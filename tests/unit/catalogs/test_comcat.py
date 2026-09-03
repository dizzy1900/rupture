"""ComCat GeoJSON parser on the committed real slices."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from rupture.adapters.catalogs import comcat
from rupture.domain import EventType, MagnitudeType, Provenance
from tests.unit.catalogs.conftest import fixture_file


def test_gorkha_slice_parses_every_feature(test_provenance: Provenance) -> None:
    f = fixture_file("comcat", "gorkha-2015-30d-m4.geojson")
    report = comcat.parse_comcat_geojson_report(f.content, provenance=f.provenance)
    doc = json.loads(f.content)
    assert report.skipped == []
    assert len(report.events) == doc["metadata"]["count"] == len(doc["features"])
    main = next(e for e in report.events if e.source_event_id == "us20002926")
    assert main.origin_time == datetime(2015, 4, 25, 6, 11, 25, 950000, tzinfo=UTC)
    assert main.magnitude.type is MagnitudeType.MWW
    assert main.magnitude.value == 7.8
    assert main.mw == 7.8
    assert main.mw_conversion == "identity:mww"
    assert main.depth_km == pytest.approx(8.22)
    assert main.event_type is EventType.EARTHQUAKE
    assert main.provenance.sha256 == f.provenance.sha256
    assert main.horizontal_uncertainty_km is None  # summary feed has no error fields
    assert main.id == "usgs-comcat:us20002926"


def test_mb_events_are_not_converted_at_parse_time() -> None:
    f = fixture_file("comcat", "gorkha-2015-30d-m4.geojson")
    events = comcat.parse_comcat_geojson(f.content, provenance=f.provenance)
    mb = [e for e in events if e.magnitude.type is MagnitudeType.MB]
    assert len(mb) > 200
    assert all(e.mw is None and e.mw_conversion is None for e in mb)


def test_landslide_entry_is_retained_and_tagged() -> None:
    f = fixture_file("comcat", "nepal-2026-landslide-us7000tbwb.geojson")
    events = comcat.parse_comcat_geojson(f.content, provenance=f.provenance)
    ls = next(e for e in events if e.source_event_id == "us7000tbwb")
    assert ls.event_type is EventType.LANDSLIDE
    assert ls.magnitude.value == 5.2
    assert ls.magnitude.raw_type == "ms_vx"
    assert ls.magnitude.type is MagnitudeType.OTHER
    assert ls.mw is None
    assert ls.depth_km == 0.0
    assert (ls.latitude, ls.longitude) == pytest.approx((28.271, 85.515), abs=0.01)
    assert ls.origin_time.date().isoformat() == "2026-08-26"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("earthquake", EventType.EARTHQUAKE),
        ("landslide", EventType.LANDSLIDE),
        ("quarry blast", EventType.EXPLOSION),
        ("mining explosion", EventType.EXPLOSION),
        ("nuclear explosion", EventType.EXPLOSION),
        ("explosion", EventType.EXPLOSION),
        ("rock burst", EventType.OTHER),
        ("ice quake", EventType.OTHER),
        ("something new", EventType.OTHER),
        (None, EventType.EARTHQUAKE),
    ],
)
def test_event_type_mapping(raw: str | None, expected: EventType) -> None:
    assert comcat.map_event_type(raw) is expected


def test_feature_without_magnitude_is_reported_not_silently_dropped(
    test_provenance: Provenance,
) -> None:
    # synthetic *input to the parser*, not data: a feature with mag=null cannot become an Event
    doc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": "x1",
                "properties": {"mag": None, "time": 0, "type": "earthquake"},
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0, 10.0]},
            }
        ],
    }
    report = comcat.parse_comcat_geojson_report(json.dumps(doc), provenance=test_provenance)
    assert report.events == []
    assert report.skipped == [("x1", "no magnitude")]


def test_non_feature_collection_raises(test_provenance: Provenance) -> None:
    with pytest.raises(ValueError, match="FeatureCollection"):
        comcat.parse_comcat_geojson(b'{"type": "Feature"}', provenance=test_provenance)


def test_query_url_carries_bbox_window_and_page_limit(nepal) -> None:  # type: ignore[no-untyped-def]
    url = comcat.query_url(
        nepal,
        datetime(2015, 4, 25, tzinfo=UTC),
        datetime(2015, 5, 25, tzinfo=UTC),
        min_magnitude=4.0,
    )
    assert url.startswith("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson")
    assert "starttime=2015-04-25T00%3A00%3A00" in url
    assert "minmagnitude=4" in url
    assert "limit=20000" in url
    assert "minlongitude=80.0000" in url


def test_offline_source_filters_to_region_window_and_magnitude(nepal, fixtures_root) -> None:  # type: ignore[no-untyped-def]
    src = comcat.ComCatSource(offline_fixtures=fixtures_root)
    cat = src.fetch(
        nepal,
        datetime(2015, 4, 25, tzinfo=UTC),
        datetime(2015, 4, 26, tzinfo=UTC),
        min_magnitude=5.0,
    )
    assert cat.sources == ("usgs-comcat",)
    assert all(e.magnitude.value >= 5.0 for e in cat.events)
    assert all(e.origin_time.date().isoformat() == "2015-04-25" for e in cat.events)
    assert any(e.source_event_id == "us20002926" for e in cat.events)
