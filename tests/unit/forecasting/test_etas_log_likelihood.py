"""The ETAS space-time log-likelihood: identities that pin it to the model the EM fitted.

The brief requires the log-likelihood to be persisted with the parameters and diagnostics. The
``etas`` package exposes only the EM's expected complete-data objective, so the adapter assembles
the observed-data likelihood itself (``point_process_log_likelihood``, ADR-0046). These tests are
the evidence that the assembly is the right one; they do not merely check that a float is stored.

Everything here runs offline on the committed ComCat slice.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pytest
from etas import inversion as etas_inversion

from rupture.adapters.forecasting.etas_mizrahi import (
    THETA_KEYS,
    LogLikelihood,
    MizrahiETAS,
    point_process_log_likelihood,
)
from rupture.domain import Catalog, FitResult, Region
from tests.unit.forecasting.conftest import FIT_CUTOFF

MC = 3.5
"""A higher cut than the committed fit's 3.0: 61 training events, so a fit runs in a few seconds."""


@pytest.fixture(scope="module")
def small_fit(fixture_catalog: Catalog, region: Region) -> FitResult:
    return MizrahiETAS(auxiliary_years=0.5).fit(fixture_catalog, region, FIT_CUTOFF, mc=MC)


def _calc_at(model: MizrahiETAS, fit: FitResult, region: Region, catalog: Catalog, theta: dict):
    """The package state after one expectation step at ``theta`` on the fit's own window."""
    training = MizrahiETAS.training_slice(catalog, region, fit.fit_cutoff, fit.mc)
    # The test needs the exact configuration the fit used, so it calls the private builder.
    metadata = model._metadata(
        training,
        region,
        fit.mc,
        auxiliary_start=datetime.fromisoformat(fit.diagnostics["auxiliary_start"]),
        timewindow_start=datetime.fromisoformat(fit.diagnostics["timewindow_start"]),
        timewindow_end=fit.fit_cutoff,
        name="test",
    )
    metadata["beta"] = float(fit.parameters["beta"])
    metadata["theta_0"] = theta
    calc = etas_inversion.ETASParameterCalculation(metadata)
    calc.prepare()
    calc.theta = theta
    array = etas_inversion.parameter_dict2array(theta)
    calc.pij, calc.target_events, calc.source_events, calc.n_hat, calc.i_hat = (
        calc.expectation_step(array, calc.m_ref - calc.delta_m / 2.0)
    )
    return calc


def _theta_of(fit: FitResult) -> dict:
    theta = {k: float(fit.parameters[k]) for k in THETA_KEYS}
    theta["log10_iota"] = None
    return theta


def test_a_fit_persists_a_finite_log_likelihood(small_fit: FitResult) -> None:
    assert small_fit.log_likelihood is not None
    assert math.isfinite(small_fit.log_likelihood)
    terms = small_fit.diagnostics["log_likelihood_terms"]
    assert terms["n_targets"] > 0
    assert terms["n_sources"] >= terms["n_targets"]
    assert terms["background_integral"] > 0.0
    assert terms["triggering_integral"] >= 0.0
    assert small_fit.diagnostics["log_likelihood_note"].startswith("space-time ETAS log-likelihood")


def test_terms_sum_to_the_total(small_fit: FitResult) -> None:
    t = small_fit.diagnostics["log_likelihood_terms"]
    assert t["observed_term"] - t["background_integral"] - t[
        "triggering_integral"
    ] == pytest.approx(small_fit.log_likelihood)


def test_the_integral_term_equals_the_weighted_target_count_at_the_em_fixed_point(
    small_fit: FitResult,
) -> None:
    """A property of the ETAS EM optimum, and the sharpest available check of the integral term.

    At convergence ``mu`` is ``n_hat / (area * T)`` and the productivity parameters satisfy the
    aftershock-term stationarity, which together make the integral of the fitted intensity over
    the primary window equal the (completeness-weighted) number of targets in it. An error in the
    area, the window length, the ``expected_aftershocks`` limits or the completeness factors would
    break this identity; a wrong sign or a missing term would break it badly.
    """
    t = small_fit.diagnostics["log_likelihood_terms"]
    total_integral = t["background_integral"] + t["triggering_integral"]
    assert total_integral == pytest.approx(t["n_targets"], rel=1e-3)


