"""The promotion rule itself: protocol § 10 as encoded in :mod:`rupture.models.promotion`.

These tests are the specification of ADR-0040. They use no real data and no model — the rule takes
pass rates and test results, and that is the whole point: the same code judges every challenger,
and a reader can see what would and would not be promoted without running anything.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rupture.models.promotion import (
    MIN_CONSECUTIVE_WINDOWS,
    MIN_REGIONS,
    condition_1,
    condition_2,
    longest_consecutive_run,
    overall_verdict,
    pass_rate_table,
    pooled_paired_test,
    region_verdict,
)

STEP = timedelta(days=30)
START = datetime(2022, 1, 1, tzinfo=UTC)


def _times(count: int, *, skip: set[int] | None = None) -> list[str]:
    return [(START + i * STEP).isoformat() for i in range(count) if i not in (skip or set())]


def _rates(value: float) -> dict[str, float]:
    return dict.fromkeys(("N", "M", "S", "L"), value)


def _pooled(advantage: float, *, events: int = 40) -> dict[str, object]:
    """A pooled test built from real per-event log rates, not a hand-written verdict."""
    offsets = [0.2 * (i - events / 2) / events for i in range(events)]
    window = {
        "issue_time": START.isoformat(),
        "pooling": {
            "log_rates": [advantage + o for o in offsets],
            "benchmark_log_rates": [0.0 for _ in offsets],
            "n_forecast": 1.0,
            "benchmark_n_forecast": 1.0,
        },
    }
    return pooled_paired_test([window])


# ---------------------------------------------------------------- consecutive windows
def test_consecutive_means_a_run_not_a_count() -> None:
    assert longest_consecutive_run(_times(14), STEP) == 14
    assert longest_consecutive_run(_times(14, skip={7}), STEP) == 7
    assert longest_consecutive_run([], STEP) == 0


def test_an_unreadable_issue_time_breaks_the_run_rather_than_being_dropped() -> None:
    """A schedule whose times cannot be read is not evidence that they were consecutive."""
    assert longest_consecutive_run([*_times(13), "not a timestamp"], STEP) == 0


def test_the_run_is_computed_on_instants_not_strings() -> None:
    """The same instant is written ...Z and ...+00:00, and '+' sorts below 'Z'."""
    times = [START.isoformat().replace("+00:00", "Z"), (START + STEP).isoformat()]
    assert longest_consecutive_run(times, STEP) == 2


def test_a_step_must_be_positive() -> None:
    with pytest.raises(ValueError, match="step must be positive"):
        longest_consecutive_run(_times(3), timedelta(0))


# ---------------------------------------------------------------- condition 1
def test_condition_one_needs_every_test_at_or_above_etas() -> None:
    equal = condition_1(
        challenger=_rates(0.8), baseline=_rates(0.8), consecutive_windows=MIN_CONSECUTIVE_WINDOWS
    )
    assert equal["met"] is True  # "at or above", so equality passes

    one_below = _rates(0.8) | {"S": 0.79}
    verdict = condition_1(
        challenger=one_below, baseline=_rates(0.8), consecutive_windows=MIN_CONSECUTIVE_WINDOWS
    )
    assert verdict["met"] is False
    assert any("S-test" in reason for reason in verdict["reasons"])


def test_condition_one_fails_on_too_few_consecutive_windows_however_good_the_rates() -> None:
    verdict = condition_1(
        challenger=_rates(1.0),
        baseline=_rates(0.0),
        consecutive_windows=MIN_CONSECUTIVE_WINDOWS - 1,
    )
    assert verdict["met"] is False
    assert any("consecutive window" in reason for reason in verdict["reasons"])


def test_a_missing_rate_fails_rather_than_being_assumed_favourable() -> None:
    verdict = condition_1(
        challenger=_rates(1.0),
        baseline={"N": 0.5},
        consecutive_windows=MIN_CONSECUTIVE_WINDOWS,
    )
    assert verdict["met"] is False
    assert verdict["per_test"]["S"]["at_least_etas"] is None


# ---------------------------------------------------------------- condition 2
def test_condition_two_is_the_pooled_test_and_needs_the_interval_above_zero() -> None:
    assert condition_2(_pooled(1.0))["met"] is True
    assert condition_2(_pooled(-1.0))["met"] is False
    # A gain of zero has beaten nothing, whichever side of zero the noise falls.
    assert condition_2(_pooled(0.0))["met"] is False


def test_condition_two_records_the_per_window_tally_without_letting_it_decide() -> None:
    """ADR-0040: the tally is evidence about the shape of the result, never the verdict."""
    verdict = condition_2(
        _pooled(1.0), per_window={"t_test_wins": 1, "windows_compared": 10, "w_test_wins": 0}
    )
    assert verdict["met"] is True
    assert verdict["per_window_tally"]["t_test_wins"] == 1


def test_condition_two_is_not_met_when_it_cannot_be_decided() -> None:
    absent = condition_2(None)
    assert (absent["met"], absent["decidable"]) == (False, False)
    undefined = condition_2({"decided": False, "reason": "a target event fell in a zero-rate bin"})
    assert (undefined["met"], undefined["decidable"]) == (False, False)
    assert any("zero-rate bin" in reason for reason in undefined["reasons"])


def test_a_w_test_disagreement_warns_and_does_not_veto() -> None:
    pooled = {**_pooled(1.0), "w_test_beats_benchmark": False}
    verdict = condition_2(pooled)
    assert verdict["met"] is True
    assert verdict["w_test_disagrees"] is True
    assert verdict["warnings"]


# ---------------------------------------------------------------- conditions 3 and the whole rule
def _region(region_id: str, *, promotable: bool) -> dict[str, object]:
    return region_verdict(
        region_id=region_id,
        model_id="test-challenger",
        challenger_rates=_rates(0.9 if promotable else 0.1),
        baseline_rates=_rates(0.5),
        consecutive_windows=MIN_CONSECUTIVE_WINDOWS,
        pooled=_pooled(1.0 if promotable else -1.0),
    )


def test_one_region_is_not_two() -> None:
    verdict = overall_verdict(
        [_region("turkiye-eaf", promotable=True), _region("nepal-himalaya", promotable=False)],
        model_id="test-challenger",
    )
    assert verdict["promoted"] is False
    assert verdict["regions_passing"] == ["turkiye-eaf"]
    assert verdict["regions_not_evaluated"] == ["california"]
    # One pass plus one region that could still pass reaches two: the verdict is not yet safe.
    assert verdict["verdict_robust_to_unevaluated_regions"] is False


def test_a_region_that_cannot_pass_makes_the_verdict_robust() -> None:
    """Naming *why* a region could not have changed the answer is stronger than "not promoted"."""
    verdict = overall_verdict(
        [_region("turkiye-eaf", promotable=True), _region("nepal-himalaya", promotable=False)],
        model_id="test-challenger",
        regions_that_cannot_pass={"california": "the baseline schedule is 6 windows"},
    )
    assert verdict["promoted"] is False
    assert verdict["regions_that_could_still_pass"] == []
    assert verdict["verdict_robust_to_unevaluated_regions"] is True
    assert "california" in verdict["regions_that_cannot_pass"]


def test_two_regions_promote() -> None:
    verdict = overall_verdict(
        [_region("turkiye-eaf", promotable=True), _region("nepal-himalaya", promotable=True)],
        model_id="test-challenger",
    )
    assert verdict["promoted"] is True
    assert len(verdict["regions_passing"]) == MIN_REGIONS


def test_pass_rate_table_ignores_anything_it_cannot_read() -> None:
    table = pass_rate_table(
        {"pass_rates": {"N": {"rate": 0.5}, "M": {"rate": None}, "S": "not a table"}}
    )
    assert table == {"N": 0.5}
