"""Rasterisation of catalogue history and static covariates onto the region's own lattice.

The lattice is the one the ETAS adapter uses (``rupture.adapters.forecasting.grid.build_lattice``)
so a gridded forecast lands on exactly the cells pycsep compares against the baseline. Cells that
lie inside the polygon are the model's support; the rectangular raster is only a convenience for
convolutions and is masked everywhere else.

Two kinds of input:

* **dynamic** — event-count rasters over strictly causal lookback frames. Frame ``k`` of ``T``
  covers ``[t - (T-k) * span, t - (T-1-k) * span)`` and the last frame ends exactly at the issue
  time, so no frame can contain an event at or after it (ADR-0022 decision 2).
* **static** — fault density from the GEM Global Active Faults database, historical rate, and the
  depth distribution of past seismicity. All three are computed once from events strictly before
  the fit cutoff and then frozen, so they cannot drift with the target window.

rupture does not predict earthquakes: these are the inputs to a rate model.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from rupture.adapters.forecasting.grid import Lattice, build_lattice
from rupture.domain import Catalog, Region
from rupture.models.challengers.gridded._data import assert_before_cutoff, causal_window

EARTH_RADIUS_KM = 6.3781e3

DYNAMIC_CHANNELS: tuple[str, ...] = (
    "count_ge_mc",
    "count_ge_mc_minus_1",
    "magnitude_weighted_ge_mc",
)
STATIC_CHANNELS: tuple[str, ...] = (
    "fault_density",
    "historical_rate",
    "mean_depth",
    "shallow_fraction",
)

DEFAULT_FAULTS_PARQUET = Path("data") / "interim" / "gem_active_faults.parquet"
FIXTURE_FAULTS_GEOJSON = (
    Path("data") / "fixtures" / "gem_faults" / "gem_active_faults_harmonized.nepal-bbox.geojson"
)


@dataclass(frozen=True)
class Raster:
    """The region lattice viewed as a rectangular ``(ny, nx)`` array with an in-polygon mask."""

    lattice: Lattice
    nx: int
    ny: int
    cell_index: npt.NDArray[np.int64]  # (ny, nx); -1 where the cell is outside the polygon
    mask: npt.NDArray[np.bool_]  # (ny, nx)

    @property
    def n_cells(self) -> int:
        return self.lattice.n_cells

    def to_cells(self, raster: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        """``(ny, nx)`` raster -> ``(n_cells,)`` in ``ForecastGrid.cell_origins`` order."""
        out = np.zeros(self.n_cells, dtype=np.float64)
        ix = self.cell_index[self.mask]
        out[ix] = raster[self.mask]
        return out

    def from_cells(self, values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        out = np.zeros((self.ny, self.nx), dtype=np.float64)
        out[self.mask] = values[self.cell_index[self.mask]]
        return out


def build_raster(region: Region) -> Raster:
    lattice = build_lattice(region)
    keys = list(lattice.index_of)
    nx = max(k[0] for k in keys) + 1
    ny = max(k[1] for k in keys) + 1
    cell_index = np.full((ny, nx), -1, dtype=np.int64)
    for (ix, iy), idx in lattice.index_of.items():
        cell_index[iy, ix] = idx
    return Raster(lattice=lattice, nx=nx, ny=ny, cell_index=cell_index, mask=(cell_index >= 0))


# ---------------------------------------------------------------------- catalogue arrays
@dataclass(frozen=True)
class EventArrays:
    """The columns the rasteriser needs, in origin-time order, as plain numpy."""

    epoch_s: npt.NDArray[np.float64]
    longitude: npt.NDArray[np.float64]
    latitude: npt.NDArray[np.float64]
    mw: npt.NDArray[np.float64]
    depth_km: npt.NDArray[np.float64]
    cell: npt.NDArray[np.int64]
    iy: npt.NDArray[np.int64]
    ix: npt.NDArray[np.int64]

    def __len__(self) -> int:
        return int(self.epoch_s.size)


def event_arrays(catalog: Catalog, raster: Raster, region: Region) -> EventArrays:
    """Earthquakes with an Mw, inside the region's cells and depth range, sorted by origin time."""
    lat = raster.lattice
    rows = [
        e
        for e in catalog.earthquakes().events
        if e.mw is not None
        and e.depth_km is not None
        and region.depth_min_km <= e.depth_km <= region.depth_max_km
    ]
    rows.sort(key=lambda e: e.origin_time)
    if not rows:
        empty_f = np.zeros(0, dtype=np.float64)
        empty_i = np.zeros(0, dtype=np.int64)
        return EventArrays(empty_f, empty_f, empty_f, empty_f, empty_f, empty_i, empty_i, empty_i)
    lons = np.array([e.longitude for e in rows], dtype=np.float64)
    lats = np.array([e.latitude for e in rows], dtype=np.float64)
    cells = lat.cell_indices(lons, lats)
    keep = cells >= 0
    ix = np.floor((lons - lat.lon0) / lat.cell_size_deg + 1e-9).astype(np.int64)
    iy = np.floor((lats - lat.lat0) / lat.cell_size_deg + 1e-9).astype(np.int64)
    return EventArrays(
        epoch_s=np.array([e.origin_time.timestamp() for e in rows], dtype=np.float64)[keep],
        longitude=lons[keep],
        latitude=lats[keep],
        mw=np.array([e.mw for e in rows], dtype=np.float64)[keep],
        depth_km=np.array([e.depth_km for e in rows], dtype=np.float64)[keep],
        cell=cells[keep],
        iy=iy[keep],
        ix=ix[keep],
    )


