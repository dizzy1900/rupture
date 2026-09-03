"""Offline builds from the fixtures: association, precedence, filters, Mc, ids, round trip."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.sources.regions import contains, region_polygon
from rupture.adapters.storage.geoparquet import parquet_metadata, read_catalog, write_catalog
from rupture.domain import Catalog, EventType, HomogenisationStep, McMethod, Region
from rupture.pipelines import completeness as cp
from rupture.pipelines.build_catalog import (
    MergeConfig,
    association_keys,
    build_catalog,
    contributing_lanes,
    haversine_km,
    lane_of,
    rupture_event_id,
)

GORKHA_START = datetime(2015, 4, 25, tzinfo=UTC)
GORKHA_END = datetime(2015, 5, 25, tzinfo=UTC)


@pytest.fixture(scope="module")
def gorkha(fixtures_root: Path, nepal: Region) -> Catalog:
    return build_catalog(
        nepal,
        GORKHA_START,
        GORKHA_END,
        ["comcat", "isc", "gcmt"],
        offline_fixtures=fixtures_root,
        etas_cross_check=False,
    )


def test_gorkha_mainshock_merges_three_sources_with_gcmt_mw(gorkha: Catalog) -> None:
    main = [e for e in gorkha.events if e.magnitude.value > 7.5]
    assert len(main) == 1, [(e.source_catalog, e.source_event_id) for e in main]
    m = main[0]
    assert set(m.contributing_ids) == {
        "isc:607208674",
        "usgs-comcat:us20002926",
        "gcmt:C201504250611A",
    }
    # location/time from ISC (highest present in precedence), Mw from GCMT
    assert m.source_catalog == "isc"
    assert m.origin_time == datetime(2015, 4, 25, 6, 11, 26, 634000, tzinfo=UTC)
    assert m.mw == 7.88
    assert m.mw_conversion == "identity:mwc"
    assert {r.type.value for r in m.other_magnitudes} >= {"mww", "mwc"}
    assert m.id == rupture_event_id("isc", "607208674")
    merged = [x for x in gorkha.homogenisation_log if x.event_id == m.id]
    assert {x.step for x in merged} >= {
        HomogenisationStep.DUPLICATE_MERGED,
        HomogenisationStep.PREFERRED_SOLUTION,
        HomogenisationStep.MAGNITUDE_CONVERTED,
    }


def test_aftershock_m7_3_also_merges(gorkha: Catalog) -> None:
    hits = [
        e for e in gorkha.events if e.origin_time.strftime("%Y-%m-%d %H:%M") == "2015-05-12 07:05"
    ]
    assert len(hits) == 1
    assert "gcmt:C201505120705A" in hits[0].contributing_ids
    assert hits[0].mw_conversion == "identity:mwc"


def test_no_source_record_contributes_twice(gorkha: Catalog) -> None:
    counts = Counter(cid for e in gorkha.events for cid in e.contributing_ids)
    assert all(n == 1 for n in counts.values())


def test_records_from_one_lane_never_merge(gorkha: Catalog) -> None:
    for e in gorkha.events:
        assert len(contributing_lanes(e)) == len(e.contributing_ids), e.contributing_ids
    assert lane_of(gorkha.events[0]) in contributing_lanes(gorkha.events[0])


def test_no_cross_lane_pair_survives_within_windows(gorkha: Catalog) -> None:
    cfg = MergeConfig()
    events = sorted(gorkha.events, key=lambda e: e.origin_time)
    for i, a in enumerate(events):
        for b in events[i + 1 :]:
            if (b.origin_time - a.origin_time) > timedelta(seconds=cfg.time_window_s + 60):
                break
            if contributing_lanes(a) & contributing_lanes(b):
                continue  # the lane rule kept two distinct same-bulletin events apart
            close = any(
                abs((ta - tb).total_seconds()) <= cfg.time_window_s
                and haversine_km(la, lo_a, lb, lo_b) <= cfg.distance_km
                for ta, la, lo_a in association_keys(a)
                for tb, lb, lo_b in association_keys(b)
            )
            assert not close, (a.id, b.id)


def test_magnitude_homogenisation_mix(gorkha: Catalog) -> None:
    conv = Counter(e.mw_conversion for e in gorkha.events)
    assert conv["scordilis2006:mb"] > 100
    assert conv["identity:mwc"] >= 5
    unconvertible = [e for e in gorkha.events if e.mw is None]
    steps = {
        x.event_id: x.step for x in gorkha.homogenisation_log if x.step.name.startswith("MAGNITUDE")
    }
    assert all(steps[e.id] is HomogenisationStep.MAGNITUDE_UNCONVERTIBLE for e in unconvertible)


def test_events_inside_polygon_and_depth(gorkha: Catalog, nepal: Region) -> None:
    poly = region_polygon(nepal)
    assert all(contains(poly, e.longitude, e.latitude) for e in gorkha.events)
    assert all(e.depth_km is None or e.depth_km <= nepal.depth_max_km for e in gorkha.events)
    dropped = [
        x for x in gorkha.homogenisation_log if x.step is HomogenisationStep.OUTSIDE_REGION_DROPPED
    ]
    assert dropped, "the fixture bbox is wider than the polygon, so something must be dropped"


def test_completeness_estimates_for_gorkha_slice_are_plausible(gorkha: Catalog) -> None:
    maxc = gorkha.preferred_mc(McMethod.MAXIMUM_CURVATURE)
    stab = gorkha.preferred_mc(McMethod.B_VALUE_STABILITY)
    assert maxc is not None
    assert stab is not None
    assert 4.0 <= maxc.mc <= 5.0
    assert 4.0 <= stab.mc <= 5.0
    assert maxc.correction == 0.2
    assert maxc.b_value is not None
    assert 0.6 <= maxc.b_value <= 1.5
    assert stab.b_value is not None
    assert 0.6 <= stab.b_value <= 1.5
    assert maxc.window_start == GORKHA_START
    assert maxc.window_end == GORKHA_END


def test_landslide_retained_in_full_nepal_window(fixtures_root: Path, nepal: Region) -> None:
    cat = build_catalog(
        nepal,
        datetime(2026, 8, 20, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
        ["comcat", "isc", "gcmt"],
        offline_fixtures=fixtures_root,
        estimate_mc=False,
    )
    ls = [e for e in cat.events if e.source_event_id == "us7000tbwb"]
    assert len(ls) == 1
    assert ls[0].event_type is EventType.LANDSLIDE
    assert ls[0].mw is None
    assert cat.earthquakes().count_by_type()[EventType.LANDSLIDE] == 0
    tagged = [x for x in cat.homogenisation_log if x.step is HomogenisationStep.EVENT_TYPE_TAGGED]
    assert any(x.event_id == ls[0].id for x in tagged)


def test_ids_are_deterministic_across_rebuilds(
    fixtures_root: Path, nepal: Region, gorkha: Catalog
) -> None:
    again = build_catalog(
        nepal,
        GORKHA_START,
        GORKHA_END,
        ["comcat", "isc", "gcmt"],
        offline_fixtures=fixtures_root,
        estimate_mc=False,
    )
    assert [e.id for e in again.events] == [e.id for e in gorkha.events]
    assert again.event_hash() == gorkha.event_hash()
    assert rupture_event_id("isc", "607208674").startswith("rup-")
    assert len(rupture_event_id("isc", "607208674")) == 16


def test_isc_gem_absence_is_recorded_not_fatal(fixtures_root: Path, nepal: Region) -> None:
    cat = build_catalog(
        nepal,
        GORKHA_START,
        GORKHA_START + timedelta(days=1),
        ["comcat", "isc-gem"],
        offline_fixtures=fixtures_root,
        estimate_mc=False,
    )
    assert cat.sources == ("usgs-comcat",)
    assert cat.notes is not None
    assert "isc-gem not included" in cat.notes


def test_other_regions_build_offline(
    fixtures_root: Path, turkiye: Region, california: Region
) -> None:
    tk = build_catalog(
        turkiye,
        datetime(2023, 2, 6, tzinfo=UTC),
        datetime(2023, 3, 8, tzinfo=UTC),
        ["comcat", "isc", "gcmt"],
        offline_fixtures=fixtures_root,
        etas_cross_check=False,
    )
    ca = build_catalog(
        california,
        datetime(2019, 7, 4, tzinfo=UTC),
        datetime(2019, 8, 3, tzinfo=UTC),
        ["comcat", "isc", "gcmt"],
        offline_fixtures=fixtures_root,
        etas_cross_check=False,
    )
    assert max(e.mw or 0 for e in tk.events) >= 7.7  # Kahramanmaras Mw 7.8 (GCMT)
    assert max(e.mw or 0 for e in ca.events) >= 7.0  # Ridgecrest Mw 7.1
    for cat in (tk, ca):
        assert cat.preferred_mc(McMethod.MAXIMUM_CURVATURE) is not None
        assert cat.preferred_mc(McMethod.B_VALUE_STABILITY) is not None


def test_geoparquet_round_trip(gorkha: Catalog, tmp_path: Path) -> None:
    paths = write_catalog(gorkha, tmp_path)
    assert {p.name for p in tmp_path.iterdir()} == {
        "events.parquet",
        "catalog.meta.json",
        "homogenisation_log.jsonl",
    }
    back = read_catalog(tmp_path)
    assert back == gorkha
    md = parquet_metadata(paths["events"])
    assert md["rupture:region_id"] == "nepal-himalaya"
    assert "public-domain (USGS)" in md["rupture:licences"]


def test_empty_catalog_round_trips(gorkha: Catalog, tmp_path: Path) -> None:
    empty = gorkha.model_copy(update={"events": (), "homogenisation_log": ()})
    write_catalog(empty, tmp_path)
    assert read_catalog(tmp_path) == empty


# --------------------------------------------------------------- completeness maths


def test_aki_b_value_recovers_a_known_slope() -> None:
    """Synthetic Gutenberg-Richter sample (statistical input, not catalogue data).

    Magnitudes reported to 0.1 come from a continuous law whose lowest bin, centred on Mc,
    covers [Mc - 0.05, Mc + 0.05); the sample therefore starts at 2.95 for Mc = 3.0.
    """
    rng = np.random.default_rng(7)
    b_true = 1.0
    mags = 2.95 + rng.exponential(scale=1 / (b_true * np.log(10)), size=20_000)
    binned = cp.bin_magnitudes(mags, 0.1)
    b, sigma, n = cp.b_value_aki(binned, 3.0, 0.1)
    assert n == 20_000
    assert b == pytest.approx(b_true, abs=0.03)
    assert 0 < sigma < 0.02
    assert cp.maximum_curvature(binned, 0.1) == pytest.approx(3.2)  # mode 3.0 + 0.2
    stab = cp.b_value_stability(binned, 0.1)
    assert stab is not None
    assert stab[0] == pytest.approx(3.0)


def test_completeness_needs_two_magnitudes() -> None:
    with pytest.raises(cp.InsufficientDataError):
        cp.estimate_completeness(
            [5.0], window_start=GORKHA_START, window_end=GORKHA_END, with_etas_cross_check=False
        )
