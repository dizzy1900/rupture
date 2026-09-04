"""Triggered cascades: earthquake-induced ground failure and co-seismic slope exposure.

**These are susceptibility and exposure products, not forecasts of individual failures.** The
USGS ground-failure models give the probability (or areal fraction) of landsliding given shaking
and static conditioning factors; they do not say a particular slope will fail. rupture labels
every cascade output accordingly, and the language gate enforces the vocabulary.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from rupture.domain.common import Provenance, RuptureModel, UTCDatetime
from rupture.domain.money import ConfidenceTier, ModelProvenance
from rupture.domain.region import LonLat


class CascadeKind(StrEnum):
    LANDSLIDE = "landslide"
    LIQUEFACTION = "liquefaction"
    ICE_ROCK_AVALANCHE = "ice_rock_avalanche"


class GroundFailureCell(RuptureModel):
    """One grid cell of a ground-failure model output."""

    longitude: float = Field(ge=-180.0, le=180.0)
    latitude: float = Field(ge=-90.0, le=90.0)
    probability: float = Field(ge=0.0, le=1.0, description="P(failure) or areal fraction.")
    areal_coverage: float | None = Field(default=None, ge=0.0, le=1.0)


class GroundFailureField(RuptureModel):
    """A gridded ground-failure susceptibility product for one event or scenario."""

    id: str
    kind: CascadeKind
    scenario_id: str
    model_id: str = Field(description="e.g. 'nowicki_jessee_2018', 'zhu_2017_coastal'.")
    model_version: str
    cells: tuple[GroundFailureCell, ...] = Field(min_length=1)
    cell_size_deg: float = Field(gt=0.0)
    shaking_source: str = Field(description="ShakeMap grid id, or the GroundMotionField id.")
    computed_at: UTCDatetime
    provenance: Provenance
    source_refs: tuple[str, ...] = ()
    notes: str | None = None

    @model_validator(mode="after")
    def _finite(self) -> Self:
        for c in self.cells:
            if not math.isfinite(c.probability):
                msg = "ground-failure probabilities must be finite"
                raise ValueError(msg)
        return self

    def mean_probability(self) -> float:
        return sum(c.probability for c in self.cells) / len(self.cells)


class ExposedSlopeUnit(RuptureModel):
    """A slope unit flagged as shaken above a threshold. Fields mirror serac's `slope-unit.v0`.

    The unit carries its own footprint (`polygon`, an exterior ring in EPSG:4326) so a
    :class:`CascadeExposure` can be written as GeoParquet and overlaid in a GIS. `polygon` is
    empty when the slope-unit source carries no geometry, which is a statement about the source,
    not a licence to invent one. `representative_longitude` / `representative_latitude` are the
    point at which `pga_g` was actually sampled.
    """

    id: str
    aoi_id: str | None = None
    mean_slope_deg: float | None = Field(default=None, ge=0.0, le=90.0)
    glacier_cover: float | None = Field(default=None, ge=0.0, le=1.0)
    permafrost_index: float | None = Field(default=None, ge=0.0, le=1.0)
    elevation_band_m: str | None = None
    area_m2: float | None = Field(default=None, ge=0.0)
    polygon: tuple[LonLat, ...] = Field(
        default=(),
        description="Exterior ring of the unit's footprint, (lon, lat) degrees, EPSG:4326.",
    )
    representative_longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    representative_latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    pga_g: float = Field(ge=0.0, description="Ground motion received at the unit.")
    exceeds_threshold: bool
    settlements_below: tuple[str, ...] = ()
    assets_below: tuple[str, ...] = Field(
        default=(),
        description=(
            "Ids of the non-settlement assets the slope-unit source maps in the same corridor "
            "(hydropower, roads, bridges). Corridor membership, not a verified elevation "
            "relation."
        ),
    )
    source_refs: tuple[str, ...] = ()


class CascadeExposure(RuptureModel):
    """Slope units exposed to a scenario's shaking, above a stated threshold.

    Susceptibility and exposure only: this flags where a co-seismic ice or rock avalanche
    mechanism is *possible* given shaking and terrain, in the manner of Langtang 2015. It does not
    state that a slope will fail, and no consumer may read it as such.
    """

    id: str
    scenario_id: str
    aoi_id: str
    kind: CascadeKind = CascadeKind.ICE_ROCK_AVALANCHE
    pga_threshold_g: float = Field(gt=0.0)
    units: tuple[ExposedSlopeUnit, ...]
    slope_unit_source: str = Field(description="Where the inventory came from, e.g. serac export.")
    shaking_source: str | None = Field(
        default=None,
        description=(
            "Id of the GroundMotionField the PGA was sampled from: a published ShakeMap grid or "
            "a GSIM-computed scenario field. Null only for a record built before this field "
            "existed."
        ),
    )
    provenance: ModelProvenance = ModelProvenance.ASSUMED
    confidence: ConfidenceTier = ConfidenceTier.UNQUALIFIED
    computed_at: UTCDatetime
    label: str = Field(
        default="susceptibility and exposure, not a forecast of individual slope failure",
        description="Carried in the payload so a downstream reader cannot lose the caveat.",
    )
    notes: str | None = None

    @property
    def n_exceeding(self) -> int:
        return sum(1 for u in self.units if u.exceeds_threshold)
