"""Azimuthal-equidistant projection between (longitude, latitude) and local kilometres.

EarthquakeNPP (Stockman, Lawson & Werner, TMLR 2026; ``ss15859/EarthquakeNPP``, MIT) ships its
catalogues with both ``longitude, latitude`` and projected ``x, y`` in kilometres, and its
``Datasets/README.md`` directs point-process models to use ``x, y`` because ETAS works in
great-circle kilometres. rupture adopts that convention: learned kernels are isotropic in
kilometres, not in degrees, so a cell at 37 N and a cell at 32 N mean the same thing to the model.

The projection is exact at the origin and distorts with distance from it (an azimuthal
equidistant projection preserves distance *from the centre* only). Region polygons here span a few
hundred kilometres, where the error is small; the centre is the region's bounding-box centre and
is stored with the fitted model so a reload reproduces it exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from rupture.domain import Region

# The Earth radius the ``etas`` package uses, so distances match the baseline's.
EARTH_RADIUS_KM = 6.3781e3

_F8 = npt.NDArray[np.float64]


@dataclass(frozen=True)
class Projection:
    """Azimuthal equidistant projection about ``(lon0, lat0)``, in kilometres."""

    lon0: float
    lat0: float
    radius_km: float = EARTH_RADIUS_KM

    @classmethod
    def for_region(cls, region: Region) -> Projection:
        min_lon, min_lat, max_lon, max_lat = region.bbox()
        return cls(lon0=(min_lon + max_lon) / 2.0, lat0=(min_lat + max_lat) / 2.0)

    def to_dict(self) -> dict[str, float]:
        return {"lon0": self.lon0, "lat0": self.lat0, "radius_km": self.radius_km}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Projection:
        return cls(
            lon0=float(raw["lon0"]), lat0=float(raw["lat0"]), radius_km=float(raw["radius_km"])
        )

    def forward(self, lon: npt.ArrayLike, lat: npt.ArrayLike) -> tuple[_F8, _F8]:
        """(lon, lat) in degrees -> (x, y) in kilometres east/north of the origin."""
        lam = np.radians(np.asarray(lon, dtype=np.float64) - self.lon0)
        phi = np.radians(np.asarray(lat, dtype=np.float64))
        phi1 = math.radians(self.lat0)
        cos_c = np.sin(phi1) * np.sin(phi) + np.cos(phi1) * np.cos(phi) * np.cos(lam)
        cos_c = np.clip(cos_c, -1.0, 1.0)
        c = np.arccos(cos_c)
        sin_c = np.sin(c)
        # k -> 1 as c -> 0; the limit is taken explicitly to avoid 0/0.
        k = np.where(sin_c > 1e-12, c / np.where(sin_c > 1e-12, sin_c, 1.0), 1.0)
        x = self.radius_km * k * np.cos(phi) * np.sin(lam)
        north = np.cos(phi1) * np.sin(phi) - np.sin(phi1) * np.cos(phi) * np.cos(lam)
        y = self.radius_km * k * north
        return np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)

    def inverse(self, x: npt.ArrayLike, y: npt.ArrayLike) -> tuple[_F8, _F8]:
        """(x, y) in kilometres -> (lon, lat) in degrees."""
        xa = np.asarray(x, dtype=np.float64)
        ya = np.asarray(y, dtype=np.float64)
        phi1 = math.radians(self.lat0)
        rho = np.hypot(xa, ya)
        c = rho / self.radius_km
        safe = rho > 1e-12
        rho_safe = np.where(safe, rho, 1.0)
        sin_c, cos_c = np.sin(c), np.cos(c)
        sin_phi = np.where(
            safe, cos_c * math.sin(phi1) + ya * sin_c * math.cos(phi1) / rho_safe, math.sin(phi1)
        )
        phi = np.arcsin(np.clip(sin_phi, -1.0, 1.0))
        lam = np.where(
            safe,
            np.arctan2(xa * sin_c, rho_safe * math.cos(phi1) * cos_c - ya * math.sin(phi1) * sin_c),
            0.0,
        )
        lon = self.lon0 + np.degrees(lam)
        return np.asarray(lon, dtype=np.float64), np.asarray(np.degrees(phi), dtype=np.float64)
