"""Intervals that survive clustering: the moving-block bootstrap over scored windows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from rupture.scoring.blocks import (
    BlockBootstrapResult,
    block_length_sensitivity,
    conclusion_holds_across_lengths,
    effective_blocks,
    moving_block_bootstrap,
    pooled_information_gain,
)
from rupture.scoring.evidence import read_all_with_blocks

CHALLENGERS = Path("reports/challenger")


def _window(
    issue: str, diffs: list[float], n_forecast: float = 0.0, bench_forecast: float = 0.0
) -> dict[str, Any]:
    """A window whose per-event log-rate differences are exactly ``diffs``."""
    return {
        "issue_time": issue,
        "n_target_events": len(diffs),
        "pooling": {
            "log_rates": [float(d) for d in diffs],
            "benchmark_log_rates": [0.0] * len(diffs),
            "n_forecast": n_forecast,
            "benchmark_n_forecast": bench_forecast,
        },
    }


# ---------------------------------------------------------------- the statistic


def test_the_pooled_gain_is_the_published_formula() -> None:
    """(sum of log-rate differences - forecast-count difference) / events."""
    windows = [_window("a", [1.0, 2.0], n_forecast=1.0, bench_forecast=0.5)]
    assert pooled_information_gain(windows) == pytest.approx((3.0 - 0.5) / 2)


def test_a_schedule_with_no_target_has_no_statistic() -> None:
    assert pooled_information_gain([_window("a", [])]) is None


def test_mismatched_pairing_is_refused() -> None:
    bad = _window("a", [1.0, 2.0])
    bad["pooling"]["benchmark_log_rates"] = [0.0]
    with pytest.raises(ValueError, match="paired per event"):
        pooled_information_gain([bad])


# ---------------------------------------------------------------- effective blocks


def test_evenly_spread_events_are_worth_every_window() -> None:
    windows = [_window(str(i), [1.0, 1.0]) for i in range(10)]
    assert effective_blocks(windows) == pytest.approx(10.0)


def test_one_dominant_window_collapses_the_effective_count() -> None:
    """The Türkiye case: most of the evidence is one aftershock sequence."""
    windows = [_window("big", [1.0] * 160), *[_window(str(i), [1.0]) for i in range(57)]]
    assert effective_blocks(windows) < 2.0


def test_no_events_is_zero_blocks() -> None:
    assert effective_blocks([_window("a", [])]) == 0.0


# ---------------------------------------------------------------- the bootstrap


def test_the_interval_brackets_the_observed_statistic() -> None:
    rng = np.random.default_rng(0)
    windows = [_window(str(i), list(rng.normal(0.5, 1.0, size=4))) for i in range(40)]
    result = moving_block_bootstrap(windows, n_resamples=2000, rng=np.random.default_rng(1))
    assert result.lower <= result.observed <= result.upper


def test_a_clustered_schedule_gives_a_wider_interval_than_a_spread_one() -> None:
    """The whole point: concentrating the same events into fewer windows costs information."""
    rng = np.random.default_rng(3)
    values = list(rng.normal(0.4, 1.0, size=120))
    spread = [_window(str(i), values[i * 3 : (i + 1) * 3]) for i in range(40)]
    clustered = [
        _window("big", values[:100]),
        *[_window(str(i), [values[100 + i]]) for i in range(20)],
    ]
    wide = moving_block_bootstrap(clustered, n_resamples=3000, rng=np.random.default_rng(4))
    tight = moving_block_bootstrap(spread, n_resamples=3000, rng=np.random.default_rng(4))
    assert wide.width > tight.width
    assert wide.effective_blocks < tight.effective_blocks


def test_the_bootstrap_is_reproducible_from_its_generator() -> None:
    windows = [_window(str(i), [0.3, -0.1]) for i in range(30)]
    a = moving_block_bootstrap(windows, n_resamples=500, rng=np.random.default_rng(9))
    b = moving_block_bootstrap(windows, n_resamples=500, rng=np.random.default_rng(9))
    assert (a.lower, a.upper) == (b.lower, b.upper)


def test_a_longer_block_is_clamped_to_the_schedule() -> None:
    windows = [_window(str(i), [1.0]) for i in range(5)]
    result = moving_block_bootstrap(
        windows, block_length=99, n_resamples=200, rng=np.random.default_rng(0)
    )
    assert result.block_length == 5


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"block_length": 0}, "at least 1"),
        ({"level": 1.5}, "level"),
    ],
)
def test_impossible_inputs_are_refused(kwargs: dict[str, Any], match: str) -> None:
    windows = [_window(str(i), [1.0]) for i in range(5)]
    with pytest.raises(ValueError, match=match):
        moving_block_bootstrap(windows, n_resamples=10, **kwargs)


def test_an_empty_schedule_is_refused() -> None:
    with pytest.raises(ValueError, match="no windows"):
        moving_block_bootstrap([], n_resamples=10)


def test_a_schedule_with_no_targets_anywhere_is_refused() -> None:
    with pytest.raises(ValueError, match="no target event"):
        moving_block_bootstrap([_window("a", []), _window("b", [])], n_resamples=10)


def test_the_width_ratio_needs_a_normal_interval_to_compare_against() -> None:
    windows = [_window(str(i), [0.5]) for i in range(20)]
    bare = moving_block_bootstrap(windows, n_resamples=200, rng=np.random.default_rng(0))
    assert bare.width_ratio is None
    assert bare.verdict_changed is None


def test_sensitivity_reports_one_result_per_block_length() -> None:
    windows = [_window(str(i), [0.5, -0.2]) for i in range(20)]
    results = block_length_sensitivity(windows, lengths=(1, 2, 4), n_resamples=300, seed=5)
    assert [r.block_length for r in results] == [1, 2, 4]
    assert conclusion_holds_across_lengths(results) is not None


def test_agreement_across_lengths_is_detected() -> None:
    same = [BlockBootstrapResult(0.5, 0.1, 0.9, 0.95, b, 100, 20, 40, 20.0, 0.0) for b in (1, 2, 3)]
    assert conclusion_holds_across_lengths(same) is True
    mixed = [*same, BlockBootstrapResult(0.5, -0.1, 0.9, 0.95, 5, 100, 20, 40, 20.0, 0.0)]
    assert conclusion_holds_across_lengths(mixed) is False


# ---------------------------------------------------------------- the committed evidence


@pytest.fixture(scope="module")
def checks() -> list[Any]:
    if not CHALLENGERS.exists():
        pytest.skip(f"{CHALLENGERS} is not in this clone")
    return read_all_with_blocks(CHALLENGERS, n_resamples=3000, seed=0)


def test_the_turkiye_schedule_is_dominated_by_one_window(checks: list[Any]) -> None:
    """160 of 217 target events are the Kahramanmaraş sequence."""
    hit = next(c for c in checks if c.powered.region_id == "turkiye-eaf")
    first = hit.sensitivity[0]
    assert first.n_events == 217
    assert first.effective_blocks < 3.0, "217 events are worth about 1.8 independent windows"


def test_the_only_positive_result_survives_the_clustering_correction(checks: list[Any]) -> None:
    """The Türkiye log-linear ensemble is the one metric this repository has ever beaten."""
    hit = next(
        c
        for c in checks
        if c.powered.region_id == "turkiye-eaf" and "ensemble" in c.powered.model_id
    )
    assert hit.robust is True
    assert all(not r.crosses_zero for r in hit.sensitivity)
    assert hit.verdict_survives is True
    assert all(r.lower > 0 for r in hit.sensitivity)


def test_the_interval_widens_and_skews_once_clustering_is_allowed_for(checks: list[Any]) -> None:
    hit = next(
        c
        for c in checks
        if c.powered.region_id == "turkiye-eaf" and "ensemble" in c.powered.model_id
    )
    widths = [r.width_ratio for r in hit.sensitivity]
    assert all(w is not None and w > 2.0 for w in widths)
    assert hit.sensitivity[0].skew > 1.0, "a symmetric interval cannot express this"


def test_a_published_significant_verdict_that_does_not_survive_is_named(
    checks: list[Any],
) -> None:
    """Nepal's gridded model was published as significantly worse than ETAS (p = 0.0125)."""
    hit = next(
        c
        for c in checks
        if c.powered.region_id == "nepal-himalaya" and "gridded" in c.powered.model_id
    )
    assert hit.powered.significant is True
    assert hit.verdict_survives is False
    assert all(r.crosses_zero for r in hit.sensitivity)
    assert "DOES NOT SURVIVE" in hit.render()


def test_the_block_detectable_effect_is_larger_than_the_independent_one(
    checks: list[Any],
) -> None:
    """A wider interval means a larger smallest-findable effect, everywhere."""
    for check in checks:
        assert check.block_mde is not None
        assert check.block_mde > check.powered.minimum_detectable_gain
