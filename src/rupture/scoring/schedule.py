"""Scoring a whole pseudo-prospective alarm schedule as one experiment.

One 30-day window holds a handful of target events, and a Molchan diagram drawn on a handful of
events cannot reject anything: the minimum detectable gain in
:mod:`rupture.scoring.power` says so numerically. A schedule is the unit of evidence, so this
module pools every window into a single trajectory whose bins are ``(window, cell)`` pairs.

Two properties make the pooling honest. Each window enters weighted by the number of events its
*reference* expects there, so an aftershock month is not averaged away against a quiet one. And
the threshold swept is global: an alarm cannot pick a different operating point in each window
after the fact, which is the space-time version of the same bias that makes the best point of a
swept trajectory not a result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy.stats import binom

from rupture.domain.alarm import AlarmScore, AlarmSet, MolchanPoint, ReferenceKind
from rupture.domain.catalog import Catalog
from rupture.domain.common import utc_now
from rupture.scoring import molchan, power
from rupture.scoring.alarm import (
    DEFAULT_ALTERNATIVE_GAIN,
    DEFAULT_SIMULATIONS,
    SCORER_VERSION,
    cell_index_of_events,
    target_events,
)
from rupture.scoring.errors import MissingReferenceError, UniformReferenceRefusedError
from rupture.scoring.reference import ReferenceMeasure, pool


@dataclass(frozen=True, slots=True)
class WindowInput:
    """One issued alarm, the reference issued for the same window, and nothing else."""

    alarm: AlarmSet
    reference: ReferenceMeasure


def _flatten(
    windows: Sequence[WindowInput], catalog: Catalog
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.int64], list[str], int, int]:
    """Concatenate alarm values and target counts in the pooling order; report what was dropped."""
    values: list[npt.NDArray[np.float64]] = []
    counts: list[npt.NDArray[np.int64]] = []
    notes: list[str] = []
    n_targets = 0
    n_outside = 0
    for w in windows:
        if w.reference.cell_origins != w.alarm.cell_origins:
            msg = (
                f"window {w.alarm.id!r}: the reference is on different cells from the alarm; they "
                "must share a lattice"
            )
            raise MissingReferenceError(msg)
        events = target_events(w.alarm, catalog)
        idx = cell_index_of_events(events, w.alarm.cell_origins, w.alarm.cell_size_deg)
        outside = int((idx < 0).sum())
        n_outside += outside
        inside = idx[idx >= 0]
        n_targets += int(inside.size)
        values.append(w.alarm.values())
        counts.append(np.bincount(inside, minlength=w.alarm.n_cells).astype(np.int64))
    if n_outside:
        notes.append(
            f"{n_outside} target event(s) across the schedule fell outside every cell and were "
            "dropped; they are neither hits nor misses"
        )
    return np.concatenate(values), np.concatenate(counts), notes, n_targets, n_outside


def score_alarm_schedule(  # noqa: PLR0912, PLR0915 - one scorer, reported in one place
    windows: Sequence[WindowInput],
    catalog: Catalog,
    *,
    schedule_id: str,
    declared_threshold: float | None = None,
    alpha: float = 0.05,
    target_power: float = 0.8,
    alternative_gain: float = DEFAULT_ALTERNATIVE_GAIN,
    n_simulations: int = DEFAULT_SIMULATIONS,
    seed: int | None = None,
    as_contrast: bool = False,
) -> AlarmScore:
    """Pool every window into one Molchan trajectory and score it once.

    ``declared_threshold`` defaults to the threshold every alarm in the schedule declared, and is
    refused if they disagree: a schedule that moved its operating point between windows did not
    declare one.
    """
    if not windows:
        msg = "an empty schedule cannot be scored"
        raise ValueError(msg)
    first = windows[0].alarm
    reference, _offsets = pool([w.reference for w in windows], reference_id=f"ref-{schedule_id}")
    if reference.kind is ReferenceKind.SPATIALLY_UNIFORM and not as_contrast:
        msg = (
            f"schedule {schedule_id!r} was offered a spatially uniform reference. Pass "
            "as_contrast=True to measure that effect deliberately, or supply a "
            "clustering-aware reference."
        )
        raise UniformReferenceRefusedError(msg)

    rng = np.random.default_rng(seed)
    values, counts, notes, n_targets, _ = _flatten(windows, catalog)

    if declared_threshold is None:
        declared = {w.alarm.declared_threshold for w in windows}
        if len(declared) == 1:
            declared_threshold = declared.pop()
        else:
            notes.append(
                "the windows declared different operating points, so the schedule declared none; "
                "only the trajectory is scored"
            )

    groups = molchan.group_by_threshold(values, reference.probabilities, counts)
    traj = molchan.trajectory(groups, n_targets)
    gains = traj.probability_gain()
    p_values = traj.p_values()
    points = tuple(
        MolchanPoint(
            threshold=float(traj.thresholds[k]),
            tau=float(traj.tau[k]),
            nu=float(traj.nu[k]),
            n_alarm_cells=int(traj.alarm_cells[k]),
            n_hits=int(traj.hits[k]),
            probability_gain=None if not np.isfinite(gains[k]) else float(gains[k]),
            p_value=None if not np.isfinite(p_values[k]) else float(p_values[k]),
        )
        for k in range(traj.tau.size)
    )

    ass: float | None = None
    ass_p: float | None = None
    ass_sims: int | None = None
    if n_targets > 0:
        ass = molchan.area_skill_score(traj.tau, traj.hit_rate)
        null = molchan.area_skill_null(groups, n_targets, n_simulations=n_simulations, rng=rng)
        ass_p = float((null >= ass).sum() + 1) / float(n_simulations + 1)
        ass_sims = n_simulations
    else:
        notes.append("no target event fell in any window: the schedule is undecidable, not passed")

    declared_tau: float | None = None
    declared_hits: int | None = None
    declared_gain: float | None = None
    declared_p: float | None = None
    matched_p: float | None = None
    matched_sims: int | None = None
    the_power: float | None = None
    mdg: float | None = None
    significant: bool | None = None

    if declared_threshold is not None:
        footprint = values >= declared_threshold
        n_alarm_cells = int(footprint.sum())
        declared_tau = float(reference.probabilities[footprint].sum())
        declared_hits = int(counts[footprint].sum())
        if declared_tau <= 0.0:
            notes.append(
                "the declared footprint carries no reference mass across the schedule: no gain "
                "over the reference is defined"
            )
        elif n_targets > 0:
            declared_gain = (declared_hits / n_targets) / declared_tau
            declared_p = float(binom.sf(declared_hits - 1, n_targets, declared_tau))
            significant = declared_p <= alpha
            the_power = power.power_at_gain(n_targets, declared_tau, alternative_gain, alpha)
            mdg = power.minimum_detectable_gain(
                n_targets, declared_tau, alpha=alpha, target_power=target_power
            )
            matched = molchan.matched_random_hits(
                counts,
                n_alarm_cells=n_alarm_cells,
                n_simulations=min(n_simulations, 2000),
                rng=rng,
            )
            matched_sims = int(matched.size)
            matched_p = float((matched >= declared_hits).sum() + 1) / float(matched_sims + 1)
            if mdg is None:
                notes.append(
                    f"no probability gain is detectable at {n_targets} target event(s) and a "
                    f"pooled alarm fraction of {declared_tau:.4g}: the upper bound this schedule "
                    f"achieved is G < {1.0 / declared_tau:.4g}, unattained"
                )
            elif not significant:
                notes.append(
                    f"null result: observed G = {declared_gain:.3g}, and the smallest gain this "
                    f"schedule could have rejected the reference for at {target_power:.0%} power "
                    f"is G = {mdg:.3g} (ADR-0055 decision 5)"
                )

    notes.append(f"pooled over {len(windows)} window(s), {reference.n_cells} space-time bin(s)")
    notes.extend(reference.notes)
    if as_contrast:
        notes.append(
            f"CONTRAST ONLY: scored against a {reference.kind.value} reference, which is not the "
            "reference of record for this arm"
        )
    notes.append(
        "data vintage is not enforced: ADR-0054's as-of layer is not built, so a revised "
        "magnitude or a late-arriving event is indistinguishable here from a timely one"
    )

    return AlarmScore(
        alarm_set_id=schedule_id,
        model_id=first.model_id,
        region_id=first.region_id,
        reference_id=reference.id,
        reference_kind=reference.kind,
        reference_model_id=reference.model_id,
        target_window_start=min(w.alarm.issue_time for w in windows),
        target_window_end=max(w.alarm.window_end for w in windows),
        target_min_magnitude=first.target_min_magnitude,
        target_catalog_hash=catalog.event_hash(),
        n_target_events=n_targets,
        n_cells=reference.n_cells,
        trajectory=points,
        area_skill_score=ass,
        area_skill_p_value=ass_p,
        area_skill_simulations=ass_sims,
        declared_threshold=declared_threshold,
        declared_tau=declared_tau,
        declared_hits=declared_hits,
        declared_probability_gain=declared_gain,
        declared_p_value=declared_p,
        matched_random_p_value=matched_p,
        matched_random_simulations=matched_sims,
        alpha=alpha,
        target_power=target_power,
        power_against_gain=alternative_gain if the_power is not None else None,
        power=the_power,
        minimum_detectable_gain=mdg,
        significant=significant,
        scored_at=utc_now(),
        scorer_version=SCORER_VERSION,
        notes=tuple(notes),
    )
