"""A pre-registration is a frozen, committed declaration of what would count as being wrong.

ADR-0056: the file is the hypothesis; git ancestry is the timestamp. This module holds the
schema only. It imports nothing outside :mod:`rupture.domain`. Git, YAML discovery and the
gate live in :mod:`rupture.preregistration` and :mod:`rupture.validation.prereg` — not in
:mod:`rupture.scoring`, which import-linter restricts to domain.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Self

from pydantic import BeforeValidator, Field, model_validator

from rupture.domain.common import RuptureModel, UTCDatetime
from rupture.domain.forecast import parse_horizon
from rupture.domain.hypothesis import HypothesisArm


def _coerce_duration(value: object) -> object:
    """Accept the project's ``7d`` form as well as ISO-8601 timedeltas."""
    if isinstance(value, timedelta):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        try:
            return parse_horizon(stripped)
        except ValueError:
            return stripped
    return value


Duration = Annotated[timedelta, BeforeValidator(_coerce_duration)]


class StatisticalPower(RuptureModel):
    """The power the design claims against a named alternative, written before any result.

    A p-value without this is not a finding (ADR-0055 decision 4). The alternative is named
    here rather than inferred later from a result that happened to look good.
    """

    alpha: float = Field(gt=0.0, lt=1.0, description="Type I error of the planned test.")
    target_power: float = Field(gt=0.0, lt=1.0, description="Power the design is sized for.")
    effect: str = Field(
        min_length=1,
        description=(
            "Named alternative the test is powered against, e.g. "
            "'probability gain G=2 against the clustering-aware reference'."
        ),
    )


class Preregistration(RuptureModel):
    """Committed experiment declaration (ADR-0056 decision 1). Frozen; extra fields forbidden."""

    experiment_id: str = Field(min_length=1)
    hypothesis: str = Field(
        min_length=1,
        description="The hypothesis in one sentence, written before any result exists.",
    )
    arm: HypothesisArm
    region_id: str = Field(min_length=1)
    magnitude_min: float = Field(ge=-2.0, le=10.0)
    magnitude_max: float = Field(ge=-2.0, le=10.0)
    magnitude_scale: str = Field(
        min_length=1,
        description=(
            "Named magnitude scale and authoritative catalogue, e.g. 'Mw (ANSS preferred)'."
        ),
    )
    lead_time: Duration
    horizon: Duration
    alarm_rate: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description="Declared alarm fraction. Required when arm is AlarmSet (ADR-0056).",
    )
    scoring_rule: str = Field(min_length=1)
    reference_baseline: str = Field(
        min_length=1,
        description="The reference the claim must beat (ADR-0059).",
    )
    as_of: UTCDatetime = Field(description="As-of instant for the evaluation vintage (ADR-0054).")
    data_vintage: str = Field(
        min_length=1,
        description="Prose description of the data vintage the experiment will be scored on.",
    )
    statistical_power: StatisticalPower
    failure_criterion: str = Field(
        min_length=1,
        description="What result would count as the hypothesis being wrong.",
    )
    test_data_paths: tuple[str, ...] = Field(
        description=(
            "Repository-relative paths whose introduction commits are C_D for the ancestry "
            "check (the DVC pointer, not the remote bytes). Empty if the test data does not "
            "exist yet (prospective); the ancestry check is then vacuous."
        ),
    )
    preregistration_commit: str | None = Field(
        default=None,
        description="Git sha of the add-commit (C_P); filled when the gate checks the file.",
    )

    @model_validator(mode="after")
    def _invariants(self) -> Self:
        if self.magnitude_min >= self.magnitude_max:
            msg = "magnitude_min must be strictly less than magnitude_max"
            raise ValueError(msg)
        if self.lead_time <= timedelta(0):
            msg = "lead_time must be positive"
            raise ValueError(msg)
        if self.horizon <= timedelta(0):
            msg = "horizon must be positive"
            raise ValueError(msg)
        if self.arm is HypothesisArm.ALARM_SET and self.alarm_rate is None:
            msg = "alarm_rate is required when arm is alarm_set"
            raise ValueError(msg)
        for path in self.test_data_paths:
            if not path or path.startswith("/") or ".." in path.split("/"):
                msg = f"test_data_paths entries must be relative repository paths, got {path!r}"
                raise ValueError(msg)
        return self
