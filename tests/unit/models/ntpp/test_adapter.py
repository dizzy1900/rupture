"""Forecasting, persistence and the leakage guards, from the committed fit. No training here."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rupture.adapters.forecasting.grid import build_lattice
from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, FitResult, Region, snapshot_hash
from rupture.models.challengers.ntpp import NeuralTPPForecaster
from rupture.models.challengers.ntpp.adapter import (
    MODEL_ID,
    archive_dir,
    digest_to_floats,
    fit_dir,
    floats_to_digest,
    load_saved_fit,
    save_fit,
)
from tests.fixtures.models.loader import (
    FIT_CUTOFF,
    MC,
    fit_provenance,
    load_ntpp_fit,
    load_ntpp_weights,
    loaded_model,
)

HORIZON = timedelta(days=30)
FEW = 3  # simulations: enough to exercise the path, not to make a forecast worth reading


@pytest.fixture
def model() -> NeuralTPPForecaster:
    return loaded_model()


@pytest.fixture
def history(fixture_catalog: Catalog) -> Catalog:
    return fixture_catalog.earthquakes().before(FIT_CUTOFF).at_least(MC)


# ---------------------------------------------------------------------- the committed fit
def test_the_committed_fit_is_a_real_fit_of_the_real_fixture(fixture_catalog: Catalog) -> None:
    fit = load_ntpp_fit()
    provenance = fit_provenance()
    assert fit.model_id == MODEL_ID
    assert fit.fit_cutoff == FIT_CUTOFF
    assert fit.converged is True
    assert fit.n_events == provenance["n_events"]
    assert fit.training_catalog_hash == provenance["training_catalog_hash"]
    assert provenance["derived_from"].endswith(".geojson")
    latest = datetime.fromisoformat(fit.diagnostics["training_max_origin_time"])
    assert latest < FIT_CUTOFF


def test_the_snapshot_hash_covers_the_weights(model: NeuralTPPForecaster) -> None:
    fit = load_ntpp_fit()
    assert snapshot_hash(model.parameter_snapshot()) == fit.parameter_snapshot_hash
    assert floats_to_digest(fit.parameters) == model.snapshot_digest()
    assert digest_to_floats(model.snapshot_digest()) == {
        k: v for k, v in fit.parameters.items() if k.startswith("snapshot_")
    }


def test_loading_mismatched_weights_is_refused(region: Region) -> None:
    """A fit record and a weights file that disagree must not silently produce forecasts."""
    weights = load_ntpp_weights()
    key = next(k for k, v in weights.items() if v)
    tampered = {**weights, key: [v + 1.0 for v in weights[key]]}
    model = NeuralTPPForecaster()
    with pytest.raises(ValueError, match="do not reproduce the fit's parameter snapshot"):
        model.load_fit(load_ntpp_fit(), region, tampered)


def test_loading_a_fit_for_another_region_is_refused(region: Region) -> None:
    other = region.model_copy(update={"id": "somewhere-else"})
    with pytest.raises(ValueError, match="is for region"):
        NeuralTPPForecaster().load_fit(load_ntpp_fit(), other, load_ntpp_weights())


# ---------------------------------------------------------------------- forecasting
def test_the_grid_matches_the_protocol_lattice_and_bins(
    model: NeuralTPPForecaster, history: Catalog, region: Region
) -> None:
    grid = model.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=FEW, seed=1)
    lattice = build_lattice(region)
    assert grid.cell_origins == lattice.origins
    assert grid.magnitude_bin_edges == region.magnitude_bin_edges()
    assert grid.cell_size_deg == region.cell_size_deg
    assert grid.model_id == MODEL_ID
    assert grid.parameter_snapshot_hash == load_ntpp_fit().parameter_snapshot_hash
    assert grid.total_expected() > 0.0
    assert grid.id.startswith(f"{MODEL_ID}-{region.id}-")


def test_every_cell_has_a_positive_rate_so_the_likelihood_is_finite(
    model: NeuralTPPForecaster, history: Catalog
) -> None:
    """The analytic background is what guarantees this; a sampled one leaves zero-rate cells and
    an observed event in one sends the log-likelihood to minus infinity."""
    grid = model.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=FEW, seed=1)
    assert min(row[0] for row in grid.expected_counts) > 0.0


def test_a_fixed_seed_reproduces_the_grid(model: NeuralTPPForecaster, history: Catalog) -> None:
    a = model.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=FEW, seed=42)
    b = model.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=FEW, seed=42)
    c = model.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=FEW, seed=43)
    assert a.expected_counts == b.expected_counts
    assert a.expected_counts != c.expected_counts


def test_a_history_event_at_the_issue_time_is_refused(
    model: NeuralTPPForecaster, history: Catalog
) -> None:
    late = history.events[-1].model_copy(update={"id": "late", "origin_time": FIT_CUTOFF})
    leaky = history.model_copy(update={"events": (*history.events, late)})
    with pytest.raises(LeakageError, match="origin_time >="):
        model.forecast(leaky, FIT_CUTOFF, HORIZON, n_simulations=FEW, seed=1)


def test_issuing_before_the_fit_cutoff_is_refused(
    model: NeuralTPPForecaster, fixture_catalog: Catalog
) -> None:
    earlier = FIT_CUTOFF - timedelta(days=10)
    history = fixture_catalog.earthquakes().before(earlier).at_least(MC)
    with pytest.raises(LeakageError, match="precedes the fit cutoff"):
        model.forecast(history, earlier, HORIZON, n_simulations=FEW, seed=1)


def test_a_history_with_the_wrong_contents_is_refused_not_filtered(
    model: NeuralTPPForecaster, fixture_catalog: Catalog
) -> None:
    unfiltered = fixture_catalog.earthquakes().before(FIT_CUTOFF)  # includes events below Mc? no
    below = unfiltered.events[0].model_copy(update={"id": "small", "mw": MC - 0.5})
    with pytest.raises(ValueError, match="below mc"):
        model.forecast(
            unfiltered.model_copy(update={"events": (below, *unfiltered.events)}),
            FIT_CUTOFF,
            HORIZON,
            n_simulations=FEW,
            seed=1,
        )


def test_a_non_positive_horizon_is_refused(model: NeuralTPPForecaster, history: Catalog) -> None:
    with pytest.raises(ValueError, match="horizon must be positive"):
        model.forecast(history, FIT_CUTOFF, timedelta(0), n_simulations=FEW, seed=1)


def test_an_unconverged_fit_is_never_used(region: Region) -> None:
    model = NeuralTPPForecaster()
    model.load_fit(load_ntpp_fit(), region, load_ntpp_weights())
    model._fit = model._fit.model_copy(update={"converged": False})
    with pytest.raises(RuntimeError, match="did not converge"):
        model.forecast(
            Catalog(id="x", events=(), built_at=FIT_CUTOFF, builder_version="t"),
            FIT_CUTOFF,
            HORIZON,
        )


def test_a_longer_horizon_forecasts_more_events(
    model: NeuralTPPForecaster, history: Catalog
) -> None:
    short = model.forecast(history, FIT_CUTOFF, timedelta(days=7), n_simulations=FEW, seed=5)
    long = model.forecast(history, FIT_CUTOFF, timedelta(days=30), n_simulations=FEW, seed=5)
    assert long.total_expected() > short.total_expected()


# ---------------------------------------------------------------------- persistence
def test_save_and_load_round_trip(tmp_path: Path, model: NeuralTPPForecaster) -> None:
    fit = load_ntpp_fit()
    out = save_fit(fit, model.state_dict_json(), tmp_path)
    assert out == fit_dir(tmp_path, fit.region_id)
    assert archive_dir(tmp_path, fit.region_id, fit.fit_cutoff).joinpath("weights.json").exists()
    restored, weights = load_saved_fit(tmp_path, fit.region_id)
    assert restored.parameter_snapshot_hash == fit.parameter_snapshot_hash
    assert weights == model.state_dict_json()


def test_a_refit_is_archived_but_does_not_clobber_the_declared_baseline(
    tmp_path: Path, model: NeuralTPPForecaster
) -> None:
    """Same rule as the ETAS adapter: a schedule refit must not replace the published fit."""
    fit = load_ntpp_fit()
    save_fit(fit, model.state_dict_json(), tmp_path)
    canonical = json.loads((fit_dir(tmp_path, fit.region_id) / "fit_result.json").read_text())
    later = fit.model_copy(update={"fit_cutoff": FIT_CUTOFF + timedelta(days=180)})
    save_fit(later, model.state_dict_json(), tmp_path, canonical=False)
    assert (
        json.loads((fit_dir(tmp_path, fit.region_id) / "fit_result.json").read_text()) == canonical
    )
    assert (
        archive_dir(tmp_path, later.region_id, later.fit_cutoff)
        .joinpath("fit_result.json")
        .exists()
    )


def test_weights_are_plain_json_not_a_pickle(tmp_path: Path, model: NeuralTPPForecaster) -> None:
    save_fit(load_ntpp_fit(), model.state_dict_json(), tmp_path)
    raw = json.loads((fit_dir(tmp_path, load_ntpp_fit().region_id) / "weights.json").read_text())
    assert all(isinstance(v, list) for v in raw.values())


def test_load_saved_fit_says_what_to_run_when_nothing_is_persisted(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="challenger ntpp fit"):
        load_saved_fit(tmp_path, "california-fixture")


def test_digest_floats_round_trip() -> None:
    digest = "0123456789abcdef" * 4
    assert floats_to_digest(digest_to_floats(digest)) == digest
    with pytest.raises(ValueError, match="64-character hex digest"):
        digest_to_floats("too-short")


def test_a_fit_result_hashes_its_own_parameters() -> None:
    """The domain validator would reject a doctored fit record; check the fixture satisfies it."""
    fit = load_ntpp_fit()
    assert FitResult.model_validate(fit.model_dump(mode="json")).parameters == fit.parameters
    with pytest.raises(ValueError, match="parameter_snapshot_hash does not match"):
        FitResult.model_validate(
            {**fit.model_dump(mode="json"), "parameters": {**fit.parameters, "log_mu": 0.5}}
        )


def test_utc_cutoff_is_timezone_aware() -> None:
    assert FIT_CUTOFF.tzinfo is UTC
