"""Simulation-based power for N/M/S/L/CL: calibration first, then what the tests can see.

Every figure this module produces rests on one property — that the simulated rejection region
rejects a *correct* forecast at the nominal rate. If it does not, no power number below means
anything, so that is the first test here and the one to read if any other starts failing.
"""

from __future__ import annotations

import numpy as np
import pytest

from rupture.scoring import consistency_power as cp

MAGNITUDES = np.array([5.0, 5.5, 6.0])


def _forecast(total: float = 200.0, n_space: int = 24) -> np.ndarray:
    """A deliberately non-uniform forecast: the concentration family needs a shape to exaggerate."""
    spatial = np.linspace(1.0, 9.0, n_space)[:, None]
    magnitude = np.array([0.7, 0.25, 0.05])[None, :]
    base = spatial * magnitude
    return np.asarray(base / base.sum() * total, dtype=np.float64)


# --------------------------------------------------------------------------- calibration


@pytest.mark.parametrize("test", list(cp.ConsistencyTest))
def test_the_null_rejection_rate_is_close_to_alpha(test: cp.ConsistencyTest) -> None:
    """The calibration check the whole construction rests on, measured on a fresh null sample.

    The N and CL statistics are discrete, so their attainable size sits a little below nominal;
    the tolerance is two-sided and wide enough for that but not for a systematically wrong tail.
    """
    rng = np.random.default_rng(4242)
    forecast = _forecast()
    result = cp.simulated_power(forecast, forecast, test, alpha=0.05, n_simulations=4000, rng=rng)
    assert result.null_rejection_rate is not None
    # Three standard errors of the *pair* of finite samples involved — the one the threshold was
    # read off and the one the rate was measured on. See ConsistencyPowerResult.calibration_error.
    assert abs(result.null_rejection_rate - 0.05) < 3.0 * result.calibration_error
    assert result.calibrated is True


def test_power_against_the_forecast_itself_is_the_size_of_the_test() -> None:
    """An "alternative" identical to the forecast is the null, so power must land on alpha.

    This is also the guard on the one mistake that would make the whole module silently useless:
    if the simulated catalogues were scored against the rates that generated them, every
    alternative would report this number.
    """
    rng = np.random.default_rng(11)
    forecast = _forecast()
    result = cp.simulated_power(
        forecast, forecast, cp.ConsistencyTest.L, n_simulations=4000, rng=rng
    )
    assert result.power is not None
    assert abs(result.power - 0.05) < 0.015


# ------------------------------------------------------------------- no rejection region


def test_a_test_with_no_rejection_region_says_so_rather_than_reporting_zero_power() -> None:
    """Ten simulated catalogues cannot resolve a 5 % tail, so nothing would ever reject."""
    rng = np.random.default_rng(3)
    forecast = _forecast()
    region = cp.rejection_region(
        forecast, cp.ConsistencyTest.L, alpha=0.05, n_simulations=10, rng=rng
    )
    assert region.exists is False
    assert region.reason is not None
    assert "cannot resolve a tail" in region.reason

    result = cp.simulated_power(
        forecast,
        cp.rate_multiplier_alternative(forecast, 5.0),
        cp.ConsistencyTest.L,
        n_simulations=10,
        rng=rng,
    )
    assert result.power is None
    assert result.power_standard_error is None


def test_a_low_rate_forecast_has_no_low_side_rejection_region_for_the_n_test() -> None:
    """Expecting 0.1 events, observing none is the modal outcome: the low tail cannot reject.

    The upper tail still can, so the region exists in part. Reporting the pair rather than a
    single boolean is what lets a caller say *which* direction of error the test was blind to.
    """
    rng = np.random.default_rng(5)
    region = cp.rejection_region(
        np.full((5, 2), 0.01), cp.ConsistencyTest.N, alpha=0.05, n_simulations=4000, rng=rng
    )
    assert region.lower is None
    assert region.upper is not None
    assert region.exists is True


# --------------------------------------------------------------------------- power rises


def test_power_rises_with_the_effect_size() -> None:
    rng = np.random.default_rng(101)
    forecast = _forecast()
    powers = [
        cp.simulated_power(
            forecast,
            cp.rate_multiplier_alternative(forecast, k),
            cp.ConsistencyTest.N,
            n_simulations=2000,
            rng=rng,
            check_calibration=False,
        ).power
        for k in (1.05, 1.2, 1.6)
    ]
    assert all(p is not None for p in powers)
    assert powers[0] < powers[1] < powers[2]  # type: ignore[operator]


