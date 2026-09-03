"""Exposure, loss and the avoided-loss contract (F2). Schema only in Prompt 1.

``AvoidedLossRequest``/``AvoidedLossResponse`` are rupture's public output contract for any
downstream financial or decision layer. They are exported as ``contracts/avoided-loss.v0.json``
and kept field-compatible with the sibling ``serac`` repository's contract of the same name.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from rupture.domain.common import Provenance, RuptureModel, UTCDatetime

CONTRACT_VERSION = "0"


class LossType(StrEnum):
    STRUCTURAL = "structural"
    NONSTRUCTURAL = "nonstructural"
    CONTENTS = "contents"
    BUSINESS_INTERRUPTION = "business_interruption"
    FATALITIES = "fatalities"
    INJURIES = "injuries"
    DISPLACED = "displaced"


class TriggerKind(StrEnum):
    SCENARIO = "scenario"  # a fixed rupture / ground-motion field
    FORECAST = "forecast"  # a ForecastGrid id (time-dependent rates)
    HAZARD = "hazard"  # long-term hazard (F0) only


class Asset(RuptureModel):
    id: str
    longitude: float = Field(ge=-180.0, le=180.0)
    latitude: float = Field(ge=-90.0, le=90.0)
    taxonomy: str = Field(description="GEM taxonomy string or a consumer-defined class.")
    value: float = Field(ge=0.0, description="Replacement value in the portfolio currency.")
    occupants: float | None = Field(default=None, ge=0.0)
    attributes: dict[str, str | float | int | bool | None] = Field(default_factory=dict)


class ExposurePortfolio(RuptureModel):
    id: str
    name: str | None = None
    currency: str = Field(min_length=3, max_length=3, description="ISO 4217.")
    valuation_date: UTCDatetime
    assets: tuple[Asset, ...] = Field(min_length=1)
    provenance: Provenance


class Interval(RuptureModel):
    """A central interval on a quantity."""

    lower: float
    upper: float
    level: float = Field(default=0.9, gt=0.0, lt=1.0, description="Coverage, e.g. 0.9.")

    @model_validator(mode="after")
    def _ordered(self) -> Interval:
        if self.lower > self.upper:
            msg = "lower must not exceed upper"
            raise ValueError(msg)
        return self


class Intervention(RuptureModel):
    """Something a risk owner could do; its effect is what avoided loss measures."""

    id: str
    description: str
    cost: float | None = Field(default=None, ge=0.0)
    applies_to_asset_ids: tuple[str, ...] = Field(
        default=(), description="Empty means the whole portfolio."
    )
    parameters: dict[str, str | float | int | bool | None] = Field(default_factory=dict)


class LossResult(RuptureModel):
    portfolio_id: str
    trigger_kind: TriggerKind
    trigger_id: str
    loss_type: LossType
    expected_loss: float = Field(ge=0.0)
    interval: Interval | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    method: str = Field(description="e.g. 'openquake.scenario_risk', 'openquake.event_based_risk'.")
    method_version: str | None = None
    computed_at: UTCDatetime
    notes: str | None = None


class AvoidedLossRequest(RuptureModel):
    """Ask rupture for expected loss with and without interventions."""

    contract_version: str = CONTRACT_VERSION
    request_id: str
    requested_at: UTCDatetime
    portfolio: ExposurePortfolio
    trigger_kind: TriggerKind
    trigger_id: str = Field(description="Scenario id, ForecastGrid id, or HazardCurveSet id.")
    horizon: str | None = Field(
        default=None, description="Forecast horizon like '30d'; None for scenario/hazard."
    )
    loss_types: tuple[LossType, ...] = (LossType.STRUCTURAL,)
    interventions: tuple[Intervention, ...] = ()
    interval_level: float = Field(default=0.9, gt=0.0, lt=1.0)
    consumer: str | None = Field(default=None, description="Identifier of the requesting system.")


class InterventionOutcome(RuptureModel):
    intervention_id: str
    losses: tuple[LossResult, ...]
    avoided_expected: float
    avoided_interval: Interval | None = None


class ResponseStatus(StrEnum):
    OK = "ok"
    NOT_IMPLEMENTED = "not_implemented"
    ERROR = "error"


class AvoidedLossResponse(RuptureModel):
    contract_version: str = CONTRACT_VERSION
    request_id: str
    status: ResponseStatus
    responded_at: UTCDatetime
    baseline: tuple[LossResult, ...] = ()
    interventions: tuple[InterventionOutcome, ...] = ()
    model_ids: tuple[str, ...] = ()
    provenance: Provenance | None = None
    message: str | None = None
