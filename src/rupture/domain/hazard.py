"""Hazard outputs (F0)."""

from __future__ import annotations

from pydantic import Field, model_validator

from rupture.domain.common import Provenance, RuptureModel, UTCDatetime


class HazardCurve(RuptureModel):
    """Probability of exceedance of intensity measure levels at one site for one IMT."""

    site_longitude: float = Field(ge=-180.0, le=180.0)
    site_latitude: float = Field(ge=-90.0, le=90.0)
    imt: str = Field(
        description="Intensity measure type, OpenQuake spelling, e.g. 'PGA', 'SA(0.3)'."
    )
    imls: tuple[float, ...] = Field(
        min_length=1, description="Intensity measure levels (g for PGA/SA)."
    )
    poes: tuple[float, ...] = Field(
        min_length=1, description="Probabilities of exceedance in investigation_time."
    )

    @model_validator(mode="after")
    def _same_length(self) -> HazardCurve:
        if len(self.imls) != len(self.poes):
            msg = "imls and poes must be the same length"
            raise ValueError(msg)
        if any(not 0.0 <= p <= 1.0 for p in self.poes):
            msg = "poes must be probabilities"
            raise ValueError(msg)
        return self


class HazardCurveSet(RuptureModel):
    """All hazard curves from one classical PSHA run (one realisation or mean)."""

    id: str
    source_model_id: str
    gsim_logic_tree_id: str | None = None
    realisation: str = Field(default="mean", description="'mean', 'quantile-0.84', or a branch id.")
    investigation_time_years: float = Field(gt=0.0)
    curves: tuple[HazardCurve, ...]
    engine: str = Field(description="e.g. 'openquake.engine'")
    engine_version: str
    job_hash: str = Field(description="sha256 of the job configuration and inputs.")
    computed_at: UTCDatetime
    provenance: Provenance
    notes: str | None = None
