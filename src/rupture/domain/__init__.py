"""Pure domain models. Imports nothing from adapters, pipelines, cli or validation."""

from rupture.domain.aftershock import AftershockForecast, MagnitudeProbability
from rupture.domain.alarm import AlarmScore, AlarmSet, MolchanPoint, ReferenceKind
from rupture.domain.avoided_loss_v1 import (
    AvoidedLossRequestV1,
    AvoidedLossResponseV1,
    HazardComponent,
    HazardKind,
    InterventionKind,
)
from rupture.domain.cascade import (
    CascadeExposure,
    CascadeKind,
    ExposedSlopeUnit,
    GroundFailureField,
)
from rupture.domain.catalog import (
    Bounds,
    Catalog,
    CompletenessEstimate,
    HomogenisationLogEntry,
    HomogenisationStep,
    McMethod,
)
from rupture.domain.common import Provenance, RuptureModel, UTCDatetime, sha256_hex, utc_now
from rupture.domain.completeness import (
    HELMSTETTER_2006,
    StaiCoefficients,
    stai_mc,
    stai_mc_current,
)
from rupture.domain.evaluation import EvaluationResult, TestName
from rupture.domain.event import Event, EventType, MagnitudeRecord, MagnitudeType
from rupture.domain.forecast import (
    FitResult,
    ForecastGrid,
    format_horizon,
    parse_horizon,
    snapshot_hash,
)
from rupture.domain.groundmotion import GroundMotionEngineId, GroundMotionField, Site
from rupture.domain.hazard import HazardCurve, HazardCurveSet, ScenarioRupture
from rupture.domain.hypothesis import ARM_DESCRIPTION, MANDATORY_REFERENCE, HypothesisArm
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
from rupture.domain.money import (
    AttributedEstimate,
    ConfidenceTier,
    ModelProvenance,
    MoneyRange,
    Range,
)
from rupture.domain.region import MagnitudePolicy, Region, TectonicSetting
from rupture.domain.source_type import SourceTypeAssessment
from rupture.domain.vintage import VintagePolicy, VintageSummary
from rupture.domain.vulnerability import (
    ConsequenceModel,
    DamageState,
    FragilityFunction,
    FragilityModel,
    HydropowerComponent,
)

__all__ = [
    "ARM_DESCRIPTION",
    "HELMSTETTER_2006",
    "MANDATORY_REFERENCE",
    "AftershockForecast",
    "AlarmScore",
    "AlarmSet",
    "Asset",
    "AttributedEstimate",
    "AvoidedLossRequest",
    "AvoidedLossRequestV1",
    "AvoidedLossResponse",
    "AvoidedLossResponseV1",
    "Bounds",
    "CascadeExposure",
    "CascadeKind",
    "Catalog",
    "CompletenessEstimate",
    "ConfidenceTier",
    "ConsequenceModel",
    "DamageState",
    "EvaluationResult",
    "Event",
    "EventType",
    "ExposedSlopeUnit",
    "ExposurePortfolio",
    "FitResult",
    "ForecastGrid",
    "FragilityFunction",
    "FragilityModel",
    "GroundFailureField",
    "GroundMotionEngineId",
    "GroundMotionField",
    "HazardComponent",
    "HazardCurve",
    "HazardCurveSet",
    "HazardKind",
    "HomogenisationLogEntry",
    "HomogenisationStep",
    "HydropowerComponent",
    "HypothesisArm",
    "Interval",
    "Intervention",
    "InterventionKind",
    "InterventionOutcome",
    "LossResult",
    "LossType",
    "MagnitudePolicy",
    "MagnitudeProbability",
    "MagnitudeRecord",
    "MagnitudeType",
    "McMethod",
    "ModelProvenance",
    "MolchanPoint",
    "MoneyRange",
    "Provenance",
    "Range",
    "ReferenceKind",
    "Region",
    "ResponseStatus",
    "RuptureModel",
    "ScenarioRupture",
    "Site",
    "SourceTypeAssessment",
    "StaiCoefficients",
    "TectonicSetting",
    "TestName",
    "TriggerKind",
    "UTCDatetime",
    "VintagePolicy",
    "VintageSummary",
    "format_horizon",
    "parse_horizon",
    "sha256_hex",
    "snapshot_hash",
    "stai_mc",
    "stai_mc_current",
    "utc_now",
]
