"""Test regions."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from rupture.domain.catalog import CompletenessEstimate
from rupture.domain.common import RuptureModel


class TectonicSetting(StrEnum):
    CONTINENTAL_COLLISION = "continental_collision"
    SUBDUCTION = "subduction"
    TRANSFORM = "transform"
    INTRAPLATE = "intraplate"
    EXTENSIONAL = "extensional"
    MIXED = "mixed"
    OTHER = "other"


LonLat = tuple[float, float]


class Region(RuptureModel):
    """A polygonal test region with its forecasting grid definition and completeness metadata.

    The polygon is a single exterior ring of (longitude, latitude) pairs, closed or open.
    ``mc`` is the *fitted* completeness estimate for the region (``None`` until a catalogue has
    been built); ``target_min_magnitude`` is the protocol threshold, which the evaluation protocol
    ties to the published Mc and only changes by ADR.
    """

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    polygon: tuple[LonLat, ...] = Field(min_length=3)
    depth_min_km: float = 0.0
    depth_max_km: float = Field(gt=0.0)
    tectonic_setting: TectonicSetting
    cell_size_deg: float = Field(default=0.1, gt=0.0)
    target_min_magnitude: float = Field(ge=0.0, le=9.0)
    magnitude_bin_width: float = Field(default=0.1, gt=0.0)
    magnitude_max: float = Field(default=8.95)
    mc: CompletenessEstimate | None = None
    description: str | None = None
    references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _checks(self) -> Region:
        if self.depth_min_km >= self.depth_max_km:
            msg = "depth_min_km must be below depth_max_km"
            raise ValueError(msg)
        for lon, lat in self.polygon:
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                msg = f"polygon vertex out of range: {(lon, lat)}"
                raise ValueError(msg)
        return self

    def closed_ring(self) -> tuple[LonLat, ...]:
        ring = self.polygon
        return ring if ring[0] == ring[-1] else (*ring, ring[0])

    def bbox(self) -> tuple[float, float, float, float]:
        lons = [p[0] for p in self.polygon]
        lats = [p[1] for p in self.polygon]
        return (min(lons), min(lats), max(lons), max(lats))

    def to_geojson(self) -> dict[str, Any]:
        """GeoJSON Feature with the region metadata as properties."""
        props = self.model_dump(mode="json", exclude={"polygon"})
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [[list(p) for p in self.closed_ring()]]},
            "properties": props,
        }

    def magnitude_bin_edges(self) -> tuple[float, ...]:
        """Lower edges of the magnitude bins from the target threshold to ``magnitude_max``."""
        edges: list[float] = []
        m = self.target_min_magnitude
        while m <= self.magnitude_max + 1e-9:
            edges.append(round(m, 6))
            m += self.magnitude_bin_width
        return tuple(edges)