# ---------------------------------------------------------------------- dynamic frames
def dynamic_frames(
    events: EventArrays,
    raster: Raster,
    issue_time: datetime,
    *,
    n_frames: int,
    frame_days: float,
    mc: float,
) -> npt.NDArray[np.float32]:
    """``(n_frames, len(DYNAMIC_CHANNELS), ny, nx)`` of causal history ending at ``issue_time``.

    Counts are ``log1p``-compressed at source: raw cell counts span several orders of magnitude
    inside an aftershock sequence and the convolution is much better conditioned on the log scale.
    """
    span = frame_days * 86400.0
    start, _ = causal_window(issue_time, 0, span, n_frames)
    stop = issue_time.timestamp()
    sel = (events.epoch_s >= start) & (events.epoch_s < stop)
    out = np.zeros((n_frames, len(DYNAMIC_CHANNELS), raster.ny, raster.nx), dtype=np.float64)
    if not np.any(sel):
        return out.astype(np.float32)
    t = events.epoch_s[sel]
    frame = np.clip(np.floor((t - start) / span).astype(np.int64), 0, n_frames - 1)
    iy = events.iy[sel]
    ix = events.ix[sel]
    mw = events.mw[sel]
    complete = mw >= mc
    dense = mw >= mc - 1.0
    zeros = np.zeros_like(frame)
    np.add.at(out, (frame[complete], zeros[complete], iy[complete], ix[complete]), 1.0)
    np.add.at(out, (frame[dense], zeros[dense] + 1, iy[dense], ix[dense]), 1.0)
    np.add.at(
        out,
        (frame[complete], zeros[complete] + 2, iy[complete], ix[complete]),
        np.power(10.0, mw[complete] - mc),
    )
    return np.log1p(out).astype(np.float32)


def target_counts(
    events: EventArrays,
    raster: Raster,
    window_start: datetime,
    window_end: datetime,
    *,
    mc_lower: float,
) -> npt.NDArray[np.float32]:
    """Observed count per cell of ``mw >= mc_lower`` in ``[window_start, window_end)``."""
    sel = (
        (events.epoch_s >= window_start.timestamp())
        & (events.epoch_s < window_end.timestamp())
        & (events.mw >= mc_lower)
    )
    out = np.zeros((raster.ny, raster.nx), dtype=np.float64)
    np.add.at(out, (events.iy[sel], events.ix[sel]), 1.0)
    return out.astype(np.float32)


# ---------------------------------------------------------------------- static covariates
@dataclass(frozen=True)
class StaticCovariates:
    """``(len(STATIC_CHANNELS), ny, nx)`` plus the provenance of what actually went into it."""

    values: npt.NDArray[np.float32]
    log_prior: npt.NDArray[np.float32]  # (ny, nx) log expected count per frame, climatology
    provenance: dict[str, Any]


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return float(2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a)))


def _fault_geometries(region: Region, faults_path: Path | None) -> tuple[list[Any], dict[str, Any]]:
    """GEM GAF line geometries near the region, plus a record of which file supplied them."""
    import geopandas as gpd  # noqa: PLC0415 - heavy optional import kept local

    from rupture.adapters.sources.gem_faults import load_faults  # noqa: PLC0415

    prov: dict[str, Any] = {"source": "gem-gaf", "licence": "CC-BY-SA-4.0"}
    candidates: list[tuple[str, Path]] = []
    if faults_path is not None:
        candidates.append(("parquet", Path(faults_path)))
    candidates.append(("fixture-geojson", FIXTURE_FAULTS_GEOJSON))
    min_lon, min_lat, max_lon, max_lat = region.bbox()
    for kind, path in candidates:
        if not path.exists():
            continue
        gdf = (
            load_faults(path)
            if kind == "parquet"
            else gpd.read_file(path).set_crs("EPSG:4326", allow_override=True)
        )
        clipped = gdf.cx[min_lon:max_lon, min_lat:max_lat]
        prov.update({"file": str(path), "kind": kind, "n_features_in_bbox": len(clipped)})
        if len(clipped) == 0:
            prov["note"] = "no GAF feature intersects the region bounding box in this file"
            continue
        return list(clipped.geometry), prov
    prov.update(
        {
            "file": None,
            "n_features_in_bbox": 0,
            "note": (
                "GEM GAF unavailable in this worktree (DVC-tracked parquet absent and the "
                "committed fixture does not cover this region); the fault-density channel is "
                "all zeros and the fit records fault_density_available=false"
            ),
        }
    )
    return [], prov


