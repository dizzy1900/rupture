"""The ``AlarmSet`` arm: a region, a window, and a declaration.

An alarm is not a rate. It says "somewhere in these cells, between these two instants, at or
above this magnitude" and it stops there. ADR-0055 gives it its own arm precisely so that nobody
has to invent a probability model for it — an invented model becomes the thing under test rather
than the alarm, which is how a precursor community's claim gets scored against a strawman version
of itself.

Two shapes are the same object here. A *binary* alarm set declares a fixed footprint: values are
0 or 1 and ``declared_threshold`` is set. A *graded* alarm function assigns every cell a real
number, higher meaning more alarming, and is swept over thresholds to trace a Molchan diagram; it
carries a ``declared_threshold`` only if its author committed to one operating point in advance.
The distinction matters to the scorer: a probability gain quoted at a threshold chosen after
seeing the targets is not a result, so :mod:`rupture.scoring.alarm` reports gain at a declared
operating point separately from the swept trajectory, and says which it is.

Provenance fields mirror :class:`~rupture.domain.forecast.ForecastGrid` so that the same leakage
assertions apply: ``fit_cutoff`` and ``training_catalog_hash`` pin what the author could see, and
``parameter_snapshot_hash`` pins the rule they committed to.
"""

from __future__ import annotations

import math
from datetime import timedelta
from enum import StrEnum

import numpy as np
import numpy.typing as npt
from pydantic import Field, model_validator

from rupture.domain.common import RuptureModel, UTCDatetime
from rupture.domain.forecast import format_horizon


class AlarmSet(RuptureModel):
    """Cells declared, or graded for declaration, over one window at or above one magnitude.

    ``alarm_values[i]`` is the alarm level of cell ``i``; the ordering of ``cell_origins`` is the
    ordering of ``alarm_values`` and matches ``ForecastGrid.cell_origins`` for the same region and
    cell size, which is what lets a rate forecast supply the reference measure for an alarm.
    """

    id: str
    region_id: str
    model_id: str
    model_version: str
    issue_time: UTCDatetime
    horizon: timedelta
    target_min_magnitude: float = Field(ge=0.0, le=9.0)
    cell_size_deg: float = Field(gt=0.0)
    cell_origins: tuple[tuple[float, float], ...] = Field(min_length=1)
    alarm_values: tuple[float, ...] = Field(min_length=1)
    declared_threshold: float | None = Field(
        default=None,
        description=(
            "The operating point the author committed to before seeing the targets. None means "
            "the claim is the whole trajectory and no single gain may be quoted as *the* result."
        ),
    )
    binary: bool = Field(
        default=False, description="True when alarm_values are 0/1 and the footprint is fixed."
    )
    fit_cutoff: UTCDatetime = Field(description="Nothing at or after this instant informed it.")
    training_catalog_hash: str
    parameter_snapshot_hash: str
    created_at: UTCDatetime
    notes: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> AlarmSet:
        if self.horizon <= timedelta(0):
            msg = "horizon must be positive"
            raise ValueError(msg)
        if len(self.alarm_values) != len(self.cell_origins):
            msg = "alarm_values must have one value per cell"
            raise ValueError(msg)
        for v in self.alarm_values:
            if not math.isfinite(v):
                msg = "alarm values must be finite"
                raise ValueError(msg)
        if self.binary and any(v not in (0.0, 1.0) for v in self.alarm_values):
            msg = "a binary alarm set may only hold values 0.0 and 1.0"
            raise ValueError(msg)
        if self.binary and self.declared_threshold is None:
            msg = "a binary alarm set declares its footprint, so declared_threshold is required"
            raise ValueError(msg)
        if self.issue_time < self.fit_cutoff:
            msg = "issue_time must not precede fit_cutoff"
            raise ValueError(msg)
        return self

    @property
    def window_end(self) -> UTCDatetime:
        return self.issue_time + self.horizon

    @property
    def n_cells(self) -> int:
        return len(self.cell_origins)

    def values(self) -> npt.NDArray[np.float64]:
        return np.asarray(self.alarm_values, dtype=np.float64)

    def declared_footprint(self) -> npt.NDArray[np.bool_]:
        """The cells the author declared. Raises when no operating point was committed to."""
        if self.declared_threshold is None:
            msg = (
                f"alarm set {self.id!r} declared no operating point; a probability gain at a "
                "threshold chosen after the targets were seen is not a result. Score the "
                "trajectory instead."
            )
            raise ValueError(msg)
        return self.values() >= self.declared_threshold

    @staticmethod
    def make_id(model_id: str, region_id: str, issue_time: UTCDatetime, horizon: timedelta) -> str:
        return f"{model_id}-{region_id}-{issue_time:%Y%m%dT%H%M%SZ}-{format_horizon(horizon)}"


