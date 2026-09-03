"""Offline builds from the fixtures: association, precedence, filters, Mc, ids, round trip."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.sources.regions import contains, region_polygon
from rupture.adapters.storage.geoparquet import parquet_metadata, read_catalog, write_catalog
from rupture.commands.catalog import region_mc_decision
from rupture.domain import (
    Catalog,
    CompletenessEstimate,
    EventType,
    HomogenisationStep,
    MagnitudePolicy,
    MagnitudeType,
    McMethod,
    Region,
)
from rupture.pipelines import completeness as cp
from rupture.pipelines import magnitudes as mg
from rupture.pipelines.build_catalog import (
    MergeConfig,
    association_keys,
    build_catalog,
    contributing_lanes,
    depth_in_range,
    haversine_km,
    lane_of,
    mw_coverage_at,
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


# ------------------------------------------------------------ magnitude policy (ADR-0019)

RIDGECREST_START = datetime(2019, 7, 4, tzinfo=UTC)
RIDGECREST_END = datetime(2019, 8, 3, tzinfo=UTC)


def _ridgecrest(fixtures_root: Path, region: Region) -> Catalog:
    return build_catalog(
        region,
        RIDGECREST_START,
        RIDGECREST_END,
        ["comcat", "isc", "gcmt"],
        offline_fixtures=fixtures_root,
        estimate_mc=False,
    )


def test_strict_policy_leaves_ml_events_without_mw(fixtures_root: Path, california: Region) -> None:
    strict = california.model_copy(update={"magnitude_policy": MagnitudePolicy.STRICT})
    cat = _ridgecrest(fixtures_root, strict)
    ml_only = [
        e
        for e in cat.events
        if e.magnitude.type in {MagnitudeType.ML, MagnitudeType.MD}
        and not any(m.type in mg.MOMENT_TYPES for m in e.other_magnitudes)
    ]
    assert len(ml_only) > 50
    assert all(e.mw is None and e.mw_conversion is None for e in ml_only)
    assert not any((e.mw_conversion or "").startswith("assumed-equivalent") for e in cat.events)
    assert cat.notes is not None
    assert "magnitude_policy=strict" in cat.notes


def test_network_preferred_policy_assumes_ml_as_mw(fixtures_root: Path, california: Region) -> None:
    assert california.magnitude_policy is MagnitudePolicy.NETWORK_PREFERRED_AS_MW
    cat = _ridgecrest(fixtures_root, california)
    assumed = [e for e in cat.events if (e.mw_conversion or "").startswith("assumed-equivalent")]
    assert len(assumed) > 50
    for e in assumed:
        assert e.magnitude.type in {MagnitudeType.ML, MagnitudeType.MD, MagnitudeType.MLV}
        assert e.mw == e.magnitude.value
        assert e.mw_conversion == f"assumed-equivalent:{e.magnitude.type.value}"
        assert not any(m.type in mg.MOMENT_TYPES for m in e.other_magnitudes)
    log = {
        x.event_id: x
        for x in cat.homogenisation_log
        if x.step is HomogenisationStep.MAGNITUDE_CONVERTED
    }
    assert all("assumed Mw-equivalent (ADR-0019)" in log[e.id].detail for e in assumed)
    # moment magnitudes and Scordilis conversions keep precedence
    main = max(cat.events, key=lambda e: e.mw or 0)
    assert main.mw_conversion == "identity:mwc"
    assert main.mw >= 7.0
    strict_cat = _ridgecrest(
        fixtures_root, california.model_copy(update={"magnitude_policy": MagnitudePolicy.STRICT})
    )
    strict_by_id = {e.id: e for e in strict_cat.events}
    for e in cat.events:
        if not (e.mw_conversion or "").startswith("assumed-equivalent"):
            assert (e.mw, e.mw_conversion) == (
                strict_by_id[e.id].mw,
                strict_by_id[e.id].mw_conversion,
            )
    assert "magnitude_policy=network-preferred-as-mw" in (cat.notes or "")


# ------------------------------------------------------------ QA follow-ups (B1, M5, minors)


def test_negative_depth_shallow_event_is_kept(fixtures_root: Path, california: Region) -> None:
    """ComCat ``ci38462175`` (Ridgecrest, -0.13 km) must survive the default depth_min_km = 0."""
    cat = build_catalog(
        california,
        RIDGECREST_START,
        RIDGECREST_END,
        ["comcat"],  # ComCat-only build forces the ComCat solution to be preferred
        offline_fixtures=fixtures_root,
        estimate_mc=False,
    )
    hits = [e for e in cat.events if e.source_event_id == "ci38462175"]
    assert len(hits) == 1
    assert hits[0].source_catalog == "usgs-comcat"
    assert hits[0].depth_km is not None
    assert hits[0].depth_km < 0
    dropped = {
        x.event_id for x in cat.homogenisation_log if x.step is HomogenisationStep.DEPTH_FILTERED
    }
    assert hits[0].id not in dropped
    assert not any(e.depth_km is not None and e.depth_km > 30.0 for e in cat.events)


def test_depth_lower_bound_only_when_explicit(california: Region) -> None:
    assert depth_in_range(-0.13, california)
    assert depth_in_range(0.0, california)
    assert not depth_in_range(30.1, california)
    deep_only = california.model_copy(update={"depth_min_km": 5.0})
    assert not depth_in_range(-0.13, deep_only)
    assert not depth_in_range(4.9, deep_only)
    assert depth_in_range(5.0, deep_only)


def test_mw_coverage_and_notes(gorkha: Catalog, nepal: Region) -> None:
    with_mw, total = mw_coverage_at(gorkha, nepal.target_min_magnitude)
    assert 0 < with_mw <= total
    assert with_mw / total > 0.8  # Nepal M >= 4.7 is dominated by convertible mb / Mw
    assert gorkha.notes is not None
    assert "etas cross-check not run" in gorkha.notes
    assert "magnitude_policy=strict" in gorkha.notes


def _estimate(method: McMethod, mc: float, b: float | None) -> CompletenessEstimate:
    return CompletenessEstimate(
        mc=mc,
        method=method,
        b_value=b,
        b_value_uncertainty=0.05 if b else None,
        n_events=100,
        window_start=GORKHA_START,
        window_end=GORKHA_END,
        computed_at=GORKHA_END,
        correction=0.2 if method is McMethod.MAXIMUM_CURVATURE else 0.0,
        notes="test",
    )


def test_region_mc_decision_publishes_only_when_b_and_coverage_pass(
    gorkha: Catalog, nepal: Region
) -> None:
    good = gorkha.model_copy(
        update={
            "completeness": (
                _estimate(McMethod.MAXIMUM_CURVATURE, 4.4, 1.1),
                _estimate(McMethod.B_VALUE_STABILITY, 4.7, 1.2),
            )
        }
    )
    updated, reason = region_mc_decision(good, nepal)
    assert updated.mc is not None
    assert updated.mc.mc == 4.4
    assert len(updated.mc_estimates) == 2
    assert all("Mw coverage at M>=4.7" in (c.notes or "") for c in updated.mc_estimates)
    assert "b=1.10" in (updated.mc.notes or "")
    assert reason.startswith("mc=4.40 published")

    low_b = good.model_copy(
        update={
            "completeness": (
                _estimate(McMethod.MAXIMUM_CURVATURE, 3.7, 0.59),
                _estimate(McMethod.B_VALUE_STABILITY, 4.9, 0.95),
            )
        }
    )
    refused, reason = region_mc_decision(low_b, nepal)
    assert refused.mc is None
    assert len(refused.mc_estimates) == 2
    assert "b 0.59 < 0.7" in reason
    forced, reason = region_mc_decision(low_b, nepal, force=True)
    assert forced.mc is not None
    assert "--force-mc" in (forced.mc.notes or "")
    assert "[forced]" in reason

    # low Mw coverage: strip mw from every target-size event
    stripped = tuple(
        e.model_copy(update={"mw": None, "mw_conversion": None})
        if e.magnitude.value >= nepal.target_min_magnitude
        else e
        for e in good.events
    )
    low_cov = good.model_copy(update={"events": stripped})
    refused, reason = region_mc_decision(low_cov, nepal)
    assert refused.mc is None
    assert "coverage 0% < 80%" in reason


def test_b_value_stability_uses_six_cutoffs() -> None:
    assert cp.STABILITY_BINS == 6
