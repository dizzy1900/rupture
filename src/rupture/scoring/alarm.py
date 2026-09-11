"""Scoring the ``AlarmSet`` arm: the domain-facing half of the alarm scorer.

:mod:`rupture.scoring.molchan` holds the mathematics on plain arrays. This module is what makes
the mathematics safe to publish: it binds an alarm to a target catalogue slice, insists on a
reference that is not uniform, drops what it cannot score and *says so*, and attaches the power
the test had to the number it produces.

The rules it enforces, all from ADR-0055:

* **No score without a reference** (decision 3). ``score_alarm_set`` takes the reference as a
  required positional argument, and a uniform one raises unless the caller marks it a contrast.
* **A matched random control** (decision 1, alarm row) is computed whenever an operating point
  was declared.
* **Power travels with the p-value** (decision 4), and a null carries its minimum detectable
  gain (decision 5).
* **The declared operating point is not the best one.** A gain read off the best point of a swept
  trajectory is a maximum over thresholds and is biased upward; it is reported as
  ``best_trajectory_gain`` in the notes and never as the result.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

import numpy as np
import numpy.typing as npt
from scipy.stats import binom

from rupture.domain.alarm import AlarmScore, AlarmSet, MolchanPoint, ReferenceKind
from rupture.domain.catalog import Catalog
from rupture.domain.common import utc_now
from rupture.domain.event import Event
from rupture.scoring import molchan, power
from rupture.scoring.errors import (
    LeakyReferenceError,
    MissingReferenceError,
    UniformReferenceRefusedError,
)
from rupture.scoring.reference import ReferenceMeasure

SCORER_VERSION = molchan.SCORER_VERSION
DEFAULT_SIMULATIONS = 10_000
DEFAULT_ALTERNATIVE_GAIN = 2.0
"""The gain rupture powers against by default: Nakatani (2020) puts most non-triggering
precursor phenomena near G = 2, so an experiment that cannot see 2 cannot see the field."""


def cell_index_of_events(
    events: Sequence[Event],
    cell_origins: tuple[tuple[float, float], ...],
    cell_size_deg: float,
) -> npt.NDArray[np.int64]:
    """Cell index per event, ``-1`` for an event outside every cell.

    The lattice is reconstructed from the cell origins rather than from a region polygon, so an
    alarm and its reference are indexed identically by construction: they share the origins.
    """
    if not cell_origins:
        msg = "an alarm with no cells cannot be scored"
        raise ValueError(msg)
    lookup = {
        (round(lon / cell_size_deg), round(lat / cell_size_deg)): i
        for i, (lon, lat) in enumerate(cell_origins)
    }
    out = np.full(len(events), -1, dtype=np.int64)
    for k, event in enumerate(events):
        ix = int(np.floor(event.longitude / cell_size_deg + 1e-9))
        iy = int(np.floor(event.latitude / cell_size_deg + 1e-9))
        out[k] = lookup.get((ix, iy), -1)
    return out


def target_events(alarm: AlarmSet, catalog: Catalog) -> tuple[Event, ...]:
    """Earthquakes in the alarm's window at or above its target magnitude, in time order."""
    slice_ = (
        catalog.earthquakes()
        .between(alarm.issue_time, alarm.window_end)
        .at_least(alarm.target_min_magnitude)
    )
    return tuple(sorted(slice_.events, key=lambda e: e.origin_time))


def _check_reference(
    alarm: AlarmSet, reference: ReferenceMeasure, *, as_contrast: bool
) -> list[str]:
    notes: list[str] = []
    if reference.cell_origins != alarm.cell_origins:
        msg = (
            f"reference {reference.id!r} is defined on different cells from alarm {alarm.id!r} "
            f"({reference.n_cells} vs {alarm.n_cells}); they must share a lattice"
        )
        raise MissingReferenceError(msg)
    if reference.kind is ReferenceKind.SPATIALLY_UNIFORM and not as_contrast:
        msg = (
            f"reference {reference.id!r} is spatially uniform. An alarm scored against area is "
            "credited for knowing that earthquakes happen on faults (Zhang et al. 2024; Luen & "
            "Stark 2008). Pass as_contrast=True to measure the size of that effect deliberately, "
            "or supply a clustering-aware reference."
        )
        raise UniformReferenceRefusedError(msg)
    if reference.kind is ReferenceKind.SPATIALLY_VARYING_POISSON:
        notes.append(
            "reference varies in space but carries no time clustering: an alarm that beats it "
            "may be reproducing Omori decay rather than predicting anything"
        )
    if as_contrast:
        notes.append(
            f"CONTRAST ONLY: scored against a {reference.kind.value} reference, which is not the "
            "reference of record for this arm"
        )
    if reference.fit_cutoff_iso is not None:
        cutoff = datetime.fromisoformat(reference.fit_cutoff_iso)
        if cutoff > alarm.issue_time:
            msg = (
                f"reference {reference.id!r} was fitted to data up to {cutoff.isoformat()}, after "
                f"the alarm was issued at {alarm.issue_time.isoformat()}: the reference saw the "
                "window it is judging"
            )
            raise LeakyReferenceError(msg)
    notes.append(
        "data vintage is not enforced: ADR-0054's as-of layer is not built, so a revised "
        "magnitude or a late-arriving event is indistinguishable here from a timely one"
    )
    return notes


