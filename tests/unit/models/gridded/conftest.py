"""Fixtures for the gridded challenger: the real ComCat slice on a small test region.

Every event comes from ``tests/fixtures/forecasting/comcat-california-2018-2019-m3.geojson``, a
committed real slice with its own provenance record. Nothing here is synthesised, and no fit in
this suite is a production fit: the region is 48 cells and the configuration runs two epochs.
"""

from __future__ import annotations

import pytest

from rupture.domain import Catalog, Region
from rupture.models.challengers.gridded import GriddedChallenger, GriddedConfig
from rupture.models.challengers.gridded import features as feat
from tests.fixtures.forecasting.loader import load_fixture_catalog
from tests.fixtures.models.gridded import FIXTURE_CUTOFF, FIXTURE_MC, small_config, small_region


@pytest.fixture(scope="session")
def catalog() -> Catalog:
    return load_fixture_catalog()


@pytest.fixture(scope="session")
def region() -> Region:
    return small_region()


@pytest.fixture(scope="session")
def raster(region: Region) -> feat.Raster:
    return feat.build_raster(region)


@pytest.fixture(scope="session")
def events(catalog: Catalog, raster: feat.Raster, region: Region) -> feat.EventArrays:
    return feat.event_arrays(catalog, raster, region)


@pytest.fixture(scope="session")
def config() -> GriddedConfig:
    return small_config()


@pytest.fixture(scope="session")
def fitted(catalog: Catalog, region: Region, config: GriddedConfig) -> GriddedChallenger:
    """One fit shared by the suite: two epochs on 48 cells, with the GEM parquet not required."""
    model = GriddedChallenger(config, faults_path=None)
    model.fit(catalog, region, FIXTURE_CUTOFF, mc=FIXTURE_MC)
    return model
