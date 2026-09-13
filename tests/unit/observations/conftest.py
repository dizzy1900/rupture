"""Offline observation-adapter tests: committed fixtures only, sockets disabled."""

from __future__ import annotations

from pathlib import Path

import pytest

from rupture.adapters.catalogs.fixtures import FixtureFile, load_fixture_dir

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "data" / "fixtures"


def fixture_file(source_dir: str, name: str) -> FixtureFile:
    files = load_fixture_dir(FIXTURES / source_dir, adapter_version="test")
    for item in files:
        if item.path.name == name:
            return item
    msg = f"{source_dir}/{name} not listed in provenance.json"
    raise KeyError(msg)


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    return FIXTURES


@pytest.fixture(autouse=True)
def _block_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never call the HTTP fetch path."""

    def _blocked(*_args: object, **_kwargs: object) -> None:
        msg = "unit tests must not call fetch_bytes"
        raise RuntimeError(msg)

    for target in (
        "rupture.adapters.observations.ngl.fetch_bytes",
        "rupture.adapters.observations.usgs_feed.fetch_bytes",
        "rupture.adapters.observations.fdsn_events.fetch_bytes",
    ):
        monkeypatch.setattr(target, _blocked)
