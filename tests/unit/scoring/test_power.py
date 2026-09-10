"""Power and minimum detectable effect: the figures ADR-0055 makes mandatory."""

from __future__ import annotations

import pytest
from scipy.stats import binom, norm

from rupture.scoring import power


def test_the_critical_hit_count_is_the_smallest_that_rejects() -> None:
    c = power.critical_hits(100, 0.05, 0.05)
    assert c is not None
    assert float(binom.sf(c - 1, 100, 0.05)) <= 0.05
    assert float(binom.sf(c - 2, 100, 0.05)) > 0.05


def test_a_test_with_no_rejection_region_says_so_rather_than_passing() -> None:
    """Two targets and a 92 % alarm fraction: nothing that could happen would reject."""
    assert power.critical_hits(2, 0.92, 0.05) is None
    assert power.power_at_gain(2, 0.92, 5.0, 0.05) == 0.0
    assert power.minimum_detectable_gain(2, 0.92) is None


def test_power_rises_with_the_gain_and_with_the_sample() -> None:
    assert power.power_at_gain(200, 0.1, 1.0, 0.05) < power.power_at_gain(200, 0.1, 2.0, 0.05)
    assert power.power_at_gain(50, 0.1, 2.0, 0.05) < power.power_at_gain(500, 0.1, 2.0, 0.05)


def test_the_minimum_detectable_gain_is_the_smallest_that_reaches_the_target_power() -> None:
    mdg = power.minimum_detectable_gain(130, 0.1, alpha=0.05, target_power=0.8)
    assert mdg is not None
    assert power.power_at_gain(130, 0.1, mdg, 0.05) >= 0.8
    assert power.power_at_gain(130, 0.1, mdg * 0.98, 0.05) < 0.8


def test_more_targets_make_a_smaller_effect_detectable() -> None:
    small = power.minimum_detectable_gain(50, 0.1)
    large = power.minimum_detectable_gain(5000, 0.1)
    assert small is not None
    assert large is not None
    assert large < small


def test_events_needed_is_the_smallest_sample_reaching_the_target_power() -> None:
    n = power.events_needed_for_gain(0.1, 2.0)
    assert n is not None
    assert power.power_at_gain(n, 0.1, 2.0, 0.05) >= 0.8
    assert power.power_at_gain(n - 1, 0.1, 2.0, 0.05) < 0.8


def test_a_gain_of_one_is_the_reference_itself_and_is_refused() -> None:
    with pytest.raises(ValueError, match="never detectable"):
        power.events_needed_for_gain(0.1, 1.0)


def test_the_information_gain_bound_shrinks_as_the_root_of_the_sample() -> None:
    a = power.minimum_detectable_information_gain(100, 1.0)
    b = power.minimum_detectable_information_gain(400, 1.0)
    assert a == pytest.approx(2.0 * b, rel=1e-9)


def test_the_information_gain_bound_is_the_textbook_expression() -> None:
    expected = (norm.isf(0.05) + norm.isf(0.2)) * 0.5 / 55**0.5
    assert power.minimum_detectable_information_gain(55, 0.5) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"n_targets": -1, "tau": 0.1, "alpha": 0.05}, "non-negative"),
        ({"n_targets": 10, "tau": 0.0, "alpha": 0.05}, "tau"),
        ({"n_targets": 10, "tau": 1.5, "alpha": 0.05}, "tau"),
        ({"n_targets": 10, "tau": 0.1, "alpha": 1.0}, "alpha"),
    ],
)
def test_impossible_inputs_are_refused(kwargs: dict[str, float], match: str) -> None:
    with pytest.raises(ValueError, match=match):
        power.critical_hits(**kwargs)  # type: ignore[arg-type]
