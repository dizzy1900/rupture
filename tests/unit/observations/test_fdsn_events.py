"""IRIS FDSN event adapter: parser on real FDSN text, query URL, no fetch in unit tests."""

from __future__ import annotations

from datetime import UTC, datetime

from rupture.adapters.observations.fdsn_events import (
    BASE_URL,
    FdsnEventSource,
    parse_fdsn_text,
    query_url,
)
from rupture.adapters.sources.regions import load_region
from rupture.domain import Catalog, VintagePolicy, utc_now
from rupture.domain.observation import ObservableKind
from tests.unit.catalogs.conftest import fixture_file as catalog_fixture
from tests.unit.observations.conftest import REPO_ROOT


def test_fdsn_text_parser_reads_a_real_bulletin_payload() -> None:
    """ISC is served as FDSN text; the IRIS adapter speaks the same columns."""
    fx = catalog_fixture("isc", "ridgecrest-2019-7d-m3.5.txt")
    events = parse_fdsn_text(fx.content, provenance=fx.provenance, source_id="iris-fdsn")
    assert events
    assert all(e.source_catalog == "iris-fdsn" for e in events)
    assert all(e.available_time is None for e in events)
    main = next(e for e in events if e.magnitude.value >= 6.4)
    assert main.origin_time.date().isoformat() == "2019-07-04"
    assert main.latitude == 35.6695
    assert main.longitude == -117.5276


def test_query_url_is_the_documented_iris_event_path() -> None:
    region = load_region(REPO_ROOT / "data" / "regions", "california")
    url = query_url(
        region,
        datetime(2019, 7, 6, tzinfo=UTC),
        datetime(2019, 7, 7, tzinfo=UTC),
        min_magnitude=5.0,
    )
    assert url.startswith(BASE_URL)
    assert "format=text" in url
    assert "starttime=2019-07-06T00%3A00%3A00" in url
    assert "minmagnitude=5" in url
    assert "minlongitude=" in url


def test_unknown_vintage_empties_as_of_under_exclude_unknown() -> None:
    fx = catalog_fixture("isc", "ridgecrest-2019-7d-m3.5.txt")
    events = parse_fdsn_text(fx.content, provenance=fx.provenance)
    catalog = Catalog(
        id="iris-fdsn/test",
        events=tuple(events),
        sources=("iris-fdsn",),
        built_at=utc_now(),
        builder_version="test",
    )
    src = FdsnEventSource(catalog=catalog)
    assert src.kind is ObservableKind.CATALOGUE_EVENT
    as_of = datetime(2019, 8, 1, tzinfo=UTC)
    empty = src.available_as_of(as_of, policy=VintagePolicy.EXCLUDE_UNKNOWN)
    assert len(empty) == 0
    kept = src.available_as_of(as_of, policy=VintagePolicy.INCLUDE_UNKNOWN)
    assert len(kept) == len(catalog)
