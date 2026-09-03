"""Operational aftershock forecasts.

This is the one genuinely operational F1 product: given a mainshock, the probability of further
events of magnitude at least *m* within a horizon. It is a rate forecast conditioned on an
observed sequence, and it is settled practice; it is still not a claim about individual events.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Self

from pydantic import Field, model_validator

from rupture.domain.common import RuptureModel, UTCDatetime


class MagnitudeProbability(RuptureModel):
    """Probability of at least one event with magnitude >= threshold in the window."""

    magnitude: float = Field(ge=0.0, le=10.0)
    probability: float = Field(ge=0.0, le=1.0)
    expected_count: float = Field(ge=0.0)

    @model_validator(mode="after")
    def _finite(self) -> Self:
        if not math.isfinite(self.expected_count):
            msg = "expected_count must be finite"
            raise ValueError(msg)
        return self


class AftershockForecast(RuptureModel):
    """A gridded, magnitude-binned aftershock rate forecast for one mainshock sequence.

    ``elapsed`` is the time from the mainshock to ``issue_time``; the sequence catalogue the model
    saw ends strictly before ``issue_time`` (the leakage rule applies here exactly as it does to
    the scheduled forecasts).
    """

    id: str
    mainshock_event_id: str
    mainshock_time: UTCDatetime
    mainshock_magnitude: float
    region_id: str
    issue_time: UTCDatetime
    horizon: timedelta
    elapsed: timedelta
    model_id: str
    model_version: str
    parameter_snapshot_hash: str
    n_sequence_events: int = Field(ge=0)
    probabilities: tuple[MagnitudeProbability, ...] = Field(min_length=1)
    forecast_grid_id: str | None = Field(
        default=None, description="The gridded ForecastGrid this summarises, when one was written."
    )
    created_at: UTCDatetime
    notes: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.horizon <= timedelta(0):
            msg = "horizon must be positive"
            raise ValueError(msg)
        if self.elapsed < timedelta(0):
            msg = "elapsed must not be negative"
            raise ValueError(msg)
        if self.issue_time < self.mainshock_time:
            msg = "issue_time cannot precede the mainshock"
            raise ValueError(msg)
        mags = [p.magnitude for p in self.probabilities]
        if mags != sorted(mags):
            msg = "probabilities must be ordered by increasing magnitude"
            raise ValueError(msg)
        return self

    @property
    def window_end(self) -> UTCDatetime:
        return self.issue_time + self.horizon
