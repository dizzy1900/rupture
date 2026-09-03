"""Opt-in network checks (``make test-integration``): the services still answer as the adapters
expect. Nothing here is a data assertion beyond the presence of well-known events."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rupture.adapters.catalogs import comcat, gcmt, isc
from rupture.adapters.sources import openquake_sources
from rupture.adapters.sources.regions import load_region

pytestmark = pytest.mark.integration
REGIONS = Path(__file__).resolve().parents[3] / "data" / "regions"


def test_comcat_live_gorkha_day() -> None:
    nepal = load_region(REGIONS, "nepal-himalaya")
    cat = comcat.ComCatSource().fetch(
        nepal,
        datetime(2015, 4, 25, tzinfo=UTC),
        datetime(2015, 4, 26, tzinfo=UTC),
        min_magnitude=6.0,
    )
    assert any(e.source_event_id == "us20002926" for e in cat.events)
    assert all(e.provenance.sha256 for e in cat.events)


def test_isc_live_gorkha_day() -> None:
    nepal = load_region(REGIONS, "nepal-himalaya")
    cat = isc.IscSource().fetch(
        nepal,
        datetime(2015, 4, 25, tzinfo=UTC),
        datetime(2015, 4, 26, tzinfo=UTC),
        min_magnitude=6.0,
    )
    assert any(e.source_event_id == "607208674" for e in cat.events)


def test_gcmt_live_monthly_file(tmp_path: Path) -> None:
    nepal = load_region(REGIONS, "nepal-himalaya")
    cat = gcmt.GcmtSource(cache_dir=tmp_path).fetch(
        nepal, datetime(2021, 1, 1, tzinfo=UTC), datetime(2021, 2, 1, tzinfo=UTC)
    )
    assert cat.sources == ("gcmt",)
    assert any(p.suffix == ".bin" for p in tmp_path.iterdir())


def test_eshm20_tree_lists_logic_trees() -> None:
    commit = openquake_sources.resolve_commit()
    tree = openquake_sources.list_tree(ref=commit)
    paths = {t["path"] for t in tree}
    assert openquake_sources.SOURCE_MODEL_LOGIC_TREE in paths
    assert openquake_sources.GSIM_LOGIC_TREE in paths
