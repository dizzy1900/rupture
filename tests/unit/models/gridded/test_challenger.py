"""The gridded challenger's contract: lattice, forecast grid, determinism and persistence."""

from __future__ import annotations

import math
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.forecasting.grid import build_lattice
from rupture.domain import Catalog, Region
from rupture.models.challengers.gridded import (
    GriddedChallenger,
    GriddedConfig,
    archive_dir,
    fit_dir,
    load_fit,
    save_fit,
)
from rupture.models.challengers.gridded import features as feat
from rupture.models.challengers.gridded._data import SEAM_SOURCE
from rupture.models.challengers.gridded.net import GriddedRateNet, weights_sha256
from rupture.ports import ForecastModel
from tests.fixtures.models.gridded import FIXTURE_CUTOFF, FIXTURE_MC, small_config

HORIZON = timedelta(days=30)


def test_model_satisfies_the_forecast_model_port(fitted: GriddedChallenger) -> None:
    assert isinstance(fitted, ForecastModel)


def test_raster_cells_are_the_etas_lattice(region: Region, raster: feat.Raster) -> None:
    lattice = build_lattice(region)
    assert raster.lattice.origins == lattice.origins
    assert raster.n_cells == lattice.n_cells
    values = np.arange(raster.n_cells, dtype=np.float64)
    assert np.array_equal(raster.to_cells(raster.from_cells(values)), values)


def test_forecast_grid_matches_the_region_contract(
    fitted: GriddedChallenger, catalog: Catalog, region: Region
) -> None:
    grid = fitted.forecast(catalog.before(FIXTURE_CUTOFF), FIXTURE_CUTOFF, HORIZON)
    assert grid.cell_origins == build_lattice(region).origins
    assert grid.magnitude_bin_edges == region.magnitude_bin_edges()
    assert grid.cell_size_deg == region.cell_size_deg
    assert grid.magnitude_bin_width == region.magnitude_bin_width
    counts = grid.counts()
    assert counts.shape == (len(grid.cell_origins), len(grid.magnitude_bin_edges))
    assert np.all(np.isfinite(counts))
    assert np.all(counts >= 0.0)
    assert grid.total_expected() > 0.0


def test_magnitude_distribution_is_gutenberg_richter(
    fitted: GriddedChallenger, catalog: Catalog
) -> None:
    """Adjacent bins fall by 10^(-b * bin width), because the pmf is analytic, not learned."""
    grid = fitted.forecast(catalog.before(FIXTURE_CUTOFF), FIXTURE_CUTOFF, HORIZON)
    per_bin = grid.counts().sum(axis=0)
    fit = fitted.fit_result
    assert fit is not None
    expected_ratio = 10.0 ** (-fit.parameters["b_value"] * grid.magnitude_bin_width)
    ratios = per_bin[1:-1] / per_bin[:-2]
    assert np.allclose(ratios, expected_ratio, rtol=1e-6)


def test_expected_counts_scale_linearly_with_the_horizon(
    fitted: GriddedChallenger, catalog: Catalog
) -> None:
    history = catalog.before(FIXTURE_CUTOFF)
    one = fitted.forecast(history, FIXTURE_CUTOFF, HORIZON)
    two = fitted.forecast(history, FIXTURE_CUTOFF, 2 * HORIZON)
    assert two.total_expected() == pytest.approx(2.0 * one.total_expected(), rel=1e-9)


def test_fit_is_deterministic_under_a_fixed_seed(catalog: Catalog, region: Region) -> None:
    first = GriddedChallenger(small_config(), faults_path=None)
    second = GriddedChallenger(small_config(), faults_path=None)
    a = first.fit(catalog, region, FIXTURE_CUTOFF, mc=FIXTURE_MC)
    b = second.fit(catalog, region, FIXTURE_CUTOFF, mc=FIXTURE_MC)
    assert a.diagnostics["weights_sha256"] == b.diagnostics["weights_sha256"]
    assert a.parameter_snapshot_hash == b.parameter_snapshot_hash
    ga = first.forecast(catalog.before(FIXTURE_CUTOFF), FIXTURE_CUTOFF, HORIZON)
    gb = second.forecast(catalog.before(FIXTURE_CUTOFF), FIXTURE_CUTOFF, HORIZON)
    assert ga.expected_counts == gb.expected_counts


def test_a_different_seed_gives_a_different_snapshot(catalog: Catalog, region: Region) -> None:
    other = GriddedChallenger(small_config(seed=7), faults_path=None)
    fit = other.fit(catalog, region, FIXTURE_CUTOFF, mc=FIXTURE_MC)
    assert fit.diagnostics["config_hash"] != small_config().hash()


def test_parameter_snapshot_hashes_the_trained_weights(fitted: GriddedChallenger) -> None:
    snapshot = fitted.parameter_snapshot()
    fit = fitted.fit_result
    assert fit is not None
    assert snapshot["weights_sha256"] == fit.diagnostics["weights_sha256"]
    assert snapshot["config_hash"] == fitted.config.hash()
    # the digest of the weights is carried into the numeric parameters the FitResult hashes
    digest = fit.diagnostics["weights_sha256"]
    assert fit.parameters["weights_digest_hi"] == float(int(digest[:12], 16))
    assert fit.parameters["weights_digest_lo"] == float(int(digest[12:24], 16))


