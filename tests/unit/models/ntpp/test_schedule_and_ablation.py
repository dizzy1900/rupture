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
from tests.fixtures.models.loader import FIT_CUTOFF, MC, load_ntpp_fit, load_ntpp_weights

HORIZON = timedelta(days=30)
FEW = 2


def _window(
    index: int, *, passed: bool, targets: int = 3, gain: float = 0.1, t_passed: bool | None = True
) -> ChallengerWindow:
    issue = FIT_CUTOFF + timedelta(days=30 * index)
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


def test_comparison_summary_averages_the_information_gain() -> None:
    windows = [_window(0, passed=True, gain=1.0), _window(1, passed=True, gain=-3.0)]
    summary = comparison_summary(windows)
    assert summary["windows_compared"] == 2
    assert summary["mean_information_gain_per_event"] == pytest.approx(-1.0)
    assert summary["windows_with_positive_gain"] == 1


def test_a_short_schedule_cannot_be_promoted_however_good_it_looks() -> None:
    """Protocol § 10 condition 1 has a window count, and it is not negotiable by good scores."""
    report = _report([_window(i, passed=True) for i in range(4)])
    verdict = promotion_verdict(report, _baseline_rates(0.0))
    assert verdict["promotable_in_this_region"] is False
    assert any(str(MIN_PROMOTION_WINDOWS) in reason for reason in verdict["reasons_not_promotable"])


def test_a_pass_rate_below_the_baseline_fails_condition_one() -> None:
    report = _report([_window(i, passed=i % 2 == 0) for i in range(14)])
    verdict = promotion_verdict(report, _baseline_rates(1.0))
    assert verdict["condition_1_pass_rates"] is False
    assert verdict["per_test"]["S"]["at_or_above"] is False
    assert any("below the baseline" in reason for reason in verdict["reasons_not_promotable"])


def test_a_negative_information_gain_fails_condition_two() -> None:
    report = _report([_window(i, passed=True, gain=-0.5, t_passed=False) for i in range(14)])
    verdict = promotion_verdict(report, _baseline_rates(0.0))
    assert verdict["condition_1_pass_rates"] is True
    assert verdict["condition_2_paired_t"] is False
    assert verdict["promotable_in_this_region"] is False


def test_a_missing_baseline_is_reported_rather_than_assumed_favourable() -> None:
    verdict = promotion_verdict(_report([_window(i, passed=True) for i in range(14)]), None)
    assert verdict["condition_1_pass_rates"] is False
    assert all(v["at_or_above"] is None for v in verdict["per_test"].values())
    assert any("no comparable baseline" in r for r in verdict["reasons_not_promotable"])


def test_the_verdict_never_decides_the_two_of_three_region_rule_alone() -> None:
    verdict = promotion_verdict(
        _report([_window(i, passed=True) for i in range(14)]), _baseline_rates(0.0)
    )
    assert verdict["regions_required"] == 2
    assert "cannot be decided from one region" in verdict["note"]


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
    return {
        "region_id": "california-fixture",
        "n_scored": len(windows),
        "pass_rates": pass_rates(windows),
        "comparison_summary": comparison_summary(windows),
        "windows": [w.as_dict() for w in windows],
    }


def _baseline_rates(rate: float) -> dict[str, Any]:
    return {t: {"rate": rate, "scored": 20} for t in ("N", "M", "S", "L", "CL")}
