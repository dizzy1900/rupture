"""Events and magnitudes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from rupture.domain.common import Provenance, RuptureModel, UTCDatetime


class EventType(StrEnum):
    """Catalogue event class. Landslide-type entries are retained and tagged, never dropped."""

    EARTHQUAKE = "earthquake"
    LANDSLIDE = "landslide"
    EXPLOSION = "explosion"
    OTHER = "other"


class MagnitudeType(StrEnum):
    """Magnitude scales seen across the merged catalogues. Lower-case, agency-neutral."""

    MW = "mw"  # moment magnitude, scale unspecified
    MWW = "mww"  # W-phase Mw
    MWC = "mwc"  # centroid moment tensor Mw (e.g. GCMT)
    MWB = "mwb"  # body-wave moment tensor Mw
    MWR = "mwr"  # regional moment tensor Mw
    MB = "mb"  # short-period body wave
    MS = "ms"  # surface wave
    ML = "ml"  # local
    MD = "md"  # duration
    MLV = "mlv"
    OTHER = "other"


class MagnitudeRecord(RuptureModel):
    """One magnitude estimate as reported by an agency."""

    value: float = Field(ge=-2.0, le=10.0)
    type: MagnitudeType
    agency: str | None = Field(
        default=None, description="Reporting network/agency code, e.g. 'us', 'ISC', 'GCMT'."
    )
    uncertainty: float | None = Field(default=None, ge=0.0)
    raw_type: str | None = Field(
        default=None, description="The type string exactly as the source gave it."
    )


class Event(RuptureModel):
    """A single catalogued event with homogenised Mw and full provenance.

    ``mw`` is the homogenised moment magnitude and ``mw_conversion`` names the method that
    produced it (e.g. ``"identity:mwc"`` when the source gave a moment magnitude, or
    ``"scordilis2006:mb"`` for a converted body-wave magnitude). Both are ``None`` when no
    accepted conversion exists for the reported scale; such events stay in the catalogue and are
    excluded from magnitude-based analyses by filter, never by deletion.
    """

    id: str = Field(
        description="rupture-wide unique id, assigned at merge; stable across rebuilds."
    )
    origin_time: UTCDatetime
    origin_time_uncertainty_s: float | None = Field(default=None, ge=0.0)
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    horizontal_uncertainty_km: float | None = Field(default=None, ge=0.0)
    depth_km: float | None = Field(default=None, ge=-10.0, le=800.0)
    depth_uncertainty_km: float | None = Field(default=None, ge=0.0)
    magnitude: MagnitudeRecord = Field(description="Preferred magnitude as reported by the source.")
    other_magnitudes: tuple[MagnitudeRecord, ...] = ()
    mw: float | None = Field(default=None, ge=-2.0, le=10.0, description="Homogenised Mw.")
    mw_conversion: str | None = Field(
        default=None, description="Method reference, '<relation>:<from_type>'."
    )
    event_type: EventType = EventType.EARTHQUAKE
    source_catalog: str = Field(description="Catalogue the preferred solution came from.")
    source_event_id: str = Field(description="The id in the source catalogue.")
    contributing_ids: tuple[str, ...] = Field(
        default=(), description="'<catalog>:<id>' for every source record merged into this event."
    )
    provenance: Provenance

    @model_validator(mode="after")
    def _mw_and_method_travel_together(self) -> Event:
        if (self.mw is None) != (self.mw_conversion is None):
            msg = "mw and mw_conversion must both be set or both be None"
            raise ValueError(msg)
        return self
