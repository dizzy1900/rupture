"""The generic Reasenberg-Jones table, the Bayesian update, and what they do to the committed runs.

Three things are worth guarding here and they are different in kind:

1. that the transcribed USGS table still says what the published rows say (a typo in a constant is
   silent and changes every forecast);
2. that the update behaves like a Bayesian update -- prior when there is no data, sequence
   maximum-likelihood when there is a lot, monotone in between -- rather than like a weighted
   average someone tuned;
3. that the default forecaster has not quietly changed, because ``reports/aftershock/`` and the
   model card describe the ETAS-only path and must regenerate.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from rupture.domain import Catalog, ForecastGrid, Region, snapshot_hash
from rupture.services.aftershock.forecaster import (
    AftershockForecaster,
    RateModel,
    rescaled_to_total,
)
from rupture.services.aftershock.generic import (
    GENERIC_RJ,
    SETTING_TO_REGIME,
    SequenceObservation,
    expected_count,
    generic_for_region,
    generic_prior,
    omori_integral,
    productivity_exposure,
    regime_for_region,
    sequence_observation,
    update,
)
from rupture.services.aftershock.generic_validation import compare_sequence
from rupture.services.aftershock.sequences import SequenceSpec

MAINSHOCK_TIME = datetime(2015, 4, 25, 6, 11, 26, tzinfo=UTC)


# ---------------------------------------------------------------- the transcribed table
def test_table_holds_the_fifteen_garcia_regimes() -> None:
    assert len(GENERIC_RJ) == 15
    assert all(key == value.regime for key, value in GENERIC_RJ.items())


@pytest.mark.parametrize(
    ("regime", "a_max_like", "p", "a_mean", "a_sigma", "a_sigma1"),
    [
        # Rows of PageEtAlGenericParams_032116.csv, retyped independently of the module so a
        # transcription slip has to happen twice to survive.
        ("ANSR-SHALCON", -2.16, 0.98, -2.42, 0.63, 570.0),
        ("ANSR-DEEPCON", -2.01, 0.98, -2.13, 0.52, 250.0),
        ("SZ-GENERIC", -2.09, 0.88, -2.47, 0.63, 570.0),
        ("SCR-GENERIC", -2.28, 0.73, -2.85, 0.78, 870.0),
        ("SOR-GENERIC", -2.98, 0.97, -3.04, 0.67, 650.0),
        ("ANSR-HOTSPOT", -2.84, 1.12, -3.00, 0.68, 680.0),
    ],
)
def test_published_rows_are_transcribed_exactly(
    *, regime: str, a_max_like: float, p: float, a_mean: float, a_sigma: float, a_sigma1: float
) -> None:
    row = GENERIC_RJ[regime]
    assert row.a_max_likelihood == a_max_like
    assert row.p_value == p
    assert row.a_mean == a_mean
    assert row.a_sigma == a_sigma
    assert row.a_sigma1 == a_sigma1
    assert row.a_sigma0 == 0.49
    assert row.b_value == 1.00
    assert row.c_value_days == 0.018


def test_a_sigma_is_the_usgs_magnitude_dependent_form() -> None:
    row = GENERIC_RJ["ANSR-SHALCON"]
    expected = math.sqrt(0.49**2 + 570.0**2 / 10.0**7.8)
    assert row.a_sigma_for(7.8) == pytest.approx(expected)
    # Below M6 the spread is held at its M6 value rather than continuing to grow.
    assert row.a_sigma_for(5.0) == pytest.approx(row.a_sigma_for(6.0))
    assert row.a_sigma_for(7.8) < row.a_sigma_for(6.0)


def test_settings_without_a_defensible_regime_are_absent_rather_than_guessed() -> None:
    names = set(SETTING_TO_REGIME.values())
    assert names <= set(GENERIC_RJ)
    assert "mixed" not in {s.value for s in SETTING_TO_REGIME}
    assert "other" not in {s.value for s in SETTING_TO_REGIME}


def test_region_regime_comes_from_the_tectonic_setting(nepal_region: Region) -> None:
    assert regime_for_region(nepal_region) == "ANSR-SHALCON"
    assert generic_for_region(nepal_region) is GENERIC_RJ["ANSR-SHALCON"]


def test_unmapped_setting_raises_and_says_what_to_do(nepal_region: Region) -> None:
    mixed = nepal_region.model_copy(update={"tectonic_setting": "mixed"})
    with pytest.raises(KeyError, match="no generic-parameter regime"):
        regime_for_region(mixed)


# ---------------------------------------------------------------- the rate model
def test_omori_integral_matches_the_closed_form_away_from_p_one() -> None:
    # p = 2: Integral[(t + c)^-2] = 1/(c + t1) - 1/(c + t2), exactly.
    got = omori_integral(2.0, 0.05, 0.0, 1.0)
    assert got == pytest.approx(1.0 / 0.05 - 1.0 / 1.05)


def test_omori_integral_is_the_logarithm_at_p_one_and_continuous_around_it() -> None:
    at_one = omori_integral(1.0, 0.018, 0.0, 1.0)
    assert at_one == pytest.approx(math.log(1.018) - math.log(0.018))
    # The 1 - p denominator is where a naive implementation loses its precision.
    assert omori_integral(1.0 - 1e-9, 0.018, 0.0, 1.0) == pytest.approx(at_one, rel=1e-6)
    assert omori_integral(1.0 + 1e-9, 0.018, 0.0, 1.0) == pytest.approx(at_one, rel=1e-6)


def test_expected_count_scales_as_gutenberg_richter_in_magnitude() -> None:
    kwargs = {
        "b": 1.0,
        "mainshock_magnitude": 7.8,
        "p": 0.98,
        "c_days": 0.018,
        "t1_days": 0.0,
        "t2_days": 1.0,
    }
    low = expected_count(a=-2.42, min_magnitude=4.0, **kwargs)  # type: ignore[arg-type]
    high = expected_count(a=-2.42, min_magnitude=5.0, **kwargs)  # type: ignore[arg-type]
    assert low / high == pytest.approx(10.0)


def test_exposure_is_the_expected_count_per_unit_productivity() -> None:
    shared = {
        "b": 1.0,
        "mainshock_magnitude": 7.8,
        "min_magnitude": 4.7,
        "p": 0.98,
        "c_days": 0.018,
        "t1_days": 0.0,
        "t2_days": 1.0,
    }
    exposure = productivity_exposure(**shared)  # type: ignore[arg-type]
    assert expected_count(a=-2.42, **shared) == pytest.approx(  # type: ignore[arg-type]
        10.0**-2.42 * exposure
    )


def test_negative_or_inverted_windows_are_refused() -> None:
    with pytest.raises(ValueError, match="precedes its start"):
        omori_integral(1.0, 0.018, 1.0, 0.5)
    with pytest.raises(ValueError, match="must not be negative"):
        omori_integral(1.0, 0.018, -1.0, 1.0)


# ---------------------------------------------------------------- the update
def _prior_and_exposure() -> tuple[float, float]:
    row = GENERIC_RJ["ANSR-SHALCON"]
    prior = generic_prior(row, mainshock_magnitude=7.8)
    exposure = productivity_exposure(
        b=row.b_value,
        mainshock_magnitude=7.8,
        min_magnitude=4.4,
        p=row.p_value,
        c_days=row.c_value_days,
        t1_days=0.0,
        t2_days=1.0,
    )
    return prior.mean_productivity(), exposure


def test_prior_integrates_to_one_and_does_not_pile_up_on_its_edges() -> None:
    prior = generic_prior(GENERIC_RJ["ANSR-SHALCON"], mainshock_magnitude=7.8)
    assert float(np.sum(prior.pdf) * prior.delta) == pytest.approx(1.0)
    assert prior.mean_a() == pytest.approx(-2.42, abs=1e-3)
    assert prior.mass_at_edges() < 1e-4


def test_mean_productivity_exceeds_the_productivity_of_the_mean_a() -> None:
    """Jensen, and it is the whole reason counts are averaged over the posterior, not plugged."""
    prior = generic_prior(GENERIC_RJ["ANSR-SHALCON"], mainshock_magnitude=7.8)
    assert prior.mean_productivity() > 10.0 ** prior.mean_a()


def test_an_empty_window_leaves_the_prior_untouched() -> None:
    prior = generic_prior(GENERIC_RJ["ANSR-SHALCON"], mainshock_magnitude=7.8)
    posterior = update(prior, SequenceObservation(0, min_magnitude=4.4, t1_days=0.0, t2_days=0.0))
    assert np.array_equal(posterior.pdf, prior.pdf)
    assert posterior.observation is not None


def test_a_long_rich_observation_drives_the_posterior_to_the_sequence_estimate() -> None:
    """With enough events the prior stops mattering: this is the 'blend' with no weights in it."""
    prior_mean, exposure = _prior_and_exposure()
    n = 500
    prior = generic_prior(GENERIC_RJ["ANSR-SHALCON"], mainshock_magnitude=7.8)
    posterior = update(prior, SequenceObservation(n, min_magnitude=4.4, t1_days=0.0, t2_days=1.0))
    assert posterior.mean_productivity() == pytest.approx(n / exposure, rel=0.05)
    assert posterior.mean_productivity() > prior_mean
    # A posterior pinned against the table's a range would pass the comparison above by accident.
    assert posterior.mass_at_edges() < 1e-6


def test_a_quiet_observed_window_pulls_the_productivity_below_the_prior() -> None:
    prior_mean, _ = _prior_and_exposure()
    prior = generic_prior(GENERIC_RJ["ANSR-SHALCON"], mainshock_magnitude=7.8)
    posterior = update(prior, SequenceObservation(0, min_magnitude=4.4, t1_days=0.0, t2_days=1.0))
    assert posterior.mean_productivity() < prior_mean


def test_the_posterior_moves_monotonically_with_the_number_observed() -> None:
    prior = generic_prior(GENERIC_RJ["ANSR-SHALCON"], mainshock_magnitude=7.8)
    means = [
        update(
            prior, SequenceObservation(n, min_magnitude=4.4, t1_days=0.0, t2_days=1.0)
        ).mean_productivity()
        for n in (0, 5, 20, 80, 320)
    ]
    assert means == sorted(means)


def test_probability_is_the_mixture_and_so_sits_below_the_plugged_in_poisson() -> None:
    """``E[1 - exp(-lambda)] <= 1 - exp(-E[lambda])``: the concavity is not a rounding artefact."""
    prior = generic_prior(GENERIC_RJ["ANSR-SHALCON"], mainshock_magnitude=7.8)
    kwargs = {"min_magnitude": 4.7, "t1_days": 0.0, "t2_days": 1.0}
    lam = prior.expected_count(**kwargs)  # type: ignore[arg-type]
    p = prior.probability_at_least_one(**kwargs)  # type: ignore[arg-type]
    assert 0.0 <= p <= 1.0
    assert p < -math.expm1(-lam)


# ---------------------------------------------------------------- counting the sequence
def test_sequence_count_matches_the_committed_report_less_the_mainshock(
    gorkha: SequenceSpec, gorkha_catalog: Catalog, nepal_region: Region
) -> None:
    """``reports/aftershock/gorkha.json`` records 21 sequence events at +1 h, mainshock included.

    The likelihood must not count the mainshock as one of its own aftershocks, so this is 20; the
    agreement with the committed number is what says the two are counting the same population.
    """
    issue = gorkha.mainshock.origin_time + timedelta(hours=1)
    mc = nepal_region.mc.mc if nepal_region.mc is not None else 4.4
    observation = sequence_observation(
        gorkha_catalog.before(issue),
        mainshock=gorkha.mainshock,
        issue_time=issue,
        min_magnitude=mc,
    )
    assert observation.n_events == 20
    assert observation.t2_days == pytest.approx(1.0 / 24.0)


def test_dropping_the_first_hour_can_only_remove_events(
    gorkha: SequenceSpec, gorkha_catalog: Catalog
) -> None:
    issue = gorkha.mainshock.origin_time + timedelta(days=1)
    kwargs = {
        "mainshock": gorkha.mainshock,
        "issue_time": issue,
        "min_magnitude": 4.4,
    }
    full = sequence_observation(gorkha_catalog.before(issue), **kwargs)  # type: ignore[arg-type]
    trimmed = sequence_observation(
        gorkha_catalog.before(issue),
        start_offset=timedelta(hours=1),
        **kwargs,  # type: ignore[arg-type]
    )
    assert trimmed.n_events < full.n_events
    assert trimmed.t1_days == pytest.approx(1.0 / 24.0)


# ---------------------------------------------------------------- the grid rescale
def _grid(per_bin: tuple[float, ...]) -> ForecastGrid:
    half = tuple(v / 2.0 for v in per_bin)
    return ForecastGrid(
        id="g",
        region_id="r",
        model_id="m",
        model_version="v",
        parameter_snapshot_hash=snapshot_hash({}),
        fit_cutoff=MAINSHOCK_TIME,
        training_catalog_hash="h",
        issue_time=MAINSHOCK_TIME,
        horizon=timedelta(days=1),
        cell_size_deg=0.1,
        cell_origins=((84.0, 28.0), (84.1, 28.0)),
        magnitude_bin_edges=(4.7, 4.8, 4.9),
        magnitude_bin_width=0.1,
        expected_counts=(half, half),
        created_at=MAINSHOCK_TIME,
    )


def test_rescale_hits_the_target_and_keeps_the_shape() -> None:
    grid = _grid((1.0, 2.0, 1.0))
    scaled = rescaled_to_total(grid, target=40.0, above=4.7, note="test")
    assert scaled.total_expected() == pytest.approx(40.0)
    before, after = grid.counts(), scaled.counts()
    assert np.allclose(after / after.sum(), before / before.sum())
    # The rescaled grid is a composite — ETAS's shape, a Reasenberg-Jones level — and its
    # provenance says so. It used to keep ETAS's model id and ETAS's parameter snapshot hash,
    # which is the hash the schedule's leakage check compares, so the label was load-bearing.
    assert scaled.model_id == "m+rj-generic"
    assert scaled.id == ForecastGrid.make_id(
        "m+rj-generic", grid.region_id, grid.issue_time, grid.horizon
    )
    assert scaled.parameter_snapshot_hash != grid.parameter_snapshot_hash
    assert scaled.notes is not None
    assert "test" in scaled.notes


def test_rescale_targets_only_the_mass_above_the_threshold() -> None:
    grid = _grid((1.0, 2.0, 1.0))
    scaled = rescaled_to_total(grid, target=3.0, above=4.8, note="test")
    edges = np.asarray(scaled.magnitude_bin_edges)
    assert float(scaled.counts().sum(axis=0)[edges >= 4.8 - 1e-9].sum()) == pytest.approx(3.0)


def test_an_empty_grid_is_refused_rather_than_scaled_from_nothing() -> None:
    grid = _grid((0.0, 0.0, 0.0))
    with pytest.raises(ValueError, match="no expected mass"):
        rescaled_to_total(grid, target=5.0, above=4.7, note="test")


# ---------------------------------------------------------------- the default has not moved
def test_the_default_rate_model_is_still_plain_etas() -> None:
    """The committed reports and the model card describe this path; changing it silently is the
    failure this assertion exists to prevent."""
    forecaster = AftershockForecaster()
    assert forecaster.rate_model is RateModel.ETAS
    assert forecaster.generic_regime is None
    assert forecaster.generic_likelihood_start == timedelta(0)


def test_posterior_for_is_reachable_without_running_etas(
    gorkha: SequenceSpec, gorkha_catalog: Catalog, nepal_region: Region
) -> None:
    forecaster = AftershockForecaster(rate_model=RateModel.ETAS_RJ_GENERIC)
    zone = forecaster.zone(gorkha.mainshock, nepal_region)
    issue = gorkha.mainshock.origin_time + timedelta(hours=1)
    posterior = forecaster.posterior_for(
        history=gorkha_catalog.before(issue),
        region=zone,
        mainshock=gorkha.mainshock,
        issue_time=issue,
    )
    assert posterior.parameters.regime == "ANSR-SHALCON"
    assert posterior.observation is not None
    assert posterior.observation.n_events == 20


# ---------------------------------------------------------------- the measured effect
DAY_ONE = {("1h", "1d"), ("1d", "1d")}


@pytest.mark.parametrize("sequence", ["gorkha", "kahramanmaras"])
def test_generic_parameters_reduce_the_day_one_under_forecast(
    sequence: str, repo_root: Path
) -> None:
    """The claim in RELEASE_STATUS, and what the generic prior actually does to it.

    The committed ETAS run under-forecasts the day-one windows by 2.8-12.8x. This asserts only
    what was measured: the Bayesian generic count is closer to the observed count in every one of
    those windows, and it is still short of it -- an under-forecast reduced, not removed.
    """
    comparison = compare_sequence(sequence, repo_root)
    day_one = [
        row for row in comparison.windows if (row.window.issue_label, row.window.horizon) in DAY_ONE
    ]
    assert len(day_one) == 2
    for row in day_one:
        assert row.ratio_etas is not None
        assert row.ratio_bayesian is not None
        assert row.ratio_etas > 2.5
        assert row.ratio_bayesian < row.ratio_etas
        assert row.ratio_bayesian > 1.0


def test_the_committed_etas_column_is_read_not_recomputed(repo_root: Path) -> None:
    """Guards the honesty of the comparison: the 'before' numbers come off disk unmodified."""
    comparison = compare_sequence("gorkha", repo_root)
    first = comparison.windows[0].window
    assert first.issue_label == "1h"
    assert first.etas_expected == pytest.approx(3.3719049914575763)
    assert first.observed == 43


def test_the_issued_grid_is_rescaled_to_exactly_the_posterior_count(
    gorkha: SequenceSpec,
    gorkha_catalog: Catalog,
    nepal_region: Region,
    gorkha_fits: dict[str, object],
) -> None:
    """End to end on the real slice: ETAS keeps the shape, the generic posterior sets the level.

    Deliberately crude (three continuations, 0.4-degree cells) because the assertion is about the
    seam between the two models, not about the ETAS number -- whatever the simulation produces,
    the issued grid's mass above the target threshold must equal the R-J posterior-mean count.
    """
    issue = gorkha.mainshock.origin_time + timedelta(hours=1)
    fit = next(v for k, v in gorkha_fits.items() if k.startswith("2015-04-25T07"))
    forecaster = AftershockForecaster(
        n_simulations=3, cell_size_deg=0.4, seed=5, rate_model=RateModel.ETAS_RJ_GENERIC
    )
    issuance = forecaster.forecast(
        catalog=gorkha_catalog,
        parent_region=nepal_region,
        mainshock=gorkha.mainshock,
        issue_time=issue,
        horizon=timedelta(days=1),
        fit=fit,  # type: ignore[arg-type]
    )
    assert issuance.posterior is not None
    expected = issuance.posterior.expected_count(
        min_magnitude=issuance.region.target_min_magnitude,
        t1_days=1.0 / 24.0,
        t2_days=1.0 + 1.0 / 24.0,
    )
    counts = np.asarray(issuance.grid.expected_counts)
    edges = np.asarray(issuance.grid.magnitude_bin_edges)
    above = float(counts.sum(axis=0)[edges >= issuance.region.target_min_magnitude - 1e-9].sum())
    assert above == pytest.approx(expected, rel=1e-9)
    # The issued grid is a composite and its model id says so, rather than reading as the plain
    # ETAS grid whose spatial shape it borrowed.
    assert issuance.grid.model_id.endswith("+rj-generic")
    assert issuance.forecast.model_id == "etas-mizrahi+etas-rj-generic"
