"""Shared file contract with the sibling ``serac`` repository's discriminator."""

from __future__ import annotations

from pydantic import Field, model_validator

from rupture.domain.common import RuptureModel, UTCDatetime

CONTRACT_VERSION = "0"


class SourceTypeAssessment(RuptureModel):
    """Probability that a catalogued event is a mass movement rather than a tectonic rupture.

    Produced by a discriminator (in serac or rupture), consumed by the other side as a file.
    ``p_mass_movement + p_tectonic + p_other`` must sum to 1 within tolerance.
    """

    contract_version: str = CONTRACT_VERSION
    event_id: str = Field(description="rupture event id, or '<catalog>:<source_event_id>'.")
    source_catalog: str
    assessed_at: UTCDatetime
    p_mass_movement: float = Field(ge=0.0, le=1.0)
    p_tectonic: float = Field(ge=0.0, le=1.0)
    p_other: float = Field(default=0.0, ge=0.0, le=1.0)
    classifier_id: str
    classifier_version: str
    evidence: tuple[str, ...] = Field(default=(), description="Human-readable reasons.")
    features: dict[str, float | None] = Field(default_factory=dict)
    notes: str | None = None

    @model_validator(mode="after")
    def _sums_to_one(self) -> SourceTypeAssessment:
        total = self.p_mass_movement + self.p_tectonic + self.p_other
        if abs(total - 1.0) > 1e-6:
            msg = f"probabilities must sum to 1, got {total}"
            raise ValueError(msg)
        return self
