"""Registry of the public contracts and their JSON Schema export.

Each entry maps a contract file name in ``contracts/`` to the pydantic model that defines it.
Versioning policy (ADR-0013): the ``.vN`` in the file name is the contract version; changes
within a version are additive only; breaking changes bump N and keep the old file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from rupture.domain.aftershock import AftershockForecast
from rupture.domain.avoided_loss_v1 import AvoidedLossRequestV1, AvoidedLossResponseV1
from rupture.domain.cascade import CascadeExposure, GroundFailureField
from rupture.domain.catalog import Catalog
from rupture.domain.evaluation import EvaluationResult
from rupture.domain.event import Event
from rupture.domain.forecast import FitResult, ForecastGrid
from rupture.domain.groundmotion import GroundMotionField
from rupture.domain.hazard import HazardCurveSet
from rupture.domain.loss import (
    AvoidedLossRequest,
    AvoidedLossResponse,
    ExposurePortfolio,
    LossResult,
)
from rupture.domain.region import Region
from rupture.domain.source_type import SourceTypeAssessment
from rupture.domain.vulnerability import ConsequenceModel, FragilityModel

SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
ID_BASE = "https://github.com/dizzy1900/rupture/contracts/"


class _AvoidedLoss(BaseModel):
    """Envelope so request and response ship in one schema file, as serac's contract does."""

    request: AvoidedLossRequest
    response: AvoidedLossResponse


class _AvoidedLossV1(BaseModel):
    """v1: the envelope reconciled with serac (ADR-0021)."""

    request: AvoidedLossRequestV1
    response: AvoidedLossResponseV1


CONTRACTS: dict[str, type[BaseModel]] = {
    "event.v0.json": Event,
    "catalog.v0.json": Catalog,
    "region.v0.json": Region,
    "forecast-grid.v0.json": ForecastGrid,
    "fit-result.v0.json": FitResult,
    "evaluation-result.v0.json": EvaluationResult,
    "hazard-curve-set.v0.json": HazardCurveSet,
    "exposure-portfolio.v0.json": ExposurePortfolio,
    "loss-result.v0.json": LossResult,
    "avoided-loss.v0.json": _AvoidedLoss,
    "avoided-loss.v1.json": _AvoidedLossV1,
    "ground-motion-field.v0.json": GroundMotionField,
    "fragility-model.v0.json": FragilityModel,
    "consequence-model.v0.json": ConsequenceModel,
    "ground-failure-field.v0.json": GroundFailureField,
    "cascade-exposure.v0.json": CascadeExposure,
    "aftershock-forecast.v0.json": AftershockForecast,
    "source-type-assessment.v0.json": SourceTypeAssessment,
}


def schema_for(name: str) -> dict[str, Any]:
    """JSON Schema (draft 2020-12) for one contract, with a stable ``$id``."""
    model = CONTRACTS[name]
    schema = model.model_json_schema(mode="serialization")
    schema = {"$schema": SCHEMA_DIALECT, "$id": ID_BASE + name, **schema}
    if name == "avoided-loss.v1.json":
        schema["title"] = "AvoidedLoss.v1"
        schema["description"] = (
            "rupture's avoided-loss contract, version 1: the value vocabulary (MoneyRange, "
            "ConfidenceTier, ModelProvenance, AttributedEstimate) is shared verbatim with the "
            "sibling serac repository, serac's field names are accepted as aliases, and "
            "hazard_kind discriminates a seismic request from a cascade one. See ADR-0021."
        )
    if name == "avoided-loss.v0.json":
        schema["title"] = "AvoidedLoss"
        schema["description"] = (
            "rupture's public avoided-loss contract: expected loss to a portfolio with and without "
            "interventions, with intervals. Shared by file with the sibling serac repository."
        )
    return schema


def render(name: str) -> str:
    return json.dumps(schema_for(name), indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def export_all(directory: Path) -> list[Path]:
    """Write every contract; returns the paths written."""
    directory.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name in CONTRACTS:
        path = directory / name
        path.write_text(render(name), encoding="utf-8")
        written.append(path)
    return written


def drift(directory: Path) -> list[str]:
    """Names of contracts whose checked-in file differs from the current models (or is missing)."""
    out: list[str] = []
    for name in CONTRACTS:
        path = directory / name
        if not path.exists() or path.read_text(encoding="utf-8") != render(name):
            out.append(name)
    return out