class ReferenceKind(StrEnum):
    """What the alarm was scored against. The scorer refuses to publish some of these alone."""

    CLUSTERING_AWARE = "clustering-aware"
    """A fitted ETAS rate, or any spatially varying reference carrying the clustering. Required."""

    SPATIALLY_VARYING_POISSON = "spatially-varying-poisson"
    """Smoothed seismicity: varies in space, carries no time clustering. Permitted, and labelled."""

    SPATIALLY_UNIFORM = "spatially-uniform"
    """Uniform over the region. Permitted only as a *contrast*, never as the reference of record."""


class MolchanPoint(RuptureModel):
    """One threshold on the trajectory: the alarm fraction it buys and the misses it leaves."""

    threshold: float
    tau: float = Field(ge=0.0, le=1.0, description="Alarm fraction in the reference measure.")
    nu: float = Field(ge=0.0, le=1.0, description="Miss rate: 1 - hits/targets.")
    n_alarm_cells: int = Field(ge=0)
    n_hits: int = Field(ge=0)
    probability_gain: float | None = Field(
        default=None, description="(1 - nu) / tau; None when tau is zero."
    )
    p_value: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="P(Binomial(N, tau) >= hits): the chance the reference does this well.",
    )


class AlarmScore(RuptureModel):
    """The score of one alarm set against one reference, with the power it had.

    Every field that makes the number mean something is mandatory. There is no constructor path
    that yields a probability gain without naming the reference it is a gain *over*, because the
    commonest way a published alarm result turns out to be nothing is that the reference was
    uniform (Zhang et al. 2024) or that clustering alone supplied the significance (Luen & Stark
    2008).
    """

    alarm_set_id: str
    model_id: str
    region_id: str
    reference_id: str
    reference_kind: ReferenceKind
    reference_model_id: str
    target_window_start: UTCDatetime
    target_window_end: UTCDatetime
    target_min_magnitude: float
    target_catalog_hash: str
    n_target_events: int = Field(ge=0)
    n_cells: int = Field(ge=1)

    trajectory: tuple[MolchanPoint, ...] = Field(
        description="Molchan trajectory, one point per distinct alarm threshold, tau ascending."
    )
    area_skill_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Area under the (tau, 1 - nu) trajectory. 0.5 is the reference itself.",
    )
    area_skill_p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    area_skill_simulations: int | None = Field(default=None, ge=1)

    declared_threshold: float | None = None
    declared_tau: float | None = Field(default=None, ge=0.0, le=1.0)
    declared_hits: int | None = Field(default=None, ge=0)
    declared_probability_gain: float | None = None
    declared_p_value: float | None = Field(default=None, ge=0.0, le=1.0)
    matched_random_p_value: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Footprint of the same cell count relocated at random; ADR-0055 control.",
    )
    matched_random_simulations: int | None = Field(default=None, ge=1)

    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)
    target_power: float = Field(default=0.8, gt=0.0, lt=1.0)
    power_against_gain: float | None = Field(
        default=None, description="The alternative probability gain the power figure is against."
    )
    power: float | None = Field(
        default=None, ge=0.0, le=1.0, description="P(reject | that alternative is true)."
    )
    minimum_detectable_gain: float | None = Field(
        default=None,
        description=(
            "Smallest true probability gain this test would reject the reference for at "
            "``target_power``. A null states this, not 'we saw nothing' (ADR-0055 dec. 5)."
        ),
    )
    significant: bool | None = Field(
        default=None, description="None when the test could not be decided (no targets)."
    )
    scored_at: UTCDatetime
    scorer_version: str
    notes: tuple[str, ...] = ()
