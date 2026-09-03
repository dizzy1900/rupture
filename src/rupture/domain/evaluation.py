"""CSEP-style test outcomes."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from rupture.domain.common import RuptureModel, UTCDatetime


class TestName(StrEnum):
    N = "N"  # number
    M = "M"  # magnitude
    S = "S"  # spatial
    L = "L"  # likelihood
    CL = "CL"  # conditional likelihood
    T = "T"  # paired T (comparison)
    W = "W"  # Wilcoxon (comparison)


class EvaluationResult(RuptureModel):
    """One test applied to one forecast against a frozen target catalogue slice.

    ``quantile`` is the position of the observed statistic in the simulated distribution
    (one-sided tests); ``quantile_low``/``quantile_high`` are the two-sided N-test quantiles.
    ``passed`` is the protocol decision at ``alpha``. ``target_catalog_hash`` freezes the exact
    slice used, so a later catalogue revision cannot silently change the verdict.
    """

    forecast_id: str
    model_id: str
    test_name: TestName
    statistic: float = Field(
        description="Observed statistic (count, log-likelihood, IG per event...)."
    )
    quantile: float | None = Field(default=None, ge=0.0, le=1.0)
    quantile_low: float | None = Field(default=None, ge=0.0, le=1.0)
    quantile_high: float | None = Field(default=None, ge=0.0, le=1.0)
    p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    passed: bool | None = Field(
        description="None when the test could not be decided (e.g. no targets)."
    )
    benchmark_model_id: str | None = Field(default=None, description="For T/W comparisons.")
    n_target_events: int = Field(ge=0)
    n_simulations: int | None = Field(default=None, ge=1)
    target_window_start: UTCDatetime
    target_window_end: UTCDatetime
    target_catalog_hash: str
    evaluated_at: UTCDatetime
    evaluator_version: str
    notes: str | None = None
