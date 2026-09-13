"""USGS real-time GeoJSON parser on the committed Ridgecrest cut."""

from __future__ import annotations

from datetime import UTC, datetime

from rupture.adapters.observations.usgs_feed import (
    FEEDS,
    UsgsRealtimeFeed,
    parse_usgs_feed_geojson,
)
from rupture.domain import EventType, VintagePolicy
from rupture.domain.observation import ObservableKind
from tests.unit.observations.conftest import fixture_file


def test_ridgecrest_cut_parses_m71_with_comcat_vintage_clock() -> None:
    fx = fixture_file("usgs_feed", "all_day.ridgecrest-2019-07-06.geojson")
    events = parse_usgs_feed_geojson(fx.content, provenance=fx.provenance)
    assert events
    main = next(e for e in events if e.source_event_id == "ci38457511")
    assert main.origin_time == datetime(2019, 7, 6, 3, 19, 53, 40000, tzinfo=UTC)
    assert main.available_time is not None
    assert main.available_time > main.origin_time
    assert main.magnitude.value == 7.1
    assert main.event_type is EventType.EARTHQUAKE
    assert main.source_catalog == "usgs-realtime-feed"
    assert main.provenance.sha256 == fx.provenance.sha256
    assert all(e.origin_time.date().isoformat() == "2019-07-06" for e in events)


def test_offline_feed_source_does_not_fetch() -> None:
    from tests.unit.observations.conftest import FIXTURES

    src = UsgsRealtimeFeed(offline_fixtures=FIXTURES)
    assert src.kind is ObservableKind.CATALOGUE_EVENT
    catalog = src.catalog()
    assert len(catalog) > 0
    as_of = catalog.events[0].origin_time
    kept = src.available_as_of(as_of, policy=VintagePolicy.EXCLUDE_UNKNOWN)
    assert all(
        e.available_time is not None and e.available_time < as_of for e in kept.events
    )


def test_documented_feeds_include_hour_day_and_significant_month() -> None:
    assert "all_hour" in FEEDS
    assert "all_day" in FEEDS
    assert "significant_month" in FEEDS
    assert FEEDS["all_day"].endswith("/all_day.geojson")
