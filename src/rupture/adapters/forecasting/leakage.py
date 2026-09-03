"""Leakage assertions shared by the ETAS adapter and the pipelines (protocol § 7).

Every check compares ``origin_time`` against a hard cut and raises :class:`LeakageError`; nothing
here ever filters silently. The filters live on :class:`~rupture.domain.Catalog`; these functions
prove that a filter was applied.
"""

from __future__ import annotations

from datetime import datetime

from rupture.domain import Catalog


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
