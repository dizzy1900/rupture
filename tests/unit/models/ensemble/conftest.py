"""Fixtures for the ensemble: the committed ETAS fit and a gridded fit on the same real slice.

Both components run on real data. ETAS comes from the fit committed under
``tests/fixtures/forecasting/fit-2019-07-01/`` rather than being refitted here, and every ETAS
issuance is memoised, so the suite stays fast without inventing a rate field. The gridded
component is trained for two epochs on the same catalogue and the same region.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.domain import Catalog, FitResult, ForecastGrid, Region
from rupture.models.challengers.gridded import GriddedChallenger
from tests.fixtures.forecasting.loader import FIXTURE_DIR, fixture_region, load_fixture_catalog
from tests.fixtures.models.gridded import small_config, small_region

FIT_DIR = FIXTURE_DIR / "fit-2019-07-01"

#: The committed ETAS fit's cutoff. Both components are fitted here; validation windows start here.
WEIGHTS_CUTOFF = datetime(2019, 7, 1, tzinfo=UTC)
HORIZON = timedelta(days=30)
#: Two validation windows, the last of which closes exactly at the test cutoff.
N_VALIDATION_WINDOWS = 2
TEST_CUTOFF = WEIGHTS_CUTOFF + N_VALIDATION_WINDOWS * HORIZON
#: The committed fit's Mc, which the ETAS component's history must respect.
ETAS_MC = 3.0


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return load_fixture_catalog()


@pytest.fixture(scope="session")
def region() -> Region:
    """The components share the fixture's own region so their lattices match.

    ``magnitude_max`` is lowered to 5.95 for the suite only: it changes nothing about the model
    and cuts each grid from 51 magnitude bins to 21, which is most of the suite's runtime.
    """
    return fixture_region().model_copy(update={"magnitude_max": 5.95})


@pytest.fixture(scope="session")
def committed_fit() -> FitResult:
    return FitResult.model_validate_json((FIT_DIR / "fit_result.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def validation_times() -> list[datetime]:
    return [WEIGHTS_CUTOFF + k * HORIZON for k in range(N_VALIDATION_WINDOWS)]


@pytest.fixture(scope="session")
def gridded(catalog: Catalog, region: Region) -> GriddedChallenger:
    model = GriddedChallenger(
        small_config(training_years=1.5, inner_validation_years=0.25), faults_path=None
    )
    model.fit(catalog, region, WEIGHTS_CUTOFF, mc=ETAS_MC)
    return model


@pytest.fixture(scope="session")
def etas(committed_fit: FitResult, region: Region) -> MizrahiETAS:
    model = MizrahiETAS(auxiliary_years=0.5)
    model.load_fit(committed_fit, region)
    return model


@pytest.fixture(scope="session")
def etas_component(
    etas: MizrahiETAS, catalog: Catalog
) -> Callable[[Catalog, datetime, timedelta], ForecastGrid]:
    """Memoised so the suite issues each ETAS forecast once (five continuations, fixed seed)."""
    cache: dict[tuple[datetime, timedelta], ForecastGrid] = {}

    def provider(history: Catalog, issue_time: datetime, horizon: timedelta) -> ForecastGrid:
        key = (issue_time, horizon)
        if key not in cache:
            usable = history.earthquakes().at_least(ETAS_MC)
            cache[key] = etas.forecast(usable, issue_time, horizon, n_simulations=5, seed=11)
        return cache[key]

    return provider


@pytest.fixture(scope="session")
def gridded_component(
    gridded: GriddedChallenger,
) -> Callable[[Catalog, datetime, timedelta], ForecastGrid]:
    cache: dict[tuple[datetime, timedelta], ForecastGrid] = {}

    def provider(history: Catalog, issue_time: datetime, horizon: timedelta) -> ForecastGrid:
        key = (issue_time, horizon)
        if key not in cache:
            cache[key] = gridded.forecast(history, issue_time, horizon)
        return cache[key]

    return provider


@pytest.fixture(scope="session")
def other_region() -> Region:
    """A different lattice, for the test that mismatched components are refused."""
    return small_region()