def test_weights_hash_changes_when_a_weight_changes() -> None:
    net = GriddedRateNet(n_dynamic=3, n_static=4, hidden_channels=2)
    before = weights_sha256(net)
    with __import__("torch").no_grad():
        net.log_scale += 1.0
    assert weights_sha256(net) != before


def test_unfitted_model_refuses_to_forecast(catalog: Catalog) -> None:
    model = GriddedChallenger(small_config(), faults_path=None)
    assert model.parameter_snapshot() == {}
    with pytest.raises(RuntimeError, match="no fit loaded"):
        model.forecast(catalog.before(FIXTURE_CUTOFF), FIXTURE_CUTOFF, HORIZON)


def test_save_and_load_round_trip(
    fitted: GriddedChallenger, catalog: Catalog, tmp_path: Path
) -> None:
    out = save_fit(fitted, tmp_path)
    assert out == fit_dir(tmp_path, "gridded-test-box")
    assert (archive_dir(tmp_path, "gridded-test-box", FIXTURE_CUTOFF) / "weights.pt").exists()
    reloaded = load_fit(tmp_path, "gridded-test-box")
    history = catalog.before(FIXTURE_CUTOFF)
    assert (
        reloaded.forecast(history, FIXTURE_CUTOFF, HORIZON).expected_counts
        == fitted.forecast(history, FIXTURE_CUTOFF, HORIZON).expected_counts
    )


def test_non_canonical_save_archives_without_replacing_the_declared_baseline(
    fitted: GriddedChallenger, catalog: Catalog, region: Region, tmp_path: Path
) -> None:
    save_fit(fitted, tmp_path)
    declared = (fit_dir(tmp_path, region.id) / "parameters.json").read_text(encoding="utf-8")

    refit = GriddedChallenger(small_config(seed=99), faults_path=None)
    refit.fit(catalog, region, FIXTURE_CUTOFF - timedelta(days=90), mc=FIXTURE_MC)
    save_fit(refit, tmp_path, canonical=False)

    assert (fit_dir(tmp_path, region.id) / "parameters.json").read_text(
        encoding="utf-8"
    ) == declared
    boundary = archive_dir(tmp_path, region.id, FIXTURE_CUTOFF - timedelta(days=90))
    assert (boundary / "fit_result.json").exists()


def test_load_fit_reports_a_missing_fit(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="no persisted gridded fit"):
        load_fit(tmp_path, "gridded-test-box")


def test_diagnostics_record_the_data_seam_and_the_covariates(fitted: GriddedChallenger) -> None:
    fit = fitted.fit_result
    assert fit is not None
    assert fit.diagnostics["seam_source"] == SEAM_SOURCE
    assert fit.diagnostics["dynamic_channels"] == list(feat.DYNAMIC_CHANNELS)
    assert fit.diagnostics["static_channels"] == list(feat.STATIC_CHANNELS)
    assert fit.diagnostics["train_windows"] > 0
    assert fit.diagnostics["validation_windows"] > 0
    assert math.isfinite(fit.diagnostics["training"]["best_validation_nll"])


def test_missing_fault_data_is_recorded_not_invented(fitted: GriddedChallenger) -> None:
    """With no GAF file the channel is zeros and the fit says so; it never guesses a density."""
    fit = fitted.fit_result
    assert fit is not None
    covariates = fit.diagnostics["static_covariates"]
    assert covariates["fault_density_available"] is False
    assert covariates["faults"]["n_features_in_bbox"] == 0
    assert "unavailable" in covariates["faults"]["note"]


def test_fault_density_reads_the_committed_gem_fixture(tmp_path: Path) -> None:
    """The committed GAF subset covers the Nepal bbox, so a Nepal box gets a real density."""
    from rupture.domain import Region as R
    from rupture.domain import TectonicSetting

    nepal_box = R(
        id="gaf-fixture-box",
        name="GAF fixture box (tests only)",
        polygon=((80.5, 27.0), (88.5, 27.0), (88.5, 30.0), (80.5, 30.0)),
        depth_max_km=70.0,
        tectonic_setting=TectonicSetting.CONTINENTAL_COLLISION,
        cell_size_deg=0.2,
        target_min_magnitude=4.7,
    )
    raster = feat.build_raster(nepal_box)
    density, provenance = feat.fault_density_km(nepal_box, raster, faults_path=None)
    assert provenance["kind"] == "fixture-geojson"
    assert provenance["n_features_in_bbox"] > 0
    assert density.sum() > 0.0


def test_config_hash_is_stable_and_sensitive() -> None:
    assert GriddedConfig().hash() == GriddedConfig().hash()
    assert GriddedConfig().hash() != GriddedConfig(hidden_channels=32).hash()
