"""Load the committed ComCat fixture for the offline ETAS/eval gates.

The loader lives with the fixture under ``tests/fixtures/forecasting/`` (it is test-only code);
the gates import it by path from the repository root they are given, so the gate never depends
on ``tests`` being an installed package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from rupture.domain import Catalog, Region

FIXTURE_REL = Path("tests") / "fixtures" / "forecasting"


def fixture_dir(repo_root: Path) -> Path:
    return repo_root / FIXTURE_REL


def load_fixture(repo_root: Path) -> tuple[Catalog, Region]:
    loader = _import_loader(repo_root)
    catalog: Catalog = loader.load_fixture_catalog()
    region: Region = loader.fixture_region()
    return catalog, region


def _import_loader(repo_root: Path) -> Any:
    path = fixture_dir(repo_root) / "loader.py"
    if not path.exists():
        msg = f"fixture loader missing at {path}"
        raise FileNotFoundError(msg)
    spec = importlib.util.spec_from_file_location("rupture_fixture_loader", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        msg = f"cannot import {path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
