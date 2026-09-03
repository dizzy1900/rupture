"""Slow, offline: refit the fixture end to end and check the committed fit reproduces."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS, load_fit
from rupture.cli import app
from rupture.domain import FitResult
from rupture.pipelines import io
from tests.fixtures.forecasting.loader import FIXTURE_DIR, fixture_region, load_fixture_catalog
from tests.fixtures.forecasting.make_fit_fixture import AUXILIARY_YEARS, FIT_CUTOFF, MC

pytestmark = pytest.mark.integration


def test_refit_reproduces_the_committed_fit() -> None:
    committed = FitResult.model_validate_json(
        (FIXTURE_DIR / "fit-2019-07-01" / "fit_result.json").read_text(encoding="utf-8")
    )
    fit = MizrahiETAS(auxiliary_years=AUXILIARY_YEARS).fit(
        load_fixture_catalog(), fixture_region(), FIT_CUTOFF, mc=MC
    )
    assert fit.parameter_snapshot_hash == committed.parameter_snapshot_hash
    assert fit.training_catalog_hash == committed.training_catalog_hash


def test_cli_fit_writes_baselines(tmp_path: Path) -> None:
    catalog, region = load_fixture_catalog(), fixture_region()
    data = tmp_path / "data"
    (data / "regions" / region.id).mkdir(parents=True)
    (data / "regions" / region.id / io.REGION_FILE).write_text(
        json.dumps(region.to_geojson()), encoding="utf-8"
    )
    io.save_catalog(catalog, data / "catalogs" / region.id)
    res = CliRunner().invoke(
        app,
        [
            "forecast",
            "fit",
            "--region",
            region.id,
            "--cutoff",
            FIT_CUTOFF.isoformat(),
            "--mc",
            str(MC),
            "--auxiliary-years",
            str(AUXILIARY_YEARS),
            "--data-dir",
            str(data),
            "--baselines",
            str(tmp_path / "baselines"),
        ],
    )
    assert res.exit_code == 0, res.output
    fit = load_fit(tmp_path / "baselines", region.id)
    assert fit.converged is True
    assert fit.n_events == 214
