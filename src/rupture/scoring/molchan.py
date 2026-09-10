"""Molchan trajectories, area skill scores and probability gains, on plain arrays.

This module is deliberately free of every rupture type. It takes an alarm function, a reference
measure and the cells the target events fell in, and returns numbers. ADR-0061 says rupture
interoperates with CSEP rather than forking it, and ADR-0055 records that pyCSEP has no
alarm-forecast class at all; keeping the mathematics in an array-only module is what makes it
possible to upstream this without dragging rupture's domain along.

The construction, following Zechar & Jordan (2008, *Tectonophysics*, `widely-used`):

* Cells are ordered by descending alarm value and grouped by *distinct* value, so that a tie is
  never broken by array order.
* ``tau`` at a threshold is the reference mass covered by the cells at or above it — the fraction
  of the events the reference model expects to be inside the alarm, not the fraction of the area.
* ``nu`` is the miss rate: one minus the fraction of target events inside the alarm.
* The **area skill score** is the area under the ``(tau, 1 - nu)`` trajectory. The reference model
  itself scores 0.5 by construction; 1.0 is a perfect alarm.
* The **probability gain** at a threshold is ``(1 - nu) / tau``.

Under the null that the target events are independent draws from the reference measure, the hits
in an alarm of mass ``tau`` are ``Binomial(N, tau)``, which gives every point on the trajectory an
exact one-sided p-value and gives the whole test an exact power calculation
(:mod:`rupture.scoring.power`).

Two things this is *not*. It is not cell-level AUC, which ADR-0055 decision 6 refuses: that metric
ranks cells and drowns in the 99.99 % of cells with no event, whereas the area skill score weights
by events on one axis and by the reference measure on the other, which is the fix for exactly that
imbalance. And a trajectory is not a result on its own — the gain quoted from the best point of a
swept trajectory is a maximum over thresholds and is biased upward, which is why
:func:`score_arrays` reports a declared operating point separately and refuses to invent one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.stats import binom

SCORER_VERSION = "alarm-molchan-1.0.0"


@dataclass(frozen=True, slots=True)
class ThresholdGroup:
    """Cells sharing one alarm value, and what they are worth."""

    threshold: float
    reference_mass: float
    n_cells: int
    n_events: int


@dataclass(frozen=True, slots=True)
class Trajectory:
    """A Molchan trajectory: cumulative alarm mass, misses and gains, threshold by threshold."""

    thresholds: npt.NDArray[np.float64]
    tau: npt.NDArray[np.float64]
    nu: npt.NDArray[np.float64]
    hits: npt.NDArray[np.int64]
    alarm_cells: npt.NDArray[np.int64]
    n_targets: int

    @property
    def hit_rate(self) -> npt.NDArray[np.float64]:
        return 1.0 - self.nu

    def probability_gain(self) -> npt.NDArray[np.float64]:
        """``(1 - nu) / tau`` at each threshold; ``nan`` where tau is zero."""
        with np.errstate(divide="ignore", invalid="ignore"):
            gain = np.where(self.tau > 0.0, self.hit_rate / self.tau, np.nan)
        return np.asarray(gain, dtype=np.float64)

    def p_values(self) -> npt.NDArray[np.float64]:
        """``P(Binomial(N, tau) >= hits)`` at each threshold."""
        if self.n_targets == 0:
            return np.full(self.tau.shape, np.nan, dtype=np.float64)
        return np.asarray(binom.sf(self.hits - 1, self.n_targets, self.tau), dtype=np.float64)


def group_by_threshold(
    alarm_values: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
    event_counts: npt.NDArray[np.int64],
) -> list[ThresholdGroup]:
    """Collapse cells to distinct alarm values, descending. Ties never split."""
    _check_shapes(alarm_values, reference, event_counts)
    order = np.argsort(-alarm_values, kind="stable")
    values = alarm_values[order]
    ref = reference[order]
    counts = event_counts[order]
    _, starts = np.unique(-values, return_index=True)
    starts = np.sort(starts)
    ends = np.append(starts[1:], values.size)
    return [
        ThresholdGroup(
            threshold=float(values[s]),
            reference_mass=float(ref[s:e].sum()),
            n_cells=int(e - s),
            n_events=int(counts[s:e].sum()),
        )
        for s, e in zip(starts.tolist(), ends.tolist(), strict=True)
    ]


def trajectory(groups: list[ThresholdGroup], n_targets: int) -> Trajectory:
    """Cumulate the groups into a trajectory, most alarming threshold first."""
    thresholds = np.asarray([g.threshold for g in groups], dtype=np.float64)
    tau = np.cumsum([g.reference_mass for g in groups], dtype=np.float64)
    hits = np.cumsum([g.n_events for g in groups], dtype=np.int64)
    cells = np.cumsum([g.n_cells for g in groups], dtype=np.int64)
    tau = np.clip(tau, 0.0, 1.0)
    nu = (
        1.0 - hits.astype(np.float64) / float(n_targets)
        if n_targets > 0
        else np.ones(hits.shape, dtype=np.float64)
    )
    return Trajectory(
        thresholds=thresholds,
        tau=tau,
        nu=np.clip(nu, 0.0, 1.0),
        hits=hits,
        alarm_cells=cells,
        n_targets=n_targets,
    )


def area_skill_score(tau: npt.NDArray[np.float64], hit_rate: npt.NDArray[np.float64]) -> float:
    """Area under the ``(tau, 1 - nu)`` trajectory, with ``(0, 0)`` prepended.

    Ties are credited linearly across the tie group, which is the usual convention and the one
    that makes the reference measure score exactly 0.5 in expectation.
    """
    x = np.concatenate(([0.0], tau))
    y = np.concatenate(([0.0], hit_rate))
    if x[-1] < 1.0:
        x = np.concatenate((x, [1.0]))
        y = np.concatenate((y, [y[-1]]))
    return float(np.trapezoid(y, x))


def _check_shapes(
    alarm_values: npt.NDArray[np.float64],
    reference: npt.NDArray[np.float64],
    event_counts: npt.NDArray[np.int64],
) -> None:
    if alarm_values.shape != reference.shape or alarm_values.shape != event_counts.shape:
        msg = (
            "alarm values, reference and event counts must all be one value per cell: got "
            f"{alarm_values.shape}, {reference.shape}, {event_counts.shape}"
        )
        raise ValueError(msg)
    if alarm_values.ndim != 1:
        msg = "alarm values must be one-dimensional (one per cell)"
        raise ValueError(msg)


def area_skill_null(
    groups: list[ThresholdGroup],
    n_targets: int,
    *,
    n_simulations: int,
    rng: np.random.Generator,
) -> npt.NDArray[np.float64]:
    """Area skill scores of ``n_simulations`` catalogues drawn from the reference measure.

    The alarm function is held fixed and the *events* are resampled, which is the null the
    Molchan diagram is read against: "the reference model is right, and this alarm knows nothing
    the reference does not". Sampling at group resolution rather than cell resolution keeps the
    null and the observed score on identical footing when the alarm has ties.
    """
    mass = np.asarray([g.reference_mass for g in groups], dtype=np.float64)
    mass = mass / mass.sum()
    tau = np.clip(np.cumsum(mass), 0.0, 1.0)
    if n_targets == 0:
        return np.full(n_simulations, np.nan, dtype=np.float64)
    draws = rng.multinomial(n_targets, mass, size=n_simulations)
    hit_rate = np.cumsum(draws, axis=1) / float(n_targets)
    x = np.concatenate(([0.0], tau))
    if x[-1] < 1.0:
        x = np.concatenate((x, [1.0]))
        pad = hit_rate[:, -1:]
        hit_rate = np.concatenate((hit_rate, pad), axis=1)
    y = np.concatenate((np.zeros((n_simulations, 1)), hit_rate), axis=1)
    return np.asarray(np.trapezoid(y, x, axis=1), dtype=np.float64)


def matched_random_hits(
    event_counts: npt.NDArray[np.int64],
    *,
    n_alarm_cells: int,
    n_simulations: int,
    rng: np.random.Generator,
) -> npt.NDArray[np.int64]:
    """Hits from relocating an alarm footprint of the same cell count at random.

    ADR-0055 requires this control alongside the clustering-aware reference. It is the weaker of
    the two: it asks whether the *placement* beats an arbitrary placement of the same size, and it
    controls for nothing else. An alarm that simply sits on the seismically active half of a
    region will pass it comfortably and still fail against a fitted ETAS reference, which is the
    control that matters.
    """
    n_cells = int(event_counts.size)
    if not 0 <= n_alarm_cells <= n_cells:
        msg = f"n_alarm_cells must be within [0, {n_cells}], got {n_alarm_cells}"
        raise ValueError(msg)
    out = np.empty(n_simulations, dtype=np.int64)
    for s in range(n_simulations):
        picked = rng.choice(n_cells, size=n_alarm_cells, replace=False)
        out[s] = int(event_counts[picked].sum())
    return out