def test_power_rises_with_the_sample_size() -> None:
    """The same relative rate error, on forecasts expecting 50, 200 and 800 events."""
    rng = np.random.default_rng(102)
    powers = []
    for total in (50.0, 200.0, 800.0):
        forecast = _forecast(total)
        powers.append(
            cp.simulated_power(
                forecast,
                cp.rate_multiplier_alternative(forecast, 1.2),
                cp.ConsistencyTest.N,
                n_simulations=2000,
                rng=rng,
                check_calibration=False,
            ).power
        )
    assert all(p is not None for p in powers)
    assert powers[0] < powers[1] < powers[2]  # type: ignore[operator]


def test_the_s_test_power_rises_with_spatial_concentration() -> None:
    rng = np.random.default_rng(103)
    forecast = _forecast()
    powers = [
        cp.simulated_power(
            forecast,
            cp.spatial_concentration_alternative(forecast, c),
            cp.ConsistencyTest.S,
            n_simulations=2000,
            rng=rng,
            check_calibration=False,
        ).power
        for c in (1.3, 2.0, 3.0)
    ]
    assert all(p is not None for p in powers)
    assert powers[0] < powers[1] < powers[2]  # type: ignore[operator]


# --------------------------------------------------------- each test sees only what it sees


def test_the_n_test_is_blind_to_a_purely_spatial_error_and_the_s_test_is_not() -> None:
    """The concentration family holds the total fixed, so the N-test cannot see it at all."""
    rng = np.random.default_rng(104)
    forecast = _forecast()
    alternative = cp.spatial_concentration_alternative(forecast, 3.0)
    blind = cp.simulated_power(
        forecast, alternative, cp.ConsistencyTest.N, n_simulations=2000, rng=rng
    )
    sighted = cp.simulated_power(
        forecast, alternative, cp.ConsistencyTest.S, n_simulations=2000, rng=rng
    )
    assert blind.power is not None
    assert abs(blind.power - 0.05) < 0.02
    assert sighted.power is not None
    assert sighted.power > 0.9


def test_the_s_test_is_blind_to_a_magnitude_error_and_the_m_test_is_not() -> None:
    rng = np.random.default_rng(105)
    forecast = _forecast()
    alternative = cp.magnitude_tilt_alternative(forecast, delta_b=0.5, magnitudes=MAGNITUDES)
    blind = cp.simulated_power(
        forecast, alternative, cp.ConsistencyTest.S, n_simulations=2000, rng=rng
    )
    sighted = cp.simulated_power(
        forecast, alternative, cp.ConsistencyTest.M, n_simulations=2000, rng=rng
    )
    assert blind.power is not None
    assert abs(blind.power - 0.05) < 0.02
    assert sighted.power is not None
    assert sighted.power > 0.8


# --------------------------------------------------------------------------- alternatives


def test_the_concentration_alternative_preserves_the_total_and_the_magnitude_marginal() -> None:
    forecast = _forecast()
    alternative = cp.spatial_concentration_alternative(forecast, 2.5)
    assert alternative.sum() == pytest.approx(forecast.sum())
    # Within each cell the magnitude split is untouched, which is what keeps the M-test blind.
    ratio = alternative / forecast
    assert np.allclose(ratio, ratio[:, :1])
    assert not np.allclose(alternative, forecast)


def test_the_concentration_alternative_is_degenerate_for_a_uniform_forecast() -> None:
    """Khawaja's case: a constant density raised to any power is the same constant density.

    The honest answer is that this *family* cannot express a departure from a shapeless forecast,
    not that the forecast's spatial component is untestable — the hotspot family still detects it.
    """
    uniform = np.full((30, 2), 5.0)
    assert np.allclose(cp.spatial_concentration_alternative(uniform, 4.0), uniform)

    rng = np.random.default_rng(106)
    assert (
        cp.minimum_detectable_concentration(uniform, n_simulations=500, rng=rng, target_power=0.8)
        is None
    )
    hotspot = cp.spatial_hotspot_alternative(uniform, cells=np.arange(3), share=0.5)
    assert hotspot.sum() == pytest.approx(uniform.sum())
    detected = cp.simulated_power(
        uniform, hotspot, cp.ConsistencyTest.S, n_simulations=1000, rng=rng
    )
    assert detected.power is not None
    assert detected.power > 0.9


def test_the_magnitude_tilt_preserves_the_total_and_the_spatial_marginal() -> None:
    forecast = _forecast()
    alternative = cp.magnitude_tilt_alternative(forecast, delta_b=0.4, magnitudes=MAGNITUDES)
    assert alternative.sum() == pytest.approx(forecast.sum())
    assert np.allclose(alternative.sum(axis=1), forecast.sum(axis=1))
    # A positive delta_b makes the truth relatively poorer in large events than forecast.
    assert alternative[:, -1].sum() < forecast[:, -1].sum()


