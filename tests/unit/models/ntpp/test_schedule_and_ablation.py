"""Schedule aggregation, the promotion rule, and the labelling of the leaky ablations.

No schedule is actually run here (that needs pycsep on a real grid, which is an integration
concern). What is checked is the arithmetic of the aggregates, the mechanical application of
protocol § 10, and the property the ablations live or die by: a leaky forecast must be
unmistakable everywhere it appears.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, Region
from rupture.domain import TestName as CsepTest
from rupture.models.challengers.ntpp import NeuralTPPForecaster
from rupture.models.challengers.ntpp.ablation import (
    FIT_LEAK_MODEL_ID,
    LEAKY_BANNER,
    LEAKY_MODEL_ID,
    TUNING_LEAK_MODEL_ID,
    LeakyFitForecaster,
    LeakyTunedForecaster,
)
from rupture.models.challengers.ntpp.schedule import (
    MIN_PROMOTION_WINDOWS,
    ChallengerWindow,
    comparison_summary,
    pass_rates,
    promotion_verdict,
)
from rupture.models.challengers.ntpp.train import select_config
from rupture.models.promotion import pooled_paired_test
from tests.fixtures.models.loader import FIT_CUTOFF, MC, load_ntpp_fit, load_ntpp_weights

HORIZON = timedelta(days=30)
FEW = 2


def _window(
    index: int,
    *,
    passed: bool,
    targets: int = 3,
    gain: float = 0.1,
    t_passed: bool | None = True,
    advantage: float | None = None,
) -> ChallengerWindow:
    """One scored window.

    ``advantage`` is the challenger's per-event log-rate advantage over the benchmark, recorded as
    the pooling terms the schedule-pooled paired T-test consumes (ADR-0040). A small deterministic
    spread is added across events because a test on identical differences has no variance and is
    undefined — which is itself the behaviour :func:`pooled_paired_test` reports.
    """
    issue = FIT_CUTOFF + timedelta(days=30 * index)
    pooling = None
    if advantage is not None:
        offsets = [0.05 * (j - targets / 2) for j in range(targets)]
        pooling = {
            "log_rates": [advantage + o for o in offsets],
            "benchmark_log_rates": [0.0 for _ in offsets],
            "n_forecast": 1.0,
            "benchmark_n_forecast": 1.0,
        }
    tests = {
        t.value: {"passed": (passed if targets else None) if t != CsepTest.N else passed}
        for t in (CsepTest.N, CsepTest.M, CsepTest.S, CsepTest.L, CsepTest.CL)
    }
    return ChallengerWindow(
        issue_time=issue,
        window_end=issue + HORIZON,
        forecast_id=f"f{index}",
        fit_cutoff=FIT_CUTOFF,
        parameter_snapshot_hash="h",
        total_expected=1.0,
        benchmark_total_expected=1.0,
        n_target_events=targets,
        n_excluded_non_earthquake=0,
        n_only=targets == 0,
        tests=tests,
        comparison={
            CsepTest.T.value: {"passed": t_passed, "statistic": gain, "p_value": 0.01},
            CsepTest.W.value: {"passed": t_passed, "statistic": 1.0, "p_value": 0.02},
        },
        pooling=pooling,
    )


def test_pass_rates_report_their_denominator_and_exclude_undecided_windows() -> None:
    windows = [
        _window(0, passed=True),
        _window(1, passed=False),
        _window(2, passed=True, targets=0),
    ]
    rates = pass_rates(windows)
    assert rates["N"]["scored"] == 3
    assert rates["S"]["scored"] == 2  # the zero-target window records N only
    assert rates["S"]["rate"] == pytest.approx(0.5)
    assert rates["N"]["denominator_rule"] == "all evaluated windows"


def test_benchmark_pass_rates_are_aggregated_from_the_same_windows() -> None:
    """Scoring the benchmark in the same run is what makes the two rate columns comparable.

    Two separate runs could differ in simulation count, seed or refit policy without anyone
    noticing; one run over one set of grids cannot.
    """
    windows = [_window(0, passed=True), _window(1, passed=False)]
    windows[0].benchmark_tests = {"N": {"passed": False}, "S": {"passed": False}}
    windows[1].benchmark_tests = {"N": {"passed": False}, "S": {"passed": None}}
    mine = pass_rates(windows)
    theirs = pass_rates(windows, attribute="benchmark_tests")
    assert mine["N"]["rate"] == pytest.approx(0.5)
    assert theirs["N"]["rate"] == pytest.approx(0.0)
    assert theirs["N"]["scored"] == 2
    assert theirs["S"]["scored"] == 1  # the undecided window is excluded, never counted as a fail


def test_comparison_summary_averages_the_information_gain() -> None:
    windows = [_window(0, passed=True, gain=1.0), _window(1, passed=True, gain=-3.0)]
    summary = comparison_summary(windows)
    assert summary["windows_compared"] == 2
    assert summary["mean_information_gain_per_event"] == pytest.approx(-1.0)
    assert summary["windows_with_positive_gain"] == 1


def test_a_short_schedule_cannot_be_promoted_however_good_it_looks() -> None:
    """Protocol § 10 condition 1 has a window count, and it is not negotiable by good scores."""
    report = _report([_window(i, passed=True, advantage=1.0) for i in range(4)])
    verdict = promotion_verdict(report, _baseline_rates(0.0))
    assert verdict["promotable_in_this_region"] is False
    assert any(str(MIN_PROMOTION_WINDOWS) in reason for reason in verdict["reasons_not_promotable"])


def test_windows_must_be_consecutive_not_merely_numerous() -> None:
    """A run of 12, not a count of 12: a schedule with a hole has not run twelve in a row.

    Fourteen windows with the seventh missing has a longest run of seven. Counting rows would call
    that fourteen and promote on a schedule that never ran twelve windows in a row.
    """
    windows = [_window(i, passed=True, advantage=1.0) for i in range(15) if i != 7]
    verdict = promotion_verdict(_report(windows), _baseline_rates(0.0))
    assert verdict["condition_1_pass_rates"]["consecutive_windows"] == 7
    assert verdict["promotable_in_this_region"] is False
    assert any("consecutive window" in r for r in verdict["reasons_not_promotable"])


def test_a_pass_rate_below_the_baseline_fails_condition_one() -> None:
    report = _report([_window(i, passed=i % 2 == 0, advantage=1.0) for i in range(14)])
    verdict = promotion_verdict(report, _baseline_rates(1.0))
    assert verdict["condition_1_pass_rates"]["met"] is False
    assert verdict["condition_1_pass_rates"]["per_test"]["S"]["at_least_etas"] is False
    assert any("below ETAS" in reason for reason in verdict["reasons_not_promotable"])


def test_a_negative_information_gain_fails_condition_two() -> None:
    report = _report([_window(i, passed=True, advantage=-0.5) for i in range(14)])
    verdict = promotion_verdict(report, _baseline_rates(0.0))
    assert verdict["condition_1_pass_rates"]["met"] is True
    assert verdict["condition_2_paired_t_test"]["met"] is False
    assert verdict["promotable_in_this_region"] is False


def test_the_pooled_test_decides_condition_two_not_a_tally_of_windows() -> None:
    """ADR-0040: "over those windows" is one test over every target event, not a vote per window.

    Here the per-window T-test is recorded as lost in thirteen of fourteen windows while every
    window's events are in fact placed better than the benchmark's. Under the old per-window
    majority reading this failed; under the rule as encoded it passes, and the tally is still
    reported so a reader can see the disagreement.
    """
    windows = [_window(i, passed=True, t_passed=False, advantage=1.0) for i in range(14)]
    windows[0].comparison["T"]["passed"] = True
    verdict = promotion_verdict(_report(windows), _baseline_rates(0.0))
    assert verdict["condition_2_paired_t_test"]["met"] is True
    assert verdict["condition_2_paired_t_test"]["per_window_tally"]["t_test_wins"] == 1
    assert verdict["promotable_in_this_region"] is True


def test_an_interval_that_spans_zero_is_not_a_win() -> None:
    """A positive mean whose interval includes zero has not beaten anything."""
    windows = [_window(i, passed=True, advantage=(2.0 if i == 0 else -0.1)) for i in range(14)]
    verdict = promotion_verdict(_report(windows), _baseline_rates(0.0))
    pooled = verdict["condition_2_paired_t_test"]
    assert pooled["information_gain_per_event"] > 0.0
    assert pooled["ig_lower"] < 0.0
    assert pooled["met"] is False


def test_condition_two_is_undecidable_rather_than_passed_without_pooling_terms() -> None:
    """Evidence that cannot decide the condition fails it, and says which one it could not decide.

    The committed NTPP schedules are exactly this case: they record per-window comparisons but no
    per-event log rates, so the pooled test cannot be recomputed from them.
    """
    verdict = promotion_verdict(
        _report([_window(i, passed=True) for i in range(14)]), _baseline_rates(0.0)
    )
    assert verdict["condition_2_paired_t_test"]["decidable"] is False
    assert verdict["condition_2_paired_t_test"]["met"] is False
    assert verdict["promotable_in_this_region"] is False


def test_a_w_test_disagreement_is_flagged_when_the_t_test_passes() -> None:
    """§ 10 asks for the W-test alongside; it warns, it does not veto."""
    windows = [_window(i, passed=True, advantage=1.0) for i in range(14)]
    report = _report(windows)
    report["pooled_paired_test"]["w_test_beats_benchmark"] = False
    verdict = promotion_verdict(report, _baseline_rates(0.0))
    assert verdict["condition_2_paired_t_test"]["met"] is True
    assert verdict["condition_2_paired_t_test"]["w_test_disagrees"] is True
    assert verdict["promotable_in_this_region"] is True  # a warning, never a veto
    assert any("W-test disagrees" in w for w in verdict["warnings"])


def test_a_missing_baseline_is_reported_rather_than_assumed_favourable() -> None:
    verdict = promotion_verdict(_report([_window(i, passed=True) for i in range(14)]), None)
    assert verdict["condition_1_pass_rates"]["met"] is False
    assert all(
        v["at_least_etas"] is None for v in verdict["condition_1_pass_rates"]["per_test"].values()
    )
    assert any("no comparable pass rate" in r for r in verdict["reasons_not_promotable"])


def test_the_verdict_never_decides_the_two_of_three_region_rule_alone() -> None:
    verdict = promotion_verdict(
        _report([_window(i, passed=True) for i in range(14)]), _baseline_rates(0.0)
    )
    assert "decided across regions, not here" in verdict["note"]


# ---------------------------------------------------------------------- ablations
def test_the_honest_model_refuses_what_the_leaky_one_is_built_to_do(
    region: Region, fixture_catalog: Catalog
) -> None:
    earlier = FIT_CUTOFF - timedelta(days=30)
    history = fixture_catalog.earthquakes().before(earlier).at_least(MC)

    honest = NeuralTPPForecaster()
    honest.load_fit(load_ntpp_fit(), region, load_ntpp_weights())
    with pytest.raises(LeakageError, match="precedes the fit cutoff"):
        honest.forecast(history, earlier, HORIZON, n_simulations=FEW, seed=1)

    leaky = LeakyFitForecaster()
    leaky.load_fit(load_ntpp_fit(), region, load_ntpp_weights())
    grid = leaky.forecast(history, earlier, HORIZON, n_simulations=FEW, seed=1)
    assert grid.model_id == FIT_LEAK_MODEL_ID
    assert grid.id.startswith(FIT_LEAK_MODEL_ID)
    assert LEAKY_BANNER in (grid.notes or "")
    assert grid.fit_cutoff == FIT_CUTOFF  # the record keeps the true cutoff, not the pretended one


def test_the_leaky_model_id_is_impossible_to_mistake() -> None:
    for model_id in (LEAKY_MODEL_ID, TUNING_LEAK_MODEL_ID, FIT_LEAK_MODEL_ID):
        assert "LEAKY" in model_id
        assert "ABLATION" in model_id
    assert "NOT A RESULT" in LEAKY_BANNER


def test_each_ablation_has_its_own_id_so_it_cannot_reuse_honest_results(
    region: Region, fixture_catalog: Catalog
) -> None:
    """Evaluation bundles are keyed by forecast id, and forecast ids are keyed by model id.

    A leaky variant sharing the honest id would find the honest results file already on disk and
    silently report it as its own — the ablation measuring nothing while appearing to work.
    """
    ids = {NeuralTPPForecaster.model_id, TUNING_LEAK_MODEL_ID, FIT_LEAK_MODEL_ID}
    assert len(ids) == 3

    history = fixture_catalog.earthquakes().before(FIT_CUTOFF).at_least(MC)
    tuned = LeakyTunedForecaster()
    tuned.load_fit(load_ntpp_fit(), region, load_ntpp_weights())
    grid = tuned.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=FEW, seed=1)
    assert grid.id.startswith(TUNING_LEAK_MODEL_ID)
    assert LEAKY_BANNER in (grid.notes or "")


def test_selection_refuses_a_validation_window_past_the_cutoff(
    fixture_catalog: Catalog, region: Region
) -> None:
    """The one refusal that makes the honest run honest."""
    with pytest.raises(LeakageError, match="hyperparameters would be chosen"):
        select_config(
            fixture_catalog,
            region,
            mc=MC,
            train_start=datetime(2018, 1, 1, tzinfo=UTC),
            validation_end=FIT_CUTOFF + timedelta(days=1),
            hard_cutoff=FIT_CUTOFF,
        )


def _report(windows: list[ChallengerWindow]) -> dict[str, Any]:
    rows = [w.as_dict() for w in windows]
    return {
        "region_id": "california-fixture",
        "model_id": "ntpp-neural-hawkes",
        "n_scored": len(windows),
        "schedule": {"step": "30d"},
        "pass_rates": pass_rates(windows),
        "comparison_summary": comparison_summary(windows),
        "pooled_paired_test": pooled_paired_test(rows),
        "windows": rows,
    }


def _baseline_rates(rate: float) -> dict[str, Any]:
    return {t: {"rate": rate, "scored": 20} for t in ("N", "M", "S", "L", "CL")}
