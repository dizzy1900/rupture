"""Avoided loss, version 1: the contract reconciled with the sibling ``serac``.

ADR-0014 said that if `serac` published a differing schema of the same name, the two would be
reconciled to a field-compatible superset and the version bumped. `serac` has now published
(read 2026-09-03), and its request envelope is genuinely different: it is cascade-warning shaped
(a `CascadeForecast`, `WarningScenario`s with lead times, interventions of kind
warning/evacuation), while rupture's is portfolio-risk shaped (a portfolio, a trigger that is a
scenario, a forecast or long-term hazard, and interventions that are retrofits and insurance
layers).

Forcing one envelope on both would make each worse. What is reconciled instead, and what makes a
consumer able to read both, is:

1. **The value vocabulary** — `MoneyRange`, `Range`, `AttributedEstimate`, `ConfidenceTier`,
   `ModelProvenance` are adopted verbatim from serac (see :mod:`rupture.domain.money`).
2. **Field aliases** — `requested_utc`/`requested_at`, `requester`/`consumer`,
   `exposure`/`portfolio` are accepted interchangeably on input.
3. **A `hazard_kind` discriminator** — `seismic` (rupture) or `cascade` (serac), so one reader can
   dispatch without guessing.
4. **A common response shape** — losses as `MoneyRange`, an avoided figure per intervention, and
   explicit `ModelProvenance`, so the answer is comparable across both projects.

`avoided-loss.v0.json` stays published and unchanged; nothing that reads v0 breaks.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from rupture.domain.common import Provenance, RuptureModel, UTCDatetime
from rupture.domain.loss import ExposurePortfolio, LossType, TriggerKind
from rupture.domain.money import ConfidenceTier, ModelProvenance, MoneyRange

CONTRACT_VERSION = "1.0.0"


class HazardKind(StrEnum):
    """Which sibling's question this is. The discriminator a shared reader dispatches on."""

    SEISMIC = "seismic"
    CASCADE = "cascade"


class InterventionKind(StrEnum):
    """Superset of rupture's structural measures and serac's warning-based ones.

    The first four are serac's enum verbatim; the rest are the measures a seismic-risk owner has.
    """

    NONE = "none"
    WARNING = "warning"
    EVACUATION = "evacuation"
    COMBINED = "combined"
    STRUCTURAL_RETROFIT = "structural_retrofit"
    AUTOMATED_SHUTDOWN = "automated_shutdown"
    LAND_USE_EXCLUSION = "land_use_exclusion"
    INSURANCE_LAYER = "insurance_layer"


class Intervention(RuptureModel):
    """Something a risk owner could do. Its effect is what avoided loss measures."""

    id: str
    kind: InterventionKind
    description: str = Field(min_length=1)
    cost: MoneyRange | None = None
    applies_to_asset_ids: tuple[str, ...] = Field(
        default=(), description="Empty means the whole portfolio."
    )
    lead_time_minutes: float | None = Field(
        default=None, ge=0.0, description="For warning-based interventions (serac's semantics)."
    )
    assumptions: tuple[str, ...] = ()
    parameters: dict[str, str | float | int | bool | None] = Field(default_factory=dict)


class AvoidedLossRequestV1(RuptureModel):
    """Ask rupture for expected loss with and without a set of interventions."""

    contract_version: str = CONTRACT_VERSION
    hazard_kind: HazardKind = HazardKind.SEISMIC
    request_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")
    requested_at: UTCDatetime = Field(
        validation_alias="requested_utc",
        serialization_alias="requested_at",
        description="Accepts serac's `requested_utc` on input.",
    )
    portfolio: ExposurePortfolio = Field(
        validation_alias="exposure", description="Accepts serac's `exposure` on input."
    )
    trigger_kind: TriggerKind
    trigger_id: str
    horizon: str | None = Field(default=None, description="e.g. '30d'; null for a scenario.")
    loss_types: tuple[LossType, ...] = (LossType.STRUCTURAL,)
    interventions: tuple[Intervention, ...] = ()
    interval_level: float = Field(default=0.9, gt=0.0, lt=1.0)
    consumer: str | None = Field(
        default=None, validation_alias="requester", description="Accepts serac's `requester`."
    )

    model_config = RuptureModel.model_config | {"populate_by_name": True}


class ResponseStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    NOT_IMPLEMENTED = "not_implemented"
    ERROR = "error"


class HazardComponent(StrEnum):
    """Avoided loss is decomposed by component so a reader can see what drove it."""

    GROUND_SHAKING = "ground_shaking"
    LANDSLIDE = "landslide"
    LIQUEFACTION = "liquefaction"
    ICE_ROCK_AVALANCHE = "ice_rock_avalanche"


class AssetLoss(RuptureModel):
    """Loss attributable to one asset, decomposed by hazard component."""

    asset_id: str
    loss_type: LossType
    expected_loss: MoneyRange
    by_component: dict[HazardComponent, float] = Field(
        default_factory=dict, description="Component shares of the best estimate, same currency."
    )


class InterventionOutcome(RuptureModel):
    """What one intervention changes."""

    intervention_id: str
    expected_loss: MoneyRange
    avoided_vs_baseline: MoneyRange
    by_asset: tuple[AssetLoss, ...] = ()
    assumptions: tuple[str, ...] = ()


class AvoidedLossResponseV1(RuptureModel):
    """Expected loss with and without interventions, with intervals and provenance."""

    contract_version: str = CONTRACT_VERSION
    hazard_kind: HazardKind = HazardKind.SEISMIC
    request_id: str
    status: ResponseStatus
    computed_at: UTCDatetime = Field(
        validation_alias="computed_utc", serialization_alias="computed_at"
    )
    baseline: tuple[AssetLoss, ...] = ()
    baseline_total: MoneyRange | None = None
    interventions: tuple[InterventionOutcome, ...] = ()
    model_ids: tuple[str, ...] = ()
    provenance_kind: ModelProvenance = ModelProvenance.STUB
    confidence: ConfidenceTier = ConfidenceTier.UNQUALIFIED
    n_realisations: int | None = Field(default=None, ge=1)
    provenance: Provenance | None = None
    assumptions: tuple[str, ...] = ()
    message: str | None = None

    model_config = RuptureModel.model_config | {"populate_by_name": True}

    @model_validator(mode="after")
    def _stub_cannot_claim_confidence(self) -> Self:
        if (
            self.provenance_kind == ModelProvenance.STUB
            and self.confidence != ConfidenceTier.UNQUALIFIED
        ):
            msg = "a stub response may only claim ConfidenceTier.UNQUALIFIED"
            raise ValueError(msg)
        return self
