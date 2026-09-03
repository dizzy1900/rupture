"""Shared paths and loaders for the offline catalogue tests (fixtures are real slices)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rupture.adapters.catalogs.fixtures import FixtureFile, load_fixture_dir
from rupture.adapters.sources.regions import load_region
from rupture.domain import Provenance, Region

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "data" / "fixtures"
REGIONS = REPO_ROOT / "data" / "regions"


def fixture_file(source_dir: str, name: str) -> FixtureFile:
    files = load_fixture_dir(FIXTURES / source_dir, adapter_version="test")
    for f in files:
        if f.path.name == name:
            return f
    msg = f"{source_dir}/{name} not listed in provenance.json"
    raise KeyError(msg)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def nepal() -> Region:
    return load_region(REGIONS, "nepal-himalaya")


@pytest.fixture(scope="session")
def turkiye() -> Region:
    return load_region(REGIONS, "turkiye-eaf")


@pytest.fixture(scope="session")
def california() -> Region:
    return load_region(REGIONS, "california")


@pytest.fixture
def test_provenance() -> Provenance:
    """Provenance for parser tests that only care about parsing (payload digest not asserted)."""
    return Provenance(
        source="test",
        retrieved_at=datetime(2026, 9, 3, tzinfo=UTC),
        adapter_version="test",
        licence="test",
    )