# --------------------------------------------------------------------------- statistics


def test_the_number_statistic_is_the_observed_total() -> None:
    forecast = _forecast()
    counts = np.zeros(forecast.shape, dtype=np.int64)
    counts[0, 0] = 3
    counts[5, 2] = 4
    assert cp.statistic(forecast, counts, cp.ConsistencyTest.N) == 7.0


def test_the_conditional_likelihood_equals_the_likelihood_when_the_count_matches() -> None:
    """CL rescales the forecast to the observed total; when they already agree it is an identity."""
    forecast = _forecast(total=12.0, n_space=4)
    counts = np.ones(forecast.shape, dtype=np.int64)  # 4 x 3 bins, 12 events, total matches
    assert counts.sum() == pytest.approx(forecast.sum())
    joint = cp.statistic(forecast, counts, cp.ConsistencyTest.L)
    conditional = cp.statistic(forecast, counts, cp.ConsistencyTest.CL)
    assert conditional == pytest.approx(joint)


def test_an_event_where_the_forecast_declared_zero_rate_is_infinitely_unlikely() -> None:
    forecast = _forecast(total=12.0, n_space=4)
    forecast[0, 0] = 0.0
    counts = np.zeros(forecast.shape, dtype=np.int64)
    counts[0, 0] = 1
    assert cp.statistic(forecast, counts, cp.ConsistencyTest.L) == -np.inf


# ------------------------------------------------------------------ minimum detectable effect


def test_the_minimum_detectable_multiplier_reaches_target_power_and_a_smaller_one_does_not() -> (
    None
):
    rng = np.random.default_rng(2024)
    forecast = _forecast()
    mdm = cp.minimum_detectable_rate_multiplier(forecast, n_simulations=2000, rng=rng)
    assert mdm is not None
    assert 1.0 < mdm < 2.0
    at_effect = cp.simulated_power(
        forecast,
        cp.rate_multiplier_alternative(forecast, mdm),
        cp.ConsistencyTest.N,
        n_simulations=4000,
        rng=rng,
        check_calibration=False,
    ).power
    halfway = cp.simulated_power(
        forecast,
        cp.rate_multiplier_alternative(forecast, 1.0 + (mdm - 1.0) / 2.0),
        cp.ConsistencyTest.N,
        n_simulations=4000,
        rng=rng,
        check_calibration=False,
    ).power
    assert at_effect is not None
    assert halfway is not None
    assert at_effect > 0.75  # Monte Carlo slack around the 0.8 target
    assert halfway < 0.6


def test_more_events_make_a_smaller_rate_error_detectable() -> None:
    rng = np.random.default_rng(2025)
    small = cp.minimum_detectable_rate_multiplier(_forecast(50.0), n_simulations=2000, rng=rng)
    large = cp.minimum_detectable_rate_multiplier(_forecast(2000.0), n_simulations=2000, rng=rng)
    assert small is not None
    assert large is not None
    assert 1.0 < large < small


def test_the_detectable_multiplier_below_one_is_asked_for_separately() -> None:
    rng = np.random.default_rng(2026)
    forecast = _forecast()
    below = cp.minimum_detectable_rate_multiplier(
        forecast, direction="below", n_simulations=2000, rng=rng
    )
    assert below is not None
    assert 0.0 < below < 1.0


def test_an_undetectable_effect_returns_none_rather_than_a_multiplier() -> None:
    """Twenty expected events cannot resolve a 2 % rate error however the search is run."""
    rng = np.random.default_rng(2027)
    assert (
        cp.minimum_detectable_rate_multiplier(
            _forecast(20.0), n_simulations=500, rng=rng, largest_multiplier=1.02
        )
        is None
    )


# --------------------------------------------------------------------------- events needed


def test_detecting_a_smaller_effect_needs_more_events() -> None:
    """The Khawaja figure in miniature: halve the effect and the required catalogue grows."""
    rng = np.random.default_rng(909)
    forecast = _forecast()
    big = cp.events_needed_for_rate_multiplier(
        forecast, 1.5, n_simulations=600, rng=rng, rel_tol=0.15
    )
    small = cp.events_needed_for_rate_multiplier(
        forecast, 1.15, n_simulations=600, rng=rng, rel_tol=0.15
    )
    assert big is not None
    assert small is not None
    assert small > big