def score_alarm_set(  # noqa: PLR0915 - one scorer, reported in one place
    alarm: AlarmSet,
    catalog: Catalog,
    reference: ReferenceMeasure,
    *,
    alpha: float = 0.05,
    target_power: float = 0.8,
    alternative_gain: float = DEFAULT_ALTERNATIVE_GAIN,
    n_simulations: int = DEFAULT_SIMULATIONS,
    seed: int | None = None,
    as_contrast: bool = False,
) -> AlarmScore:
    """Score one alarm set against one reference on one target slice.

    ``as_contrast`` is the only way to score against a uniform reference, and every score produced
    that way is labelled in its notes so it can never be read as the result.
    """
    notes = _check_reference(alarm, reference, as_contrast=as_contrast)
    rng = np.random.default_rng(seed)

    events = target_events(alarm, catalog)
    indices = cell_index_of_events(events, alarm.cell_origins, alarm.cell_size_deg)
    outside = int((indices < 0).sum())
    if outside:
        notes.append(
            f"{outside} of {len(events)} target event(s) fell outside every cell of the alarm "
            "lattice and were dropped; they are neither hits nor misses"
        )
    inside = indices[indices >= 0]
    n_targets = int(inside.size)
    counts = np.bincount(inside, minlength=alarm.n_cells).astype(np.int64)

    values = alarm.values()
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
        notes.append(
            "no target event fell in the window: the alarm is undecidable, not passed. "
            "Every quantity below that needs a target is null"
        )

    declared_tau: float | None = None
    declared_hits: int | None = None
    declared_gain: float | None = None
    declared_p: float | None = None
    matched_p: float | None = None
    matched_sims: int | None = None
    the_power: float | None = None
    mdg: float | None = None
    significant: bool | None = None

    if alarm.declared_threshold is not None:
        footprint = alarm.declared_footprint()
        n_alarm_cells = int(footprint.sum())
        declared_tau = float(reference.probabilities[footprint].sum())
        declared_hits = int(counts[footprint].sum())
        if declared_tau <= 0.0:
            notes.append(
                "the declared footprint carries no reference mass: the reference model expects no "
                "event there at all, so no gain over it is defined"
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
                    f"no probability gain is detectable at {n_targets} target event(s) and an "
                    f"alarm fraction of {declared_tau:.4g}: even a perfect alarm inside this "
                    f"footprint would not reject the reference at alpha = {alpha}. The upper "
                    f"bound this experiment achieved is G < {1.0 / declared_tau:.4g}, unattained"
                )
            elif declared_gain is not None and not significant:
                notes.append(
                    f"null result: observed G = {declared_gain:.3g}, and the smallest gain this "
                    f"test could have rejected the reference for at {target_power:.0%} power is "
                    f"G = {mdg:.3g} (ADR-0055 decision 5)"
                )
    else:
        notes.append(
            "no operating point was declared before the targets were seen, so no single "
            "probability gain is quoted: the claim is the whole trajectory"
        )
        finite = np.isfinite(gains) & (traj.tau > 0.0)
        if n_targets > 0 and finite.any():
            best = int(np.nanargmax(np.where(finite, gains, -np.inf)))
            notes.append(
                f"for orientation only, the best point of the swept trajectory is G = "
                f"{gains[best]:.3g} at tau = {traj.tau[best]:.4g}; a maximum over thresholds is "
                "biased upward and is not a result"
            )

    notes.extend(reference.notes)
    return AlarmScore(
        alarm_set_id=alarm.id,
        model_id=alarm.model_id,
        region_id=alarm.region_id,
        reference_id=reference.id,
        reference_kind=reference.kind,
        reference_model_id=reference.model_id,
        target_window_start=alarm.issue_time,
        target_window_end=alarm.window_end,
        target_min_magnitude=alarm.target_min_magnitude,
        target_catalog_hash=catalog.event_hash(),
        n_target_events=n_targets,
        n_cells=alarm.n_cells,
        trajectory=points,
        area_skill_score=ass,
        area_skill_p_value=ass_p,
        area_skill_simulations=ass_sims,
        declared_threshold=alarm.declared_threshold,
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
