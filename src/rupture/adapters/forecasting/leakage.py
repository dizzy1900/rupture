"""Leakage assertions shared by the ETAS adapter and the pipelines (protocol § 7).

Every check compares a time against a hard cut and raises :class:`LeakageError`; nothing here
ever filters silently. The filters live on :class:`~rupture.domain.Catalog`; these functions
prove that a filter was applied.

**Two clocks, two assertions.** Until ADR-0064 every function in this module compared
``origin_time`` and nothing else, so the whole module could only see one of the two ways a fit
reaches into its own future. An event that happened in 2018 and whose magnitude was revised in
2026 passes :func:`assert_all_before` at a 2019 cutoff, and on the committed California fixture
that describes 69 of the 217 events such a fit would train on.
:func:`assert_available_before` is the second clock. It is not wired into the existing pipelines,
because doing that silently would change every number in the ledger; it is what the ``asof`` gate
uses to measure the exposure first.
"""

from __future__ import annotations

from datetime import datetime

from rupture.domain import Catalog, VintagePolicy


class LeakageError(RuntimeError):
    """Raised when data at or after a cut could reach a fit, a forecast or a target slice."""


def assert_all_before(catalog: Catalog, cutoff: datetime, *, what: str) -> None:
    """Rule 1/3: every event in ``catalog`` has ``origin_time < cutoff``."""
    latest = catalog.max_origin_time()
    if latest is not None and latest >= cutoff:
        offenders = [e.id for e in catalog.events if e.origin_time >= cutoff][:5]
        msg = (
            f"leakage: {what} contains {len(offenders)}+ event(s) with origin_time >= "
            f"{cutoff.isoformat()} (latest {latest.isoformat()}; e.g. {offenders})"
        )
        raise LeakageError(msg)


def assert_within_window(catalog: Catalog, start: datetime, end: datetime, *, what: str) -> None:
    """Rule 2: every event in ``catalog`` satisfies ``start <= origin_time < end``."""
    earliest = catalog.min_origin_time()
    latest = catalog.max_origin_time()
    if earliest is not None and earliest < start:
        msg = f"leakage: {what} has an event before the window start {start.isoformat()}"
        raise LeakageError(msg)
    if latest is not None and latest >= end:
        msg = f"leakage: {what} has an event at/after the window end {end.isoformat()}"
        raise LeakageError(msg)


def assert_issue_after_fit(issue_time: datetime, fit_cutoff: datetime) -> None:
    """Parameters fitted with data up to ``fit_cutoff`` may only be used from that time on."""
    if issue_time < fit_cutoff:
        msg = (
            f"leakage: issue_time {issue_time.isoformat()} precedes the fit cutoff "
            f"{fit_cutoff.isoformat()}; the parameters were fitted on data after the issue time"
        )
        raise LeakageError(msg)


def assert_available_before(
    catalog: Catalog, cutoff: datetime, *, what: str, policy: VintagePolicy
) -> None:
    """Rule 4 (ADR-0064): every record was *available* before ``cutoff``, not merely old enough.

    Under ``EXCLUDE_UNKNOWN`` an event with no vintage is a violation, because "we do not know
    when this value came to exist" is not evidence that it existed in time. Under
    ``INCLUDE_UNKNOWN`` it is permitted and the count is reported in the error message when
    something else fails, so a caller can see how much of the pass rested on the assumption.
    """
    late = [
        e for e in catalog.events if e.available_time is not None and e.available_time >= cutoff
    ]
    unknown = [e for e in catalog.events if e.available_time is None]
    offenders = list(late)
    if policy is VintagePolicy.EXCLUDE_UNKNOWN:
        offenders += unknown
    if not offenders:
        return
    ids = [e.id for e in offenders[:5]]
    detail = f"{len(late)} record(s) last modified at or after the cut"
    if unknown:
        detail += f", {len(unknown)} of unknown vintage"
    msg = (
        f"leakage (vintage): {what} contains {len(offenders)} event(s) not provably available "
        f"before {cutoff.isoformat()} under policy {policy.value} -- {detail}; e.g. {ids}"
    )
    raise LeakageError(msg)