def test_the_intensity_matches_the_packages_own_background_probability(
    small_fit: FitResult, fixture_catalog: Catalog, region: Region
) -> None:
    """``lambda_i`` is rebuilt from ``gij``; the package derives ``P_background = mu / lambda_i``.

    The two paths through the expectation step must agree exactly, which is what makes the
    observed term the likelihood of the intensity the package actually used.
    """
    model = MizrahiETAS(auxiliary_years=0.5)
    theta = _theta_of(small_fit)
    calc = _calc_at(model, small_fit, region, fixture_catalog, theta)
    mu = 10.0 ** theta["log10_mu"]
    rebuilt = mu + (calc.pij["gij"] * calc.pij["xi_plus_1"]).groupby(
        level="target_id"
    ).sum().reindex(calc.target_events.index).fillna(0.0).to_numpy(dtype=np.float64)
    from_package = (mu / calc.target_events["P_background"]).to_numpy(dtype=np.float64)
    assert np.allclose(rebuilt, from_package, rtol=1e-12, atol=0.0)


@pytest.mark.parametrize("key", ["log10_mu", "a", "log10_c"])
def test_the_fitted_parameters_are_a_local_maximum_of_this_likelihood(
    small_fit: FitResult, fixture_catalog: Catalog, region: Region, key: str
) -> None:
    """Perturbing a converged parameter in either direction must lower the number.

    This is what distinguishes the observed-data log-likelihood from an arbitrary sum of the same
    pieces: the EM maximises it, so the fitted theta sits at a maximum along every coordinate.
    """
    model = MizrahiETAS(auxiliary_years=0.5)
    theta = _theta_of(small_fit)
    at_fit = point_process_log_likelihood(
        _calc_at(model, small_fit, region, fixture_catalog, theta)
    )
    for step in (-0.05, 0.05):
        moved = dict(theta)
        moved[key] = theta[key] + step
        away = point_process_log_likelihood(
            _calc_at(model, small_fit, region, fixture_catalog, moved)
        )
        assert away.total < at_fit.total, f"{key} {step:+}: {away.total} !< {at_fit.total}"


def test_recomputing_a_stored_fit_reproduces_the_persisted_value(
    small_fit: FitResult, fixture_catalog: Catalog, region: Region
) -> None:
    model = MizrahiETAS(auxiliary_years=0.5)
    model.load_fit(small_fit, region)
    again = model.log_likelihood(fixture_catalog)
    assert isinstance(again, LogLikelihood)
    assert again.total == pytest.approx(small_fit.log_likelihood)
    assert again.n_targets == small_fit.diagnostics["log_likelihood_terms"]["n_targets"]


def test_recomputing_refuses_a_catalogue_that_is_not_the_training_slice(
    small_fit: FitResult, fixture_catalog: Catalog, region: Region
) -> None:
    """The number would silently describe a different model, so it is refused, not approximated."""
    model = MizrahiETAS(auxiliary_years=0.5)
    model.load_fit(small_fit, region)
    kept = tuple(e for e in fixture_catalog.events if e.mw is None or e.mw < 4.0)
    trimmed = fixture_catalog.model_copy(update={"events": kept})
    with pytest.raises(ValueError, match="does not reproduce the fit's training slice"):
        model.log_likelihood(trimmed)


def test_recomputing_needs_a_loaded_fit(fixture_catalog: Catalog) -> None:
    with pytest.raises(RuntimeError, match="no fit loaded"):
        MizrahiETAS().log_likelihood(fixture_catalog)


def test_the_committed_fit_carries_the_likelihood(committed_fit: FitResult) -> None:
    """Regenerated by ``make_fit_fixture``; the persisted value must not drift back to null."""
    assert committed_fit.log_likelihood is not None
    terms = committed_fit.diagnostics["log_likelihood_terms"]
    assert terms["background_integral"] + terms["triggering_integral"] == pytest.approx(
        terms["n_targets"], rel=1e-3
    )
