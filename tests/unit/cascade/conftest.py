"""Shared paths and builders for the cascade tests. Everything reads committed fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def gorkha_fixtures(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "cascade" / "gorkha-2015"


@pytest.fixture(scope="session")
def usgs_fixtures(repo_root: Path) -> Path:
    return repo_root / "tests" / "fixtures" / "cascade" / "usgs_groundfailure"
