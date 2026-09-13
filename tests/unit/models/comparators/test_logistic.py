"""One-neuron logistic: leakage, distance monotonicity, and ForecastGrid counts."""

from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pytest
from tests.unit.models.comparators.conftest import CUTOFF, HORIZON, ISSUE, M_MAIN, MC

from rupture.adapters.forecasting.grid import build_lattice
from rupture.adapters.forecasting.leakage import LeakageError, assert_all_before
from rupture.domain import Catalog, Region, snapshot_hash
from rupture.models.comparators._fit import log10_distance_to_anchors, mainshock_anchors
from rupture.models.comparators.citations import (
    DOI_DEVRIES_2018,
    DOI_MEADE_REPLY_2019,
    DOI_MIGNAN_BROCCARDO_2019,
)
from rupture.models.comparators.logistic import MODEL_ID, MODEL_VERSION, OneNeuronAftershockModel
from rupture.models.data.geo import Projection
from rupture.ports import ForecastModel


def test_the_model_satisfies_the_forecast_port(fitted: OneNeuronAftershockModel) -> None:
    assert isinstance(fitted, ForecastModel)
    assert fitted.model_id == MODEL_ID
    assert fitted.model_version == MODEL_VERSION
    assert not hasattr(OneNeuronAftershockModel, "auc")


def test_fit_on_the_ridgecrest_fixture_is_a_distance_logistic(
    fitted: OneNeuronAftershockModel,
) -> None:
    fit = fitted.fit_result
    assert fit is not None
    assert fit.n_events > 0
    assert fit.parameters["b"] < 0.0
    assert fit.parameters["used_slip"] == 0.0
    snapshot = fitted.parameter_snapshot()
    assert snapshot["a"] == fit.parameters["a"]
    assert snapshot["b"] == fit.parameters["b"]
    assert snapshot["distance_floor_km"] == pytest.approx(0.1)
    assert snapshot["m_main"] == M_MAIN
    assert snapshot["citation_devries_doi"] == DOI_DEVRIES_2018
    assert snapshot["citation_mignan_doi"] == DOI_MIGNAN_BROCCARDO_2019
    assert snapshot["citation_meade_reply_doi"] == DOI_MEADE_REPLY_2019
    notes = fit.notes or ""
    assert "single-feature distance logistic" in notes
    assert "expected COUNTS" in notes
    assert "Meade" in notes
    assert "`rebutted`" in notes
    assert "`contested`" in notes


def test_an_event_at_the_cutoff_does_not_move_the_snapshot(
    fixture_catalog: Catalog, ridgecrest_region: Region, training: Catalog
) -> None:
    """Mutate a copy with a real event moved to the cutoff; the snapshot hash must not change."""
    clean = OneNeuronAftershockModel(m_main=M_MAIN, mc=MC)
    clean.fit(fixture_catalog, ridgecrest_region, CUTOFF)
    late_source = training.events[-1]
    late = late_source.model_copy(
        update={"id": f"{late_source.id}-at-cutoff", "origin_time": CUTOFF}
    )
    dirty = fixture_catalog.model_copy(update={"events": (*fixture_catalog.events, late)})
    leaked = OneNeuronAftershockModel(m_main=M_MAIN, mc=MC)
    leaked.fit(dirty, ridgecrest_region, CUTOFF)
    assert snapshot_hash(clean.parameter_snapshot()) == snapshot_hash(leaked.parameter_snapshot())
    assert clean.fit_result is not None
    assert leaked.fit_result is not None
    assert clean.fit_result.parameter_snapshot_hash == leaked.fit_result.parameter_snapshot_hash
    assert late.origin_time >= CUTOFF


def test_fit_refuses_to_train_on_an_unfiltered_future_if_asserted_directly(
    fixture_catalog: Catalog,
) -> None:
    with pytest.raises(LeakageError, match="origin_time"):
        assert_all_before(fixture_catalog, CUTOFF, what="unfiltered catalog")


def test_cells_nearer_the_mainshock_have_higher_expected_counts(
    fitted: OneNeuronAftershockModel, training: Catalog, ridgecrest_region: Region
) -> None:
    grid = fitted.forecast(training, ISSUE, HORIZON)
    totals = grid.counts().sum(axis=1)
    lattice = build_lattice(ridgecrest_region)
    anchors = mainshock_anchors(training, m_main=M_MAIN)
    log_d = log10_distance_to_anchors(
        lattice, Projection.for_region(ridgecrest_region), anchors, distance_floor_km=0.1
    )
    order = np.argsort(log_d)
    # A 1-D transect in distance: nearer cells must not have lower expected counts, allowing
    # ties from equal distances. The fitted b is negative, so this is the logistic's claim.
    ordered = totals[order]
    diffs = np.diff(ordered)
    assert fitted.fit_result is not None
    assert fitted.fit_result.parameters["b"] < 0.0
    assert float(np.max(diffs)) <= 1e-9


def test_forecast_grid_is_finite_nonnegative_counts(
    fitted: OneNeuronAftershockModel, training: Catalog
) -> None:
    grid = fitted.forecast(training, ISSUE, HORIZON)
    counts = grid.counts()
    assert np.all(np.isfinite(counts))
    assert np.all(counts >= 0.0)
    assert grid.total_expected() > 0.0
    notes = grid.notes or ""
    assert "expected COUNTS" in notes
    assert "single-feature distance logistic" in notes
    fit = fitted.fit_result
    assert fit is not None
    logistic_n = fit.parameters["n_training_events"]
    # The conversion is P * productivity * (horizon / training_days); a 30-day issue
    # after a weeks-long aftershock training window must not collapse to ~0 counts.
    assert grid.total_expected() > 1.0
    assert logistic_n > 0.0


def test_forecast_refuses_history_at_or_after_issue(
    fitted: OneNeuronAftershockModel, fixture_catalog: Catalog
) -> None:
    with pytest.raises(LeakageError, match="origin_time"):
        fitted.forecast(fixture_catalog, ISSUE, HORIZON)


def test_issue_before_fit_cutoff_is_refused(
    fitted: OneNeuronAftershockModel, training: Catalog
) -> None:
    too_early = CUTOFF - timedelta(days=1)
    with pytest.raises(LeakageError, match="precedes the fit cutoff"):
        fitted.forecast(training, too_early, HORIZON)


def test_parameter_snapshot_hash_matches_numeric_parameters(
    fitted: OneNeuronAftershockModel,
) -> None:
    fit = fitted.fit_result
    assert fit is not None
    assert snapshot_hash(fit.parameters) == fit.parameter_snapshot_hash
    for value in fit.parameters.values():
        assert isinstance(value, float)
        assert math.isfinite(value)
