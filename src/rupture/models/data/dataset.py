"""Catalogue -> model inputs, with the cutoff enforced by refusal (ADR-0022 decision 1).

Two shapes are built here, because rupture's two learned challengers need different ones:

- :class:`EventSequence` — the marked point-process view: one row per event, time in float days
  from a fixed epoch, location in projected kilometres, magnitude as the mark. This is what the
  neural temporal point process consumes.
- :class:`GridCounts` — the raster view: counts per (time bin, cell, magnitude bin) on exactly the
  lattice and magnitude bins the evaluation protocol uses. This is what a gridded deep model
  consumes.

**The cutoff rule.** Every builder takes a ``cutoff`` and raises
:class:`~rupture.adapters.forecasting.leakage.LeakageError` if it is handed an event with
``origin_time >= cutoff``. It does not filter. Silently dropping late events would hide the bug
that supplied them, and that bug is exactly how leakage gets into a learned model. Filtering is a
separate, explicitly named act: :func:`causal_slice`. Call it, then hand the result to a builder,
and the builder proves you did.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import numpy.typing as npt
from shapely.geometry import Point

from rupture.adapters.forecasting.grid import (
    Lattice,
    build_lattice,
    magnitude_bin_indices,
    region_polygon,
)
from rupture.adapters.forecasting.leakage import LeakageError, assert_all_before
from rupture.domain import Catalog, Region, sha256_hex
from rupture.models.data.geo import Projection

_F8 = npt.NDArray[np.float64]
_I8 = npt.NDArray[np.int64]

SECONDS_PER_DAY = 86400.0


def days_between(earlier: datetime, later: datetime) -> float:
    """``later - earlier`` in float days. EarthquakeNPP's time unit; also the ``etas`` package's."""
    return (later - earlier).total_seconds() / SECONDS_PER_DAY


def epoch_plus_days(epoch: datetime, days: npt.ArrayLike) -> list[datetime]:
    return [epoch + timedelta(seconds=float(d) * SECONDS_PER_DAY) for d in np.atleast_1d(days)]


# ---------------------------------------------------------------------- explicit filtering
def causal_slice(catalog: Catalog, region: Region, cutoff: datetime, mc: float) -> Catalog:
    """Everything a model may legitimately see before ``cutoff``, as an explicit act.

    Earthquakes only, homogenised ``mw >= mc``, ``origin_time < cutoff``, epicentre inside the
    region polygon and hypocentre inside its depth range. Mirrors
    ``MizrahiETAS.training_slice`` so the baseline and the challengers are fitted on exactly the
    same events and their ``training_catalog_hash`` values are comparable.
    """
    poly = region_polygon(region)
    base = catalog.earthquakes().before(cutoff).at_least(mc)
    kept = tuple(
        e
        for e in base.events
        if poly.covers(Point(e.longitude, e.latitude))
        and (e.depth_km is None or region.depth_min_km <= e.depth_km <= region.depth_max_km)
    )
    return base.model_copy(update={"events": kept, "id": f"{base.id}/in-region"})


# ---------------------------------------------------------------------- sequence view
@dataclass(frozen=True)
class SequenceSpec:
    """Everything needed to rebuild an :class:`EventSequence` identically, carried with a model."""

    region_id: str
    mc: float
    cutoff: datetime
    epoch: datetime
    projection: Projection

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "mc": self.mc,
            "cutoff": self.cutoff.isoformat(),
            "epoch": self.epoch.isoformat(),
            "projection": self.projection.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SequenceSpec:
        return cls(
            region_id=str(raw["region_id"]),
            mc=float(raw["mc"]),
            cutoff=datetime.fromisoformat(raw["cutoff"]),
            epoch=datetime.fromisoformat(raw["epoch"]),
            projection=Projection.from_dict(raw["projection"]),
        )


@dataclass(frozen=True)
class EventSequence:
    """A time-ordered marked point pattern. Arrays are parallel and never mutated in place.

    ``t`` is float days since ``spec.epoch`` and is non-decreasing. ``x``/``y`` are kilometres
    east/north of the projection origin. ``mw`` is the homogenised moment magnitude (the mark).
    """

    spec: SequenceSpec
    event_ids: tuple[str, ...]
    t: _F8
    x: _F8
    y: _F8
    lon: _F8
    lat: _F8
    mw: _F8
    depth_km: _F8

    def __len__(self) -> int:
        return int(self.t.size)

    def __post_init__(self) -> None:
        n = len(self.event_ids)
        for name in ("t", "x", "y", "lon", "lat", "mw", "depth_km"):
            arr = getattr(self, name)
            if arr.shape != (n,):
                msg = f"{name} has shape {arr.shape}, expected ({n},)"
                raise ValueError(msg)
        if n > 1 and bool(np.any(np.diff(self.t) < 0.0)):
            msg = "event times must be non-decreasing"
            raise ValueError(msg)

    def days_of(self, when: datetime) -> float:
        return days_between(self.spec.epoch, when)

    def take(self, index: npt.ArrayLike) -> EventSequence:
        idx = np.asarray(index, dtype=np.int64)
        return EventSequence(
            spec=self.spec,
            event_ids=tuple(self.event_ids[i] for i in idx.tolist()),
            t=self.t[idx],
            x=self.x[idx],
            y=self.y[idx],
            lon=self.lon[idx],
            lat=self.lat[idx],
            mw=self.mw[idx],
            depth_km=self.depth_km[idx],
        )

    def before(self, when: datetime) -> EventSequence:
        """Events with ``origin_time < when``. Closed-left, open-right, like every other cut."""
        return self.take(np.flatnonzero(self.t < self.days_of(when)))

    def between(self, start: datetime, end: datetime) -> EventSequence:
        lo, hi = self.days_of(start), self.days_of(end)
        return self.take(np.flatnonzero((self.t >= lo) & (self.t < hi)))

    def sequence_hash(self) -> str:
        """Hash over ids and times: identifies the slice, like ``Catalog.event_hash``."""
        keys = sorted(f"{i}|{tt!r}" for i, tt in zip(self.event_ids, self.t.tolist(), strict=True))
        return sha256_hex("\n".join(keys))


def build_sequence(
    catalog: Catalog,
    region: Region,
    cutoff: datetime,
    *,
    mc: float,
    epoch: datetime | None = None,
    projection: Projection | None = None,
) -> EventSequence:
    """Build the sequence view. **Raises** on any event with ``origin_time >= cutoff``.

    ``catalog`` must already be the causal slice (:func:`causal_slice`); this function proves it
    rather than enforcing it, per ADR-0022 decision 1.
    """
    assert_all_before(catalog, cutoff, what=f"{catalog.id} handed to build_sequence")
    missing = [e.id for e in catalog.events if e.mw is None]
    if missing:
        msg = (
            f"{len(missing)} event(s) have no homogenised mw (e.g. {missing[:3]}); "
            "filter with causal_slice() first"
        )
        raise ValueError(msg)
    below = [e.id for e in catalog.events if e.mw is not None and e.mw < mc]
    if below:
        msg = f"{len(below)} event(s) are below mc={mc} (e.g. {below[:3]}); filter first"
        raise ValueError(msg)

    events = sorted(catalog.events, key=lambda e: (e.origin_time, e.id))
    proj = projection if projection is not None else Projection.for_region(region)
    start = epoch if epoch is not None else (events[0].origin_time if events else cutoff)
    spec = SequenceSpec(
        region_id=region.id, mc=float(mc), cutoff=cutoff, epoch=start, projection=proj
    )
    mw_values = [float(e.mw) for e in events if e.mw is not None]
    lon = np.array([e.longitude for e in events], dtype=np.float64)
    lat = np.array([e.latitude for e in events], dtype=np.float64)
    x, y = proj.forward(lon, lat)
    return EventSequence(
        spec=spec,
        event_ids=tuple(e.id for e in events),
        t=np.array([days_between(start, e.origin_time) for e in events], dtype=np.float64),
        x=x,
        y=y,
        lon=lon,
        lat=lat,
        mw=np.array(mw_values, dtype=np.float64),
        depth_km=np.array(
            [float(e.depth_km) if e.depth_km is not None else np.nan for e in events],
            dtype=np.float64,
        ),
    )


# ---------------------------------------------------------------------- raster view
@dataclass(frozen=True)
class GridCounts:
    """Counts on the protocol lattice: ``counts[time_bin, cell, magnitude_bin]``.

    ``time_edges`` has ``n_time_bins + 1`` entries; bin ``b`` covers
    ``[time_edges[b], time_edges[b + 1])``. ``cell_origins`` and ``magnitude_bin_edges`` are the
    same objects a :class:`~rupture.domain.ForecastGrid` carries, so a model trained on this
    tensor emits forecasts that pycsep can compare to ETAS without any regridding.
    """

    region_id: str
    time_edges: tuple[datetime, ...]
    cell_origins: tuple[tuple[float, float], ...]
    cell_size_deg: float
    magnitude_bin_edges: tuple[float, ...]
    magnitude_bin_width: float
    counts: npt.NDArray[np.int64]
    n_outside_grid: int
    n_below_threshold: int

    @property
    def n_time_bins(self) -> int:
        return len(self.time_edges) - 1

    def totals_per_bin(self) -> _I8:
        out: _I8 = self.counts.sum(axis=(1, 2))
        return out


def time_edges(start: datetime, end: datetime, step: timedelta) -> tuple[datetime, ...]:
    """Half-open bin edges ``[start, start+step), ...`` up to ``end``, never past it."""
    if step <= timedelta(0):
        msg = "step must be positive"
        raise ValueError(msg)
    if end <= start:
        msg = "end must be after start"
        raise ValueError(msg)
    edges = [start]
    while edges[-1] + step <= end:
        edges.append(edges[-1] + step)
    if len(edges) < 2:
        msg = f"step {step} does not fit once between {start.isoformat()} and {end.isoformat()}"
        raise ValueError(msg)
    return tuple(edges)


def build_grid_counts(
    catalog: Catalog,
    region: Region,
    cutoff: datetime,
    *,
    edges: Sequence[datetime],
    lattice: Lattice | None = None,
) -> GridCounts:
    """Build the raster view. **Raises** on any event at or after ``cutoff``, and on bins that
    reach it.

    The last bin edge must be at or before ``cutoff``: a training tensor whose final bin straddles
    the cutoff is the classic way a gridded model learns the future.
    """
    assert_all_before(catalog, cutoff, what=f"{catalog.id} handed to build_grid_counts")
    if len(edges) < 2:
        msg = "need at least two time edges"
        raise ValueError(msg)
    if list(edges) != sorted(edges):
        msg = "time edges must be increasing"
        raise ValueError(msg)
    if edges[-1] > cutoff:
        msg = (
            f"leakage: the last time-bin edge {edges[-1].isoformat()} is after the cutoff "
            f"{cutoff.isoformat()}; the final bin would span data the model may not see"
        )
        raise LeakageError(msg)

    lat_grid = lattice if lattice is not None else build_lattice(region)
    mag_edges = region.magnitude_bin_edges()
    n_t, n_c, n_m = len(edges) - 1, lat_grid.n_cells, len(mag_edges)
    counts = np.zeros((n_t, n_c, n_m), dtype=np.int64)
    outside = below = 0
    edge_days = np.array([e.timestamp() for e in edges], dtype=np.float64)
    for event in catalog.earthquakes().events:
        if event.mw is None or event.mw < mag_edges[0]:
            below += 1
            continue
        b = int(np.searchsorted(edge_days, event.origin_time.timestamp(), side="right")) - 1
        if b < 0 or b >= n_t:
            continue
        cell = int(lat_grid.cell_indices([event.longitude], [event.latitude])[0])
        if cell < 0:
            outside += 1
            continue
        j = int(magnitude_bin_indices([event.mw], mag_edges, region.magnitude_bin_width)[0])
        counts[b, cell, j] += 1
    return GridCounts(
        region_id=region.id,
        time_edges=tuple(edges),
        cell_origins=lat_grid.origins,
        cell_size_deg=lat_grid.cell_size_deg,
        magnitude_bin_edges=mag_edges,
        magnitude_bin_width=region.magnitude_bin_width,
        counts=counts,
        n_outside_grid=outside,
        n_below_threshold=below,
    )
