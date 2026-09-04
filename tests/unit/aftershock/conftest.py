"""Session fixtures for the aftershock tests: the committed slices, regions and fits.

Everything here reads real committed data. No network: the loaders verify the recorded sha256 of
each slice and would fail loudly if it were missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rupture.domain import Catalog, FitResult, Region
from rupture.services.aftershock.forecaster import AftershockForecaster
from rupture.services.aftershock.sequences import (
    SequenceSpec,
    load_committed_fits,
    load_parent_region,
    load_sequence_catalog,
    sequence_spec,
)
from rupture.services.aftershock.service import LoadedSequence, load_default_sequences

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def gorkha() -> SequenceSpec:
    return sequence_spec("gorkha")


@pytest.fixture(scope="session")
def gorkha_catalog(gorkha: SequenceSpec) -> Catalog:
    return load_sequence_catalog(gorkha, REPO_ROOT)


@pytest.fixture(scope="session")
def nepal_region(gorkha: SequenceSpec) -> Region:
    return load_parent_region(gorkha, REPO_ROOT)


@pytest.fixture(scope="session")
def gorkha_fits(gorkha: SequenceSpec) -> dict[str, FitResult]:
    return load_committed_fits(gorkha, REPO_ROOT)


@pytest.fixture(scope="session")
def loaded_sequences(repo_root: Path) -> dict[str, LoadedSequence]:
    """Both committed sequences as the service loads them (catalogues, regions, fits on disk)."""
    return load_default_sequences(repo_root)


@pytest.fixture(scope="session")
def fast_forecaster() -> AftershockForecaster:
    """Deliberately crude: two continuations on a 0.4-degree lattice, so a test runs in seconds."""
    return AftershockForecaster(n_simulations=2, cell_size_deg=0.4, seed=5)
