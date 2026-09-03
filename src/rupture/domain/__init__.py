"""Pure domain models. Imports nothing from adapters, pipelines, cli or validation."""

from rupture.domain.catalog import (
    Bounds,
    Catalog,
    CompletenessEstimate,
    HomogenisationLogEntry,
    HomogenisationStep,
    McMethod,
)
from rupture.domain.common import Provenance, RuptureModel, UTCDatetime, sha256_hex, utc_now
from rupture.domain.evaluation import EvaluationResult, TestName
from rupture.domain.event import Event, EventType, MagnitudeRecord, MagnitudeType
from rupture.domain.forecast import (
    FitResult,
    ForecastGrid,
    format_horizon,
    parse_horizon,
    snapshot_hash,
)
from rupture.domain.hazard import HazardCurve, HazardCurveSet
from rupture.domain.loss import (
    Asset,
    AvoidedLossRequest,
    AvoidedLossResponse,
    ExposurePortfolio,
    Interval,
    Intervention,
    InterventionOutcome,
    LossResult,
    LossType,
    ResponseStatus,
    TriggerKind,
)
from rupture.domain.region import MagnitudePolicy, Region, TectonicSetting
from rupture.domain.source_type import SourceTypeAssessment

__all__ = [
    "Asset",
    "AvoidedLossRequest",
    "AvoidedLossResponse",
    "Bounds",
    "Catalog",
    "CompletenessEstimate",
    "EvaluationResult",
    "Event",
    "EventType",
    "ExposurePortfolio",
    "FitResult",
    "ForecastGrid",
    "HazardCurve",
    "HazardCurveSet",
    "HomogenisationLogEntry",
    "HomogenisationStep",
    "Interval",
    "Intervention",
    "InterventionOutcome",
    "LossResult",
    "LossType",
    "MagnitudePolicy",
    "MagnitudeRecord",
    "MagnitudeType",
    "McMethod",
    "Provenance",
    "Region",
    "ResponseStatus",
    "RuptureModel",
    "SourceTypeAssessment",
    "TectonicSetting",
    "TestName",
    "TriggerKind",
    "UTCDatetime",
    "format_horizon",
    "parse_horizon",
    "sha256_hex",
    "snapshot_hash",
    "utc_now",
]
