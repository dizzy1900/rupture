"""The committed ComCat slice loads into the domain with honest magnitude labels."""

from __future__ import annotations

import hashlib
import json

from rupture.domain import Catalog, EventType, Region
from tests.fixtures.forecasting.loader import GEOJSON, PROVENANCE, load_fixture_catalog


def test_fixture_digest_matches_provenance() -> None:
    prov = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert hashlib.sha256(GEOJSON.read_bytes()).hexdigest() == prov["sha256"]
    assert prov["licence"] == "public-domain (USGS)"


def test_fixture_catalog_is_earthquakes_with_reported_magnitudes(fixture_catalog: Catalog) -> None:
    assert len(fixture_catalog) == 1433
    assert fixture_catalog.count_by_type()[EventType.EARTHQUAKE] == 1433
    assert all(e.mw == e.magnitude.value for e in fixture_catalog.events)
    assert all(
        e.mw_conversion is not None and e.mw_conversion.startswith("reported-as-mw:")
        for e in fixture_catalog.events
    )
    assert all(e.provenance.sha256 for e in fixture_catalog.events)
    latest = fixture_catalog.max_origin_time()
    assert latest is not None
    assert latest.year == 2019


def test_strict_mode_only_keeps_mw_family() -> None:
    strict = load_fixture_catalog(reported_as_mw=False)
    with_mw = [e for e in strict.events if e.mw is not None]
    assert 0 < len(with_mw) < len(strict)
    assert all(e.mw_conversion == f"identity:{e.magnitude.raw_type}" for e in with_mw)
    assert all(e.magnitude.raw_type in {"mw", "mww", "mwc", "mwb", "mwr"} for e in with_mw)


def test_region_bins_and_bbox(region: Region) -> None:
    edges = region.magnitude_bin_edges()
    assert edges[0] == 3.95
    assert edges[-1] == 8.95
    assert len(edges) == 51
    assert region.bbox() == (-122.0, 32.0, -114.0, 37.5)
    assert region.mc is None, "the fixture region carries no fitted Mc; tests pass mc explicitly"
