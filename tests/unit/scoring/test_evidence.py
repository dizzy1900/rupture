"""Retrofitting power onto results that predate the rule that requires it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scipy.stats import norm

from rupture.scoring.evidence import (
    PoweredResult,
    power_for_result,
    read_all,
    read_schedule,
    sd_from_interval,
)

CHALLENGERS = Path("reports/challenger")


def test_the_standard_error_is_recovered_exactly_from_a_symmetric_interval() -> None:
    """The inversion the whole module rests on, checked against the definition."""
    sd, n = 0.75, 120
    se = sd / n**0.5
    z = float(norm.isf(0.025))
    recovered = sd_from_interval(0.3 - z * se, 0.3 + z * se, n)
    assert recovered == pytest.approx(sd)


def test_a_wider_interval_means_a_larger_detectable_effect() -> None:
    tight = power_for_result(
        region_id="r",
        model_id="m",
        benchmark_model_id="b",
        n_target_events=200,
        information_gain_per_event=0.1,
        ig_lower=0.05,
        ig_upper=0.15,
        p_value=0.01,
    )
    loose = power_for_result(
        region_id="r",
        model_id="m",
        benchmark_model_id="b",
        n_target_events=200,
        information_gain_per_event=0.1,
        ig_lower=-0.4,
        ig_upper=0.6,
        p_value=0.7,
    )
    assert tight.minimum_detectable_gain < loose.minimum_detectable_gain


def test_an_inverted_interval_is_refused() -> None:
    with pytest.raises(ValueError, match="inverted"):
        sd_from_interval(0.5, 0.1, 10)


def test_no_events_is_refused() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        sd_from_interval(0.1, 0.5, 0)


def test_a_significant_negative_result_is_not_reported_as_skill() -> None:
    """A model significantly worse than its reference must not read as 'x the detectable effect'."""
    worse = power_for_result(
        region_id="r",
        model_id="m",
        benchmark_model_id="etas",
        n_target_events=53,
        information_gain_per_event=-0.62,
        ig_lower=-1.10,
        ig_upper=-0.14,
        p_value=0.01,
    )
    assert worse.significant is True
    assert worse.beats_reference is False
    assert worse.effect_over_mde < 0
    assert "significantly *worse*" in worse.render()


def test_a_null_result_renders_its_upper_bound() -> None:
    """ADR-0055 decision 5: not 'we saw nothing' but 'we could have seen this much'."""
    null = power_for_result(
        region_id="r",
        model_id="m",
        benchmark_model_id="etas",
        n_target_events=53,
        information_gain_per_event=-0.079,
        ig_lower=-0.346,
        ig_upper=0.188,
        p_value=0.56,
    )
    assert null.significant is False
    assert null.beats_reference is False
    assert "Upper bound" in null.render()
    assert f"{null.minimum_detectable_gain:.4f}" in null.render()


def test_an_undecided_comparison_has_no_verdict() -> None:
    undecided = power_for_result(
        region_id="r",
        model_id="m",
        benchmark_model_id="etas",
        n_target_events=5,
        information_gain_per_event=0.0,
        ig_lower=-1.0,
        ig_upper=1.0,
        p_value=None,
    )
    assert undecided.significant is None
    assert undecided.beats_reference is None


# ---------------------------------------------------------------- the committed evidence


@pytest.fixture(scope="module")
def committed() -> list[PoweredResult]:
    if not CHALLENGERS.exists():
        pytest.skip(f"{CHALLENGERS} is not in this clone")
    return read_all(CHALLENGERS)


def test_every_committed_comparison_can_be_powered(committed: list[PoweredResult]) -> None:
    assert len(committed) == 4
    assert all(r.minimum_detectable_gain > 0 for r in committed)


def test_the_one_metric_ever_beaten_here_is_comfortably_powered(
    committed: list[PoweredResult],
) -> None:
    """Türkiye's log-linear ensemble is the only result in this repository that beat ETAS."""
    hit = next(r for r in committed if r.region_id == "turkiye-eaf" and "ensemble" in r.model_id)
    assert hit.beats_reference is True
    assert hit.information_gain_per_event == pytest.approx(0.3354, abs=1e-3)
    assert hit.minimum_detectable_gain < 0.1
    assert hit.effect_over_mde > 3.0, "the effect is several times the smallest detectable one"


def test_a_near_blind_null_is_identifiable_as_one(committed: list[PoweredResult]) -> None:
    """Türkiye's gridded model saw +0.059 where only +0.456 was findable."""
    blind = next(r for r in committed if r.region_id == "turkiye-eaf" and "gridded" in r.model_id)
    assert blind.significant is False
    assert blind.minimum_detectable_gain > 5 * abs(blind.information_gain_per_event)


def test_a_schedule_with_an_undecided_test_is_skipped_not_invented(tmp_path: Path) -> None:
    path = tmp_path / "schedule-x-challengers.json"
    path.write_text(
        json.dumps(
            {
                "region_id": "x",
                "models": {
                    "m": {
                        "pooled_paired_test": {"decided": False},
                        "pooled_information_gain": {"target_events": 10},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert read_schedule(path) == []
