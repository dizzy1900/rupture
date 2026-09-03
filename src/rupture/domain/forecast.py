"""Gridded, magnitude-binned rate forecasts and model fits.

A :class:`ForecastGrid` holds *expected counts* per cell per magnitude bin over ``horizon``
starting at ``issue_time``. It is a forecast of rates, never a statement that an event will
take place. Everything a model saw is pinned by ``fit_cutoff`` and ``training_catalog_hash``;
the parameters it used are pinned by ``parameter_snapshot_hash``.
"""

from __future__ import annotations

import math
import re
from datetime import timedelta
from typing import Any

import numpy as np
import numpy.typing as npt
from pydantic import Field, model_validator

from rupture.domain.common import RuptureModel, UTCDatetime, sha256_hex

_HORIZON_RX = re.compile(r"^(?P<n>\d+)(?P<u>[dhwy])$")
_UNIT_SECONDS = {"h": 3600, "d": 86400, "w": 7 * 86400, "y": 365 * 86400}


def parse_horizon(text: str) -> timedelta:
    """Parse ``'30d'``, ``'7d'``, ``'12h'``, ``'1w'``, ``'1y'`` (y = 365 days) into a timedelta."""
    m = _HORIZON_RX.match(text.strip().lower())
    if not m:
        msg = f"unrecognised horizon {text!r}; use <n>[h|d|w|y]"
        raise ValueError(msg)
    return timedelta(seconds=int(m["n"]) * _UNIT_SECONDS[m["u"]])


def format_horizon(delta: timedelta) -> str:
    """Inverse of :func:`parse_horizon` for whole days/hours; falls back to seconds."""
    secs = int(delta.total_seconds())
    if secs % 86400 == 0:
        return f"{secs // 86400}d"
    if secs % 3600 == 0:
        return f"{secs // 3600}h"
    return f"{secs}s"


def snapshot_hash(parameters: dict[str, Any]) -> str:
    """Deterministic hash of a parameter dictionary (sorted keys, repr of floats)."""
    items = sorted((k, repr(v)) for k, v in parameters.items())
    return sha256_hex("\n".join(f"{k}={v}" for k, v in items))


class FitResult(RuptureModel):
    """What a model learned from a catalogue up to a hard cutoff, and how well."""

    model_id: str
    model_version: str
    region_id: str
    fit_cutoff: UTCDatetime = Field(
        description="Only events with origin_time < fit_cutoff were used."
    )
    training_start: UTCDatetime
    training_catalog_hash: str
    n_events: int = Field(ge=0)
    mc: float
    parameters: dict[str, float]
    parameter_snapshot_hash: str
    log_likelihood: float | None = None
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    converged: bool | None = None
    fitted_at: UTCDatetime
    notes: str | None = None

    @model_validator(mode="after")
    def _hash_matches(self) -> FitResult:
        if snapshot_hash(self.parameters) != self.parameter_snapshot_hash:
            msg = "parameter_snapshot_hash does not match parameters"
            raise ValueError(msg)
        return self


class ForecastGrid(RuptureModel):
    """Expected event counts per cell and magnitude bin over one horizon from one issue time.

    ``cell_origins`` are the lower-left (longitude, latitude) corners of square cells of side
    ``cell_size_deg``. ``magnitude_bin_edges`` are the lower edges of bins of width
    ``magnitude_bin_width``; the last bin is open. ``expected_counts[i][j]`` is for cell ``i``,
    bin ``j``. All counts are finite and non-negative.
    """

    id: str
    region_id: str
    model_id: str
    model_version: str
    parameter_snapshot_hash: str
    fit_cutoff: UTCDatetime
    training_catalog_hash: str
    issue_time: UTCDatetime
    horizon: timedelta
    cell_size_deg: float = Field(gt=0.0)
    cell_origins: tuple[tuple[float, float], ...] = Field(min_length=1)
    magnitude_bin_edges: tuple[float, ...] = Field(min_length=1)
    magnitude_bin_width: float = Field(gt=0.0)
    expected_counts: tuple[tuple[float, ...], ...]
    n_simulations: int | None = Field(default=None, ge=1)
    created_at: UTCDatetime
    notes: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ForecastGrid:
        if self.horizon <= timedelta(0):
            msg = "horizon must be positive"
            raise ValueError(msg)
        if len(self.expected_counts) != len(self.cell_origins):
            msg = "expected_counts must have one row per cell"
            raise ValueError(msg)
        nb = len(self.magnitude_bin_edges)
        for row in self.expected_counts:
            if len(row) != nb:
                msg = "each expected_counts row must have one value per magnitude bin"
                raise ValueError(msg)
            for v in row:
                if not math.isfinite(v) or v < 0.0:
                    msg = "expected counts must be finite and non-negative"
                    raise ValueError(msg)
        return self

    @property
    def window_end(self) -> UTCDatetime:
        return self.issue_time + self.horizon

    def counts(self) -> npt.NDArray[np.float64]:
        """(n_cells, n_bins) float64 array."""
        return np.asarray(self.expected_counts, dtype=np.float64)

    def total_expected(self) -> float:
        return float(self.counts().sum())

    @staticmethod
    def make_id(model_id: str, region_id: str, issue_time: UTCDatetime, horizon: timedelta) -> str:
        return f"{model_id}-{region_id}-{issue_time:%Y%m%dT%H%M%SZ}-{format_horizon(horizon)}"
