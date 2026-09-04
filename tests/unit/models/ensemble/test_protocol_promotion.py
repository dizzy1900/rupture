"""``protocol_runner.promotion_decision``: the plumbing between a run's report and the rule.

The rule itself is specified in ``tests/unit/models/test_promotion.py``. What is checked here is
the part this module still owns — that the *consecutive* window run is counted from the schedule's
own issue times rather than assumed from its length, that a region with no published ETAS schedule
is refused rather than passed, and that the C1b/ensemble path now reaches the same encoding the
neural challenger's does. Before ADR-0040 this function had its own reading of condition 2 and no
test at all.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from rupture.models.ensemble.protocol_runner import HORIZON, promotion_decision
from rupture.models.promotion import pooled_paired_test

START = datetime(2022, 1, 1, tzinfo=UTC)


def _rates(value: float) -> dict[str, Any]:
    return {t: {"rate": value, "scored": 20} for t in ("N", "M", "S", "L", "CL")}


def _windows(count: int, *, advantage: float, skip: set[int] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(count):
        if i in (skip or set()):
            continue
        offsets = [0.01 * (j - 2) for j in range(5)]
        rows.append(
            {
                "issue_time": (START + i * HORIZON).isoformat(),
                "pooling": {
                    "log_rates": [advantage + o for o in offsets],
                    "benchmark_log_rates": [0.0 for _ in offsets],
                    "n_forecast": 1.0,
                    "benchmark_n_forecast": 1.0,
                },
            }
        )
    return rows


def _decide(windows: list[dict[str, Any]], *, rate: float = 0.9) -> dict[str, Any]:
    return promotion_decision(
        _rates(rate),
        {"available": True, "pass_rates": _rates(0.5)},
        pooled_paired_test(windows),
        windows,
        model_id="ensemble-loglinear",
        region_id="turkiye-eaf",
    )


def test_both_conditions_met_is_promotable_in_the_region_and_no_further() -> None:
    verdict = _decide(_windows(20, advantage=1.0))
    assert verdict["promotable_in_this_region"] is True
    assert "at least 2 of the 3 protocol regions" in verdict["note"]


def test_the_consecutive_run_is_counted_from_the_issue_times() -> None:
    """A schedule with a hole has not run twelve windows in a row, however many rows it has."""
    verdict = _decide(_windows(20, advantage=1.0, skip={10}))
    assert verdict["condition_1_pass_rates"]["consecutive_windows"] == 10
    assert verdict["promotable_in_this_region"] is False
    assert any("consecutive window" in r for r in verdict["reasons_not_promotable"])


def test_a_pass_rate_below_the_baseline_fails_condition_one() -> None:
    verdict = _decide(_windows(20, advantage=1.0), rate=0.4)
    assert verdict["condition_1_pass_rates"]["met"] is False
    assert verdict["promotable_in_this_region"] is False


def test_a_negative_pooled_gain_fails_condition_two() -> None:
    verdict = _decide(_windows(20, advantage=-1.0))
    condition_2 = verdict["condition_2_paired_t_test"]
    assert condition_2["decidable"] is True
    assert condition_2["information_gain_per_event"] < 0.0
    assert condition_2["met"] is False
    assert verdict["promotable_in_this_region"] is False


def test_no_published_baseline_is_refused_rather_than_passed() -> None:
    verdict = promotion_decision(
        _rates(1.0),
        {"available": False},
        {},
        _windows(20, advantage=1.0),
        model_id="ensemble-loglinear",
        region_id="california",
    )
    assert verdict["promotable_in_this_region"] is False
    assert "no published ETAS schedule" in verdict["reason"]


def test_the_step_is_the_protocol_horizon_by_default() -> None:
    assert timedelta(days=30) == HORIZON