def fault_density_km(
    region: Region, raster: Raster, faults_path: Path | None = DEFAULT_FAULTS_PARQUET
) -> tuple[npt.NDArray[np.float64], dict[str, Any]]:
    """Kilometres of mapped active-fault trace per cell.

    Each line segment is split into pieces no longer than a fifth of a cell and each piece's
    great-circle length is credited to the cell holding its midpoint. That is an approximation of
    an exact polygon intersection, deliberately: it is exact to within a piece length (about
    2 km at 0.1 degrees) and needs no per-cell geometry.
    """
    out = np.zeros((raster.ny, raster.nx), dtype=np.float64)
    geoms, prov = _fault_geometries(region, faults_path)
    lat = raster.lattice
    step = lat.cell_size_deg / 5.0
    for geom in geoms:
        lines = list(geom.geoms) if geom.geom_type == "MultiLineString" else [geom]
        for line in lines:
            coords = list(line.coords)
            for (x0, y0), (x1, y1) in itertools.pairwise(coords):
                n = max(1, math.ceil(max(abs(x1 - x0), abs(y1 - y0)) / step))
                for k in range(n):
                    f0, f1 = k / n, (k + 1) / n
                    ax, ay = x0 + (x1 - x0) * f0, y0 + (y1 - y0) * f0
                    bx, by = x0 + (x1 - x0) * f1, y0 + (y1 - y0) * f1
                    mx, my = (ax + bx) / 2.0, (ay + by) / 2.0
                    ix = math.floor((mx - lat.lon0) / lat.cell_size_deg + 1e-9)
                    iy = math.floor((my - lat.lat0) / lat.cell_size_deg + 1e-9)
                    if 0 <= iy < raster.ny and 0 <= ix < raster.nx and raster.mask[iy, ix]:
                        out[iy, ix] += _haversine_km(ax, ay, bx, by)
    prov["total_km_in_region"] = float(out.sum())
    return out, prov


def _gaussian_blur(field: npt.NDArray[np.float64], sigma_cells: float) -> npt.NDArray[np.float64]:
    """Separable Gaussian blur with reflecting edges (no scipy.ndimage dependency)."""
    radius = max(1, math.ceil(3.0 * sigma_cells))
    offsets = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-0.5 * (offsets / sigma_cells) ** 2)
    kernel /= kernel.sum()
    out = field
    for axis in (0, 1):
        padded = np.pad(out, [(radius, radius) if a == axis else (0, 0) for a in (0, 1)], "reflect")
        stacked = np.stack(
            [np.take(padded, range(k, k + out.shape[axis]), axis=axis) for k in range(len(kernel))]
        )
        out = np.tensordot(kernel, stacked, axes=(0, 0))
    return np.asarray(out, dtype=np.float64)