def test_events_needed_reports_none_rather_than_a_number_beyond_its_cap() -> None:
    rng = np.random.default_rng(910)
    assert (
        cp.events_needed_for_rate_multiplier(
            _forecast(), 1.02, n_simulations=400, rng=rng, max_events=200.0
        )
        is None
    )


def test_the_events_needed_figure_agrees_with_a_direct_power_calculation() -> None:
    """Scale the forecast to the returned total and the test should sit near its target power."""
    rng = np.random.default_rng(911)
    forecast = _forecast()
    needed = cp.events_needed_for_rate_multiplier(
        forecast, 1.3, n_simulations=1000, rng=rng, rel_tol=0.1
    )
    assert needed is not None
    scaled = forecast / forecast.sum() * needed
    power = cp.simulated_power(
        scaled,
        cp.rate_multiplier_alternative(scaled, 1.3),
        cp.ConsistencyTest.N,
        n_simulations=4000,
        rng=rng,
        check_calibration=False,
    ).power
    assert power is not None
    assert 0.7 < power < 0.92


def test_a_multiplier_of_one_is_the_forecast_itself_and_is_refused() -> None:
    rng = np.random.default_rng(912)
    with pytest.raises(ValueError, match="never detectable"):
        cp.events_needed_for_rate_multiplier(_forecast(), 1.0, rng=rng)


# --------------------------------------------------------------------------- refusals


def test_the_m_test_is_refused_when_the_forecast_resolves_one_magnitude_bin() -> None:
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError, match="two magnitude bins"):
        cp.rejection_region(np.full(10, 2.0), cp.ConsistencyTest.M, n_simulations=100, rng=rng)


def test_the_s_test_is_refused_when_the_forecast_resolves_one_spatial_bin() -> None:
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError, match="two spatial bins"):
        cp.rejection_region(np.full((1, 4), 2.0), cp.ConsistencyTest.S, n_simulations=100, rng=rng)


@pytest.mark.parametrize(
    ("forecast", "match"),
    [
        (np.zeros((4, 2)), "positive total"),
        (np.array([[1.0, -1.0], [1.0, 1.0]]), "non-negative"),
        (np.array([[1.0, np.nan], [1.0, 1.0]]), "finite"),
        (np.zeros((2, 2, 2)), "1-D"),
    ],
)
def test_impossible_forecasts_are_refused(forecast: np.ndarray, match: str) -> None:
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError, match=match):
        cp.rejection_region(forecast, cp.ConsistencyTest.L, n_simulations=100, rng=rng)


def test_an_alternative_of_a_different_shape_is_refused() -> None:
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError, match="match the forecast shape"):
        cp.simulated_power(
            _forecast(), _forecast(n_space=12), cp.ConsistencyTest.L, n_simulations=100, rng=rng
        )


@pytest.mark.parametrize("alpha", [0.0, 1.0, -0.1])
def test_an_impossible_alpha_is_refused(alpha: float) -> None:
    rng = np.random.default_rng(1)
    with pytest.raises(ValueError, match="alpha"):
        cp.rejection_region(
            _forecast(), cp.ConsistencyTest.L, alpha=alpha, n_simulations=100, rng=rng
        )


def test_a_hotspot_must_be_a_proper_subset_carrying_forecast_rate() -> None:
    forecast = _forecast()
    with pytest.raises(ValueError, match="proper subset"):
        cp.spatial_hotspot_alternative(forecast, cells=np.arange(forecast.shape[0]), share=0.5)
    with pytest.raises(ValueError, match="share"):
        cp.spatial_hotspot_alternative(forecast, cells=np.arange(3), share=1.0)


def test_chunked_simulation_gives_the_same_answer_as_a_single_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fine grid is simulated in chunks so it cannot exhaust memory; the law must not change.

    Forcing one catalogue per chunk exercises the loop that a realistic grid would trigger and a
    24-cell test forecast never would.
    """
    forecast = _forecast(total=40.0, n_space=8)
    whole = cp.simulate_statistics(
        forecast, cp.ConsistencyTest.L, n_simulations=64, rng=np.random.default_rng(77)
    )
    monkeypatch.setattr(cp, "_MAX_CHUNK_ELEMENTS", 1)
    chunked = cp.simulate_statistics(
        forecast, cp.ConsistencyTest.L, n_simulations=64, rng=np.random.default_rng(77)
    )
    # Bit-for-bit identical, not merely distributionally so: the chunk loop consumes the same
    # random stream in the same order, so chunking can never quietly change a published figure.
    assert np.array_equal(chunked, whole)
