"""Read a USGS ShakeMap grid into the shaking inputs the ground-failure models need.

Two entry points, both returning the same :class:`ShakeMapGrid`:

``read_grid_xml``
    The real ShakeMap ``grid.xml`` product (network-fetched, or a local copy).
``read_slice_csv``
    The committed offline slice under ``tests/fixtures/cascade/<event>/``, whose rows are the
    ``grid.xml`` rows for a window with the columns rupture uses kept verbatim.

Neither invents a value. A cell outside the grid is an error, not an extrapolation.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from rupture.domain.common import Provenance, utc_now
from rupture.domain.groundmotion import GroundMotionEngineId, GroundMotionField, Site

FloatArray = npt.NDArray[np.float64]

ADAPTER_VERSION = "0.1.0"

_SPEC_RE = re.compile(r"<grid_specification\s([^/]*)/>")
_ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
_EVENT_RE = re.compile(r"<event\s([^/]*)/>")

COLUMN_FOR_FIELD = {"pga_pct_g": "PGA", "pgv_cm_s": "PGV", "vs30_m_s": "SVEL"}
"""Fixture-CSV column names and the ShakeMap ``grid_field`` they were copied from."""


@dataclass(frozen=True, slots=True)
class ShakeMapGrid:
    """A regular lon/lat ShakeMap grid, with the bands rupture reads.

    ``longitudes`` ascend, ``latitudes`` descend (the ShakeMap row order). ``bands`` maps a
    ShakeMap field name (``PGA``, ``PGV``, ``SVEL``) to a ``(nlat, nlon)`` array in the source's
    own units: PGA in %g, PGV in cm/s, SVEL (Vs30) in m/s.
    """

    longitudes: FloatArray
    latitudes: FloatArray
    bands: dict[str, FloatArray]
    event_id: str
    magnitude: float | None
    shakemap_version: str | None
    source_url: str | None
    source_sha256: str | None
    notes: str | None = None

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return (
            float(self.longitudes.min()),
            float(self.latitudes.min()),
            float(self.longitudes.max()),
            float(self.latitudes.max()),
        )

    def sample(self, band: str, lons: FloatArray, lats: FloatArray) -> FloatArray:
        """Bilinear sample of one band at arbitrary points, refusing to extrapolate."""
        if band not in self.bands:
            msg = f"band {band!r} not in this grid; have {sorted(self.bands)}"
            raise KeyError(msg)
        lon0, lat0, lon1, lat1 = self.bounds
        if lons.min() < lon0 or lons.max() > lon1 or lats.min() < lat0 or lats.max() > lat1:
            msg = (
                "requested points fall outside the ShakeMap grid "
                f"({lon0:.4f}, {lat0:.4f}) - ({lon1:.4f}, {lat1:.4f}); rupture does not "
                "extrapolate a ShakeMap"
            )
            raise ValueError(msg)
        field = self.bands[band]
        nlat, nlon = field.shape
        asc_lat = self.latitudes[::-1]
        fx = np.interp(lons, self.longitudes, np.arange(nlon, dtype=np.float64))
        fy = np.interp(lats, asc_lat, np.arange(nlat - 1, -1, -1, dtype=np.float64))
        x0 = np.clip(np.floor(fx).astype(np.int64), 0, nlon - 2)
        y0 = np.clip(np.floor(fy).astype(np.int64), 0, nlat - 2)
        x1, y1 = x0 + 1, y0 + 1
        tx, ty = fx - x0, fy - y0
        return (
            field[y0, x0] * (1 - tx) * (1 - ty)
            + field[y0, x1] * tx * (1 - ty)
            + field[y1, x0] * (1 - tx) * ty
            + field[y1, x1] * tx * ty
        )

    def ground_motion_field(
        self,
        *,
        imt: str,
        lons: FloatArray,
        lats: FloatArray,
        scenario_id: str,
        field_id: str | None = None,
    ) -> GroundMotionField:
        """Sample the grid onto sites and wrap it as a :class:`GroundMotionField`.

        ``imt`` is ``"PGA"`` (converted from %g to g) or ``"PGV"`` (cm/s, unchanged). Vs30 on
        every site comes from the ShakeMap ``SVEL`` band, which is what rupture has; the USGS
        ground-failure product uses a separate Wald and Allen (2007) raster, and the difference
        is reported in ``docs/CASCADE.md`` rather than papered over.
        """
        band = {"PGA": "PGA", "PGV": "PGV"}.get(imt.upper())
        if band is None:
            msg = f"imt must be PGA or PGV, got {imt!r}"
            raise ValueError(msg)
        values = self.sample(band, lons, lats)
        if band == "PGA":
            values = values / 100.0  # ShakeMap reports PGA in %g; rupture's domain is g
        vs30 = self.sample("SVEL", lons, lats)
        sites = tuple(
            Site(
                id=f"{i}",
                longitude=float(lon),
                latitude=float(lat),
                vs30=float(v),
                vs30_measured=False,
            )
            for i, (lon, lat, v) in enumerate(zip(lons, lats, vs30, strict=True))
        )
        return GroundMotionField(
            id=field_id or f"shakemap-{self.event_id}-{imt.lower()}",
            scenario_id=scenario_id,
            imt=imt.upper(),
            sites=sites,
            values=(tuple(float(v) for v in values),),
            engine=GroundMotionEngineId.NATIVE_GSIM,
            engine_version=f"usgs-shakemap:{self.shakemap_version or 'unknown'}",
            gsim="usgs-shakemap-grid",
            computed_at=utc_now(),
            provenance=Provenance(
                source="usgs-shakemap",
                source_url=self.source_url,
                retrieved_at=utc_now(),
                sha256=self.source_sha256,
                licence="public-domain (USGS)",
                adapter_version=ADAPTER_VERSION,
                notes=(
                    "not computed by a GSIM: this is the published ShakeMap grid, bilinearly "
                    "sampled onto the requested cells. Vs30 is the ShakeMap SVEL band."
                ),
            ),
            notes=self.notes,
        )


def read_grid_xml(
    path: Path, *, source_url: str | None = None, source_sha256: str | None = None
) -> ShakeMapGrid:
    """Parse a ShakeMap ``grid.xml``. Reads the whole file; these are tens of megabytes."""
    text = path.read_text(encoding="utf-8")
    spec_match = _SPEC_RE.search(text)
    if spec_match is None:
        msg = f"{path} has no <grid_specification>; is it a ShakeMap grid.xml?"
        raise ValueError(msg)
    spec = dict(_ATTR_RE.findall(spec_match.group(1)))
    nlon, nlat = int(spec["nlon"]), int(spec["nlat"])
    names = re.findall(r'<grid_field index="\d+" name="(\w+)"', text)
    body = text.split("<grid_data>", 1)[1].split("</grid_data>", 1)[0].strip()
    table = np.fromstring(body, sep=" ").reshape(nlat * nlon, len(names))
    event_match = _EVENT_RE.search(text)
    event = dict(_ATTR_RE.findall(event_match.group(1))) if event_match else {}
    version_match = re.search(r'shakemap_version="([^"]*)"', text)
    grid = {name: table[:, i].reshape(nlat, nlon) for i, name in enumerate(names)}
    return ShakeMapGrid(
        longitudes=grid["LON"][0, :],
        latitudes=grid["LAT"][:, 0],
        bands={k: v for k, v in grid.items() if k in {"PGA", "PGV", "SVEL"}},
        event_id=event.get("event_id", path.stem),
        magnitude=float(event["magnitude"]) if "magnitude" in event else None,
        shakemap_version=version_match.group(1) if version_match else None,
        source_url=source_url,
        source_sha256=source_sha256,
        notes=f"ShakeMap grid.xml, {nlon}x{nlat} cells",
    )


def read_slice_csv(
    path: Path,
    *,
    event_id: str,
    magnitude: float | None = None,
    shakemap_version: str | None = None,
    source_url: str | None = None,
    source_sha256: str | None = None,
) -> ShakeMapGrid:
    """Read the committed offline ShakeMap slice (``lon,lat,pga_pct_g,pgv_cm_s,vs30_m_s``)."""
    lons_seen: list[float] = []
    lats_seen: list[float] = []
    records: dict[tuple[float, float], tuple[float, float, float]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            lon, lat = float(row["lon"]), float(row["lat"])
            lons_seen.append(lon)
            lats_seen.append(lat)
            records[lon, lat] = (
                float(row["pga_pct_g"]),
                float(row["pgv_cm_s"]),
                float(row["vs30_m_s"]),
            )
    if not records:
        msg = f"{path} is empty"
        raise ValueError(msg)
    longitudes = np.array(sorted(set(lons_seen)), dtype=np.float64)
    latitudes = np.array(sorted(set(lats_seen), reverse=True), dtype=np.float64)
    shape = (latitudes.size, longitudes.size)
    if shape[0] * shape[1] != len(records):
        msg = (
            f"{path} is not a complete rectangular grid: {len(records)} rows for a "
            f"{shape[0]}x{shape[1]} lattice"
        )
        raise ValueError(msg)
    bands = {name: np.empty(shape, dtype=np.float64) for name in ("PGA", "PGV", "SVEL")}
    lon_index = {v: i for i, v in enumerate(longitudes.tolist())}
    lat_index = {v: i for i, v in enumerate(latitudes.tolist())}
    for (lon, lat), (pga, pgv, vs30) in records.items():
        j, i = lat_index[lat], lon_index[lon]
        bands["PGA"][j, i] = pga
        bands["PGV"][j, i] = pgv
        bands["SVEL"][j, i] = vs30
    return ShakeMapGrid(
        longitudes=longitudes,
        latitudes=latitudes,
        bands=bands,
        event_id=event_id,
        magnitude=magnitude,
        shakemap_version=shakemap_version,
        source_url=source_url,
        source_sha256=source_sha256,
        notes=f"committed slice of the ShakeMap grid, {shape[1]}x{shape[0]} cells",
    )
