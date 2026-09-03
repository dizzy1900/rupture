"""Shared fixtures: the real ComCat slice, the test region and the committed fit of that slice."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.domain import Catalog, FitResult, ForecastGrid, Region
from tests.fixtures.forecasting.loader import FIXTURE_DIR, fixture_region, load_fixture_catalog

FIT_DIR = FIXTURE_DIR / "fit-2019-07-01"
FIT_CUTOFF = datetime(2019, 7, 1, tzinfo=UTC)
RIDGECREST_M64 = datetime(2019, 7, 4, 17, 33, 49, tzinfo=UTC)
HORIZON = timedelta(days=30)


@pytest.fixture(scope="session")
def fixture_catalog() -> Catalog:
    return load_fixture_catalog()


@pytest.fixture(scope="session")
def region() -> Region:
    return fixture_region()


@pytest.fixture(scope="session")
def committed_fit() -> FitResult:
    return FitResult.model_validate_json((FIT_DIR / "fit_result.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def fit_provenance() -> dict[str, object]:
    raw: dict[str, object] = json.loads((FIT_DIR / "provenance.json").read_text(encoding="utf-8"))
    return raw


@pytest.fixture
def model(committed_fit: FitResult, region: Region) -> MizrahiETAS:
    m = MizrahiETAS(auxiliary_years=0.5)
    m.load_fit(committed_fit, region)
    return m


@pytest.fixture(scope="session")
def ridgecrest_grid(
    committed_fit: FitResult, region: Region, fixture_catalog: Catalog
) -> ForecastGrid:
    """A real 30-day issuance at the fit cutoff (few simulations: tests, not production)."""
    m = MizrahiETAS(auxiliary_years=0.5)
    m.load_fit(committed_fit, region)
    history = fixture_catalog.earthquakes().before(FIT_CUTOFF).at_least(committed_fit.mc)
    return m.forecast(history, FIT_CUTOFF, HORIZON, n_simulations=10, seed=3)


@pytest.fixture
def baselines_with_committed_fit(tmp_path: Path, committed_fit: FitResult) -> Path:
    """A baselines/ tree holding the committed fit under etas/<region>/."""
    target = tmp_path / "baselines" / "etas" / committed_fit.region_id
    target.mkdir(parents=True)
    for name in ("fit_result.json", "parameters.json", "diagnostics.json"):
        (target / name).write_text((FIT_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path / "baselines"