def static_covariates(
    events: EventArrays,
    raster: Raster,
    region: Region,
    cutoff: datetime,
    *,
    mc: float,
    frame_days: float,
    smoothing_sigma_cells: float,
    faults_path: Path | None = DEFAULT_FAULTS_PARQUET,
) -> StaticCovariates:
    """Static channels and the climatological log-rate, from events strictly before ``cutoff``.

    ``log_prior`` is the smoothed historical rate expressed as an expected count of
    ``mw >= mc`` events per cell per frame. The network's head is initialised to zero, so an
    untrained model issues exactly this climatology and training only ever learns the departure
    from it.
    """
    sel = events.epoch_s < cutoff.timestamp()
    if np.any(events.epoch_s[sel] >= cutoff.timestamp()):  # pragma: no cover - defensive
        msg = "static covariates: selection let a post-cutoff event through"
        raise AssertionError(msg)
    iy, ix = events.iy[sel], events.ix[sel]
    mw, depth, epoch = events.mw[sel], events.depth_km[sel], events.epoch_s[sel]

    counts = np.zeros((raster.ny, raster.nx), dtype=np.float64)
    complete = mw >= mc
    np.add.at(counts, (iy[complete], ix[complete]), 1.0)

    depth_sum = np.zeros((raster.ny, raster.nx), dtype=np.float64)
    shallow = np.zeros((raster.ny, raster.nx), dtype=np.float64)
    seen = np.zeros((raster.ny, raster.nx), dtype=np.float64)
    np.add.at(depth_sum, (iy, ix), depth)
    np.add.at(shallow, (iy, ix), (depth <= 15.0).astype(np.float64))
    np.add.at(seen, (iy, ix), 1.0)
    region_mean_depth = float(depth.mean()) if depth.size else 0.0
    region_shallow = float((depth <= 15.0).mean()) if depth.size else 0.0
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_depth = np.where(seen > 0, depth_sum / np.maximum(seen, 1.0), region_mean_depth)
        shallow_frac = np.where(seen > 0, shallow / np.maximum(seen, 1.0), region_shallow)

    faults, fault_prov = fault_density_km(region, raster, faults_path)

    span_s = float(epoch.max() - epoch.min()) if epoch.size > 1 else frame_days * 86400.0
    n_frames_seen = max(1.0, span_s / (frame_days * 86400.0))
    smoothed = _gaussian_blur(counts, smoothing_sigma_cells) * raster.mask
    total = float(smoothed.sum())
    n_cells = int(raster.mask.sum())
    if total <= 0.0:
        share = raster.mask.astype(np.float64) / max(1, n_cells)
    else:
        # 1 % of the mass spread uniformly so no in-region cell is given a zero climatology
        share = 0.99 * smoothed / total + 0.01 * raster.mask.astype(np.float64) / max(1, n_cells)
    expected_per_frame = float(counts.sum()) / n_frames_seen
    prior = np.maximum(share * max(expected_per_frame, 1e-6), 1e-12)
    log_prior = np.where(raster.mask, np.log(prior), -30.0)

    values = np.stack(
        [
            np.log1p(faults),
            np.log1p(counts),
            mean_depth / max(region.depth_max_km, 1.0),
            shallow_frac,
        ]
    ).astype(np.float32)
    values *= raster.mask.astype(np.float32)
    provenance = {
        "cutoff": cutoff.isoformat(),
        "n_events_before_cutoff": int(sel.sum()),
        "n_events_ge_mc": int(complete.sum()),
        "expected_ge_mc_per_frame": expected_per_frame,
        "frames_covered": n_frames_seen,
        "smoothing_sigma_cells": smoothing_sigma_cells,
        "fault_density_available": bool(fault_prov.get("n_features_in_bbox", 0) > 0),
        "faults": fault_prov,
        "region_mean_depth_km": region_mean_depth,
        "region_shallow_fraction": region_shallow,
        "channels": list(STATIC_CHANNELS),
    }
    return StaticCovariates(
        values=values, log_prior=log_prior.astype(np.float32), provenance=provenance
    )


# ---------------------------------------------------------------------- sample assembly
@dataclass(frozen=True)
class SampleSet:
    """Causal inputs and observed counts for a block of issue times, all before one cutoff."""

    issue_times: tuple[datetime, ...]
    window_ends: tuple[datetime, ...]
    dynamic: npt.NDArray[np.float32]  # (n, T, C_dyn, ny, nx)
    counts: npt.NDArray[np.float32]  # (n, ny, nx)

    def __len__(self) -> int:
        return len(self.issue_times)


def sample_set(
    events: EventArrays,
    raster: Raster,
    issue_times: list[datetime],
    *,
    horizon_days: float,
    n_frames: int,
    frame_days: float,
    mc: float,
    mc_lower: float,
    cutoff: datetime,
) -> SampleSet:
    """Assemble every training/validation sample, refusing any window that reaches the cutoff.

    ADR-0022 decision 1: a sample whose target window ends after ``cutoff`` is an error, not
    something to drop quietly — the caller chose the issue times and must choose them correctly.
    """
    from datetime import timedelta  # noqa: PLC0415 - local to keep the module header short

    ends = [t + timedelta(days=horizon_days) for t in issue_times]
    assert_before_cutoff(
        [e for e in ends], cutoff + timedelta(microseconds=1), what="sample target windows"
    )
    dyn = np.stack(
        [
            dynamic_frames(events, raster, t, n_frames=n_frames, frame_days=frame_days, mc=mc)
            for t in issue_times
        ]
    )
    counts = np.stack(
        [
            target_counts(events, raster, t, e, mc_lower=mc_lower)
            for t, e in zip(issue_times, ends, strict=True)
        ]
    )
    return SampleSet(
        issue_times=tuple(issue_times), window_ends=tuple(ends), dynamic=dyn, counts=counts
    )


def write_provenance(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
