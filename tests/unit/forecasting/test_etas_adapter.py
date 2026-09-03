"""The ETAS adapter: leakage refusals, issuance without refit, determinism, fit bookkeeping."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.forecasting.etas_mizrahi import (
    PARAMETER_KEYS,
    MizrahiETAS,
    archive_dir,
    cell_areas_km2,
    gr_bin_probabilities,
    load_fit,
    save_fit,
)
from rupture.adapters.forecasting.grid import build_lattice
from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, FitResult, ForecastGrid, Region, snapshot_hash
from rupture.ports import ForecastModel
from tests.unit.conftest import make_event
from tests.unit.forecasting.conftest import FIT_CUTOFF, HORIZON, RIDGECREST_M64


def test_adapter_satisfies_the_port(model: MizrahiETAS) -> None:
    assert isinstance(model, ForecastModel)
    assert model.model_id == "etas-mizrahi"
    assert model.model_version.startswith("etas-")
    assert "+097f08b" in model.model_version


def test_committed_fit_is_consistent(
    committed_fit: FitResult, fit_provenance: dict[str, object]
) -> None:
    assert set(PARAMETER_KEYS) <= set(committed_fit.parameters)
    assert snapshot_hash(committed_fit.parameters) == committed_fit.parameter_snapshot_hash
    assert fit_provenance["parameter_snapshot_hash"] == committed_fit.parameter_snapshot_hash
    assert fit_provenance["training_catalog_hash"] == committed_fit.training_catalog_hash
    assert committed_fit.converged is True
    assert committed_fit.log_likelihood is None, "the package does not expose it; documented"
    latest = datetime.fromisoformat(committed_fit.diagnostics["training_max_origin_time"])
    assert latest < committed_fit.fit_cutoff


def test_committed_fit_training_hash_matches_fixture_slice(
    committed_fit: FitResult, fixture_catalog: Catalog, region: Region
) -> None:
    training = MizrahiETAS.training_slice(
        fixture_catalog, region, committed_fit.fit_cutoff, committed_fit.mc
    )
    assert training.event_hash() == committed_fit.training_catalog_hash
    assert len(training) == committed_fit.n_events


def test_issuance_sources_end_strictly_before_issue_time(
    model: MizrahiETAS, fixture_catalog: Catalog, region: Region
) -> None:
    # Issue in the middle of the Ridgecrest sequence: the M6.4 is history, later events are not.
    issue = datetime(2019, 7, 6, tzinfo=UTC)
    history = fixture_catalog.earthquakes().before(issue).at_least(3.0)
    assert history.max_origin_time() is not None
    assert history.max_origin_time() < issue
    assert any(e.origin_time == RIDGECREST_M64 for e in history.events)
    state = model.issuance_state(history, issue)
    latest_source = state.sources["time"].max().to_pydatetime().replace(tzinfo=UTC)
    assert latest_source < issue
    assert not (state.sources["time"] >= np.datetime64(issue.replace(tzinfo=None))).any()
    assert len(state.sources) == len(history), "every history event inside the region is a source"
    assert state.calc.theta["log10_mu"] == pytest.approx(model.parameter_snapshot()["log10_mu"])
    assert 0.0 < state.background_weights.max() <= 1.0 + 1e-9
    assert (state.background_weights >= 0.0).all()


def test_forecast_refuses_history_at_or_after_issue_time(
    model: MizrahiETAS, fixture_catalog: Catalog
) -> None:
    leaky = fixture_catalog.earthquakes().at_least(3.0)  # includes Ridgecrest, after the cutoff
    with pytest.raises(LeakageError, match="origin_time >="):
        model.forecast(leaky, FIT_CUTOFF, HORIZON, n_simulations=1)


def test_forecast_refuses_issue_before_fit_cutoff(
    model: MizrahiETAS, fixture_catalog: Catalog
) -> None:
    early = FIT_CUTOFF - timedelta(days=60)
    history = fixture_catalog.earthquakes().before(early).at_least(3.0)
    with pytest.raises(LeakageError, match="precedes the fit cutoff"):
        model.forecast(history, early, HORIZON, n_simulations=1)


def test_forecast_refuses_unfiltered_history(model: MizrahiETAS, fixture_catalog: Catalog) -> None:
    clean = fixture_catalog.earthquakes().before(FIT_CUTOFF).at_least(3.0)
    small = make_event(
        clean.events[0].provenance, eid="m2.5", when=FIT_CUTOFF - timedelta(days=2), mw=2.5
    )
    below_mc = clean.model_copy(update={"events": (*clean.events, small)})
    with pytest.raises(ValueError, match="below mc"):
        model.forecast(below_mc, FIT_CUTOFF, HORIZON, n_simulations=1)
    landslide = make_event(
        fixture_catalog.events[0].provenance,
        eid="ls",
        when=FIT_CUTOFF - timedelta(days=1),
        mw=None,
        event_type="landslide",  # type: ignore[arg-type]
    )
    mixed = fixture_catalog.model_copy(update={"events": (*fixture_catalog.events[:5], landslide)})
    with pytest.raises(ValueError, match="earthquakes only"):
        model.forecast(mixed.before(FIT_CUTOFF), FIT_CUTOFF, HORIZON, n_simulations=1)


def test_forecast_is_deterministic_given_a_seed(
    model: MizrahiETAS, fixture_catalog: Catalog
) -> None:
    history = fixture_catalog.earthquakes().before(FIT_CUTOFF).at_least(3.0)
    a = model.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=5, seed=11)
    b = model.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=5, seed=11)
    c = model.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=5, seed=12)
    assert a.expected_counts == b.expected_counts
    assert a.expected_counts != c.expected_counts


def test_grid_is_well_formed(
    ridgecrest_grid: ForecastGrid, committed_fit: FitResult, region: Region
) -> None:
    g = ridgecrest_grid
    assert g.id == "etas-mizrahi-california-fixture-20190701T000000Z-30d"
    assert g.parameter_snapshot_hash == committed_fit.parameter_snapshot_hash
    assert g.training_catalog_hash == committed_fit.training_catalog_hash
    assert g.fit_cutoff == committed_fit.fit_cutoff
    assert g.n_simulations == 10
    counts = g.counts()
    assert counts.shape == (80 * 55, 51)
    assert np.all(np.isfinite(counts))
    assert np.all(counts >= 0)
    assert 0.1 < g.total_expected() < 20.0, "a few M>=3.95 events per 30 days in the box"
    # analytic magnitude law: every cell shares the same bin proportions
    row_tot = counts.sum(axis=1)
    busiest = np.argmax(row_tot)
    beta = committed_fit.parameters["beta"]
    ratio = counts[busiest, 1] / counts[busiest, 0]
    assert ratio == pytest.approx(math.exp(-beta * 0.1), rel=1e-6)
    assert region.magnitude_bin_edges() == g.magnitude_bin_edges


def test_gr_bin_probabilities_sum_to_exceedance_probability() -> None:
    edges = tuple(round(3.95 + 0.1 * k, 6) for k in range(51))
    beta = 2.3
    pmf = gr_bin_probabilities(beta, 2.95, edges, None)
    assert pmf.sum() == pytest.approx(math.exp(-beta * (3.95 - 2.95)))
    truncated = gr_bin_probabilities(beta, 2.95, edges, 6.05)
    assert truncated[-1] == 0.0
    assert truncated.sum() < pmf.sum()


def test_cell_areas_agree_with_the_package_area(region: Region, committed_fit: FitResult) -> None:
    total = cell_areas_km2(build_lattice(region)).sum()
    assert total == pytest.approx(committed_fit.diagnostics["area_km2"], rel=0.02)


def test_fit_runs_on_a_small_real_slice(fixture_catalog: Catalog, region: Region) -> None:
    """A real EM fit (M>=3.5, ~4 s) exercising the fit path offline; the gate does the full one."""
    fit = MizrahiETAS(auxiliary_years=0.5).fit(fixture_catalog, region, FIT_CUTOFF, mc=3.5)
    assert fit.converged is True
    assert fit.n_events == 61
    assert fit.mc == 3.5
    assert fit.diagnostics["mc_source"] == "explicit mc kwarg"
    assert fit.diagnostics["iterations"] >= 1
    assert datetime.fromisoformat(fit.diagnostics["training_max_origin_time"]) < FIT_CUTOFF
    slice_ = MizrahiETAS.training_slice(fixture_catalog, region, FIT_CUTOFF, 3.5)
    assert fit.training_catalog_hash == slice_.event_hash()
    assert len(slice_) <= len(fixture_catalog.earthquakes().before(FIT_CUTOFF).at_least(3.5))
    assert snapshot_hash(fit.parameters) == fit.parameter_snapshot_hash
    assert set(PARAMETER_KEYS) == set(fit.parameters)
    assert isinstance(fit.diagnostics["at_bound"], list)
    assert fit.diagnostics["branching_ratio"] is None or fit.diagnostics["branching_ratio"] > 0


def test_em_iteration_cap_yields_a_persisted_non_converged_fit(
    fixture_catalog: Catalog, region: Region, tmp_path: Path
) -> None:
    fit = MizrahiETAS(auxiliary_years=0.5, max_iterations=2).fit(
        fixture_catalog, region, FIT_CUTOFF, mc=3.5
    )
    assert fit.converged is False
    assert fit.diagnostics["iterations"] == 2
    assert "iteration cap 2 hit" in fit.diagnostics["converged_reason"]
    assert fit.notes is not None
    assert "not converged" in fit.notes
    save_fit(fit, tmp_path)  # persisted with converged=False, never silently dropped
    assert load_fit(tmp_path, region.id).converged is False
    m = MizrahiETAS()
    m.load_fit(fit, region)
    history = fixture_catalog.earthquakes().before(FIT_CUTOFF).at_least(3.5)
    with pytest.raises(RuntimeError, match="did not converge"):
        m.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=1)


def test_fit_requires_a_magnitude_of_completeness(fixture_catalog: Catalog, region: Region) -> None:
    with pytest.raises(ValueError, match="no magnitude of completeness"):
        MizrahiETAS(auxiliary_years=0.5).fit(fixture_catalog, region, FIT_CUTOFF)


def test_fit_refuses_an_auxiliary_window_that_eats_the_data(
    fixture_catalog: Catalog, region: Region
) -> None:
    with pytest.raises(ValueError, match="no primary window"):
        MizrahiETAS(auxiliary_years=5.0).fit(fixture_catalog, region, FIT_CUTOFF, mc=3.0)


def test_save_and_load_fit_round_trip(committed_fit: FitResult, tmp_path: Path) -> None:
    out = save_fit(committed_fit, tmp_path)
    files = {"fit_result.json", "parameters.json", "diagnostics.json"}
    # the three files, plus the per-cutoff archive that keeps a refit from destroying this fit
    assert {p.name for p in out.iterdir()} == files | {"fits"}
    archive = archive_dir(tmp_path, committed_fit.region_id, committed_fit.fit_cutoff)
    assert {p.name for p in archive.iterdir()} == files
    assert load_fit(tmp_path, committed_fit.region_id) == committed_fit
    with pytest.raises(FileNotFoundError):
        load_fit(tmp_path, "nowhere")


def test_load_fit_checks_identity(committed_fit: FitResult, region: Region) -> None:
    other = region.model_copy(update={"id": "elsewhere"})
    with pytest.raises(ValueError, match="region"):
        MizrahiETAS().load_fit(committed_fit, other)
    with pytest.raises(RuntimeError, match="no fit loaded"):
        MizrahiETAS().forecast(
            Catalog(id="x", events=(), built_at=FIT_CUTOFF, builder_version="0"),
            FIT_CUTOFF,
            HORIZON,
        )
