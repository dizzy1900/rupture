"""Arm -> scorer. The only way to obtain a score (ADR-0055 decision 2).

There is no generic ``evaluate(anything)``. An arm with no registered scorer raises
:class:`~rupture.scoring.errors.ArmNotImplementedError` rather than being approximated by the
nearest available test, because the nearest available test is how an alarm ends up scored as a
degenerate rate grid and a precursor claim ends up scored against a strawman of itself.

Registering an arm means registering *both* a scorer and the reference the scorer requires. The
two are one entry so that the reference cannot be forgotten.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rupture.domain.hypothesis import ARM_DESCRIPTION, MANDATORY_REFERENCE, HypothesisArm
from rupture.scoring.alarm import score_alarm_set
from rupture.scoring.errors import ArmNotImplementedError


@dataclass(frozen=True, slots=True)
class ScorerEntry:
    """One arm's scorer, the reference it insists on, and where the mathematics lives."""

    arm: HypothesisArm
    scorer: Callable[..., Any]
    mandatory_reference: str
    module: str
    notes: str = ""


_REGISTRY: dict[HypothesisArm, ScorerEntry] = {
    HypothesisArm.ALARM_SET: ScorerEntry(
        arm=HypothesisArm.ALARM_SET,
        scorer=score_alarm_set,
        mandatory_reference=MANDATORY_REFERENCE[HypothesisArm.ALARM_SET],
        module="rupture.scoring.alarm",
        notes="Molchan trajectory, area skill score and probability gain at a declared alarm "
        "fraction, with the power the test had.",
    ),
}

_NOT_IMPLEMENTED_REASON: dict[HypothesisArm, str] = {
    HypothesisArm.RATE_FORECAST: (
        "scored today through rupture.adapters.evaluation.pycsep (ADR-0010), which is not yet "
        "registered here: the pycsep path predates the registry and moving it is a separate "
        "change that would rescore committed results"
    ),
    HypothesisArm.SIMULATED_CATALOGUES: (
        "catalogue-based (non-Poissonian) tests are not built; the pycsep path scores the "
        "Poissonian forms only"
    ),
    HypothesisArm.HAZARD_FUNCTION: "declared by ADR-0055 before implementation, on purpose",
    HypothesisArm.STATE_ESTIMATE: (
        "declared by ADR-0055 before implementation, on purpose; it is also the weakest arm, "
        "because calibration against later-observed outcomes is not a settled protocol here"
    ),
}


def scorer_for(arm: HypothesisArm) -> ScorerEntry:
    """The registered scorer for ``arm``, or a refusal naming what is missing."""
    entry = _REGISTRY.get(arm)
    if entry is None:
        reason = _NOT_IMPLEMENTED_REASON.get(arm, "no scorer is registered")
        msg = (
            f"hypothesis arm {arm.value!r} ({ARM_DESCRIPTION[arm]}) has no registered scorer: "
            f"{reason}. Its mandatory reference would be: {MANDATORY_REFERENCE[arm]}"
        )
        raise ArmNotImplementedError(msg)
    return entry


def score(arm: HypothesisArm, *args: Any, **kwargs: Any) -> Any:
    """Score a hypothesis through its arm's registered scorer."""
    return scorer_for(arm).scorer(*args, **kwargs)


def implemented_arms() -> tuple[HypothesisArm, ...]:
    return tuple(sorted(_REGISTRY, key=lambda a: a.value))


def registry_table() -> list[dict[str, str]]:
    """One row per arm: what it asserts, whether it can be scored, and against what."""
    rows: list[dict[str, str]] = []
    for arm in HypothesisArm:
        entry = _REGISTRY.get(arm)
        rows.append(
            {
                "arm": arm.value,
                "asserts": ARM_DESCRIPTION[arm],
                "scorer": entry.module if entry else "NOT_IMPLEMENTED",
                "reference": MANDATORY_REFERENCE[arm],
                "reason": "" if entry else _NOT_IMPLEMENTED_REASON.get(arm, ""),
            }
        )
    return rows
