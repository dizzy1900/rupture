"""The sequence window: rupture-length scaling, the zone polygon, and the sequence slice."""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from rupture.domain import Catalog, Region
from rupture.services.aftershock.sequences import SequenceSpec
from rupture.services.aftershock.window import (
    MAX_RADIUS_KM,
    MIN_RADIUS_KM,
    ZONE_MULTIPLIER,
    aftershock_zone_radius_km,
    epicentral_distance_km,
    sequence_catalog,
    sequence_region,
    subsurface_rupture_length_km,
    zone_polygon,
)

# Wells & Coppersmith (1994) subsurface rupture length, 10 ** (-2.44 + 0.59 M).
GORKHA_LENGTH_KM = 145.2
GORKHA_RADIUS_KM = 217.8


def test_rupture_length_matches_wells_coppersmith() -> None:
    assert subsurface_rupture_length_km(7.8) == pytest.approx(GORKHA_LENGTH_KM, abs=0.5)
    assert subsurface_rupture_length_km(6.0) == pytest.approx(
        10.0 ** (-2.44 + 0.59 * 6.0), rel=1e-12
    )


def test_zone_radius_scales_and_is_floored() -> None:
    assert aftershock_zone_radius_km(7.8) == pytest.approx(GORKHA_RADIUS_KM, abs=1.0)
    assert aftershock_zone_radius_km(7.8) == pytest.approx(
        ZONE_MULTIPLIER * subsurface_rupture_length_km(7.8), rel=1e-12
    )
    # A small mainshock gets the floor, not a sub-kilometre disc.
    assert aftershock_zone_radius_km(3.0) == MIN_RADIUS_KM
    assert aftershock_zone_radius_km(9.9) == MAX_RADIUS_KM


def test_zone_radius_is_monotone_in_magnitude() -> None:
    radii = [aftershock_zone_radius_km(m) for m in (4.0, 5.0, 6.0, 7.0, 8.0)]
    assert radii == sorted(radii)


def test_zone_polygon_vertices_lie_on_the_circle() -> None:
    lat, lon, radius = 28.2305, 84.7314, 218.0
    ring = zone_polygon(lat, lon, radius, vertices=36)
    assert len(ring) == 36
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    distance = epicentral_distance_km(lat, lon, lats, lons)
    assert distance.min() == pytest.approx(radius, rel=1e-3)
    assert distance.max() == pytest.approx(radius, rel=1e-3)


def test_zone_polygon_rejects_bad_arguments() -> None:
    with pytest.raises(ValueError, match="radius_km must be positive"):
        zone_polygon(0.0, 0.0, 0.0)
    with pytest.raises(ValueError, match="vertices must be at least 8"):
        zone_polygon(0.0, 0.0, 10.0, vertices=4)


def test_epicentral_distance_gorkha_to_the_m73_aftershock() -> None:
    """The 2015-05-12 M7.3 sits about 140 km east-south-east of the M7.8 epicentre."""
    distance = epicentral_distance_km(28.2305, 84.7314, [27.8087], [86.0655])
    assert distance[0] == pytest.approx(139.0, abs=3.0)
    # ... and therefore inside the zone, which is what f = 1.5 is for.
    assert distance[0] < aftershock_zone_radius_km(7.8)


def test_sequence_region_inherits_the_parent_settings(nepal_region: Region) -> None:
    zone = sequence_region(
        nepal_region,
        region_id="aftershock-test",
        name="test zone",
        latitude=28.2305,
        longitude=84.7314,
        radius_km=218.0,
    )
    assert zone.id == "aftershock-test"
    assert zone.mc == nepal_region.mc
    assert zone.target_min_magnitude == nepal_region.target_min_magnitude
    assert zone.magnitude_bin_width == nepal_region.magnitude_bin_width
    assert zone.depth_max_km == nepal_region.depth_max_km
    assert zone.polygon != nepal_region.polygon
    assert "Wells & Coppersmith" in (zone.description or "")


def test_sequence_catalog_keeps_only_events_after_and_inside(
    gorkha: SequenceSpec, gorkha_catalog: Catalog
) -> None:
    shock = gorkha.mainshock
    radius = aftershock_zone_radius_km(shock.magnitude)
    sequence = sequence_catalog(
        gorkha_catalog,
        mainshock_time=shock.origin_time,
        latitude=shock.latitude,
        longitude=shock.longitude,
        radius_km=radius,
    )
    assert 0 < len(sequence) < len(gorkha_catalog)
    assert all(e.origin_time >= shock.origin_time for e in sequence.events)
    lats = [e.latitude for e in sequence.events]
    lons = [e.longitude for e in sequence.events]
    assert epicentral_distance_km(shock.latitude, shock.longitude, lats, lons).max() <= radius
    # the mainshock itself is in its own sequence
    assert any(e.source_event_id == shock.event_id for e in sequence.events)
    # a decade of pre-mainshock seismicity is not
    dropped = len(gorkha_catalog) - len(sequence)
    assert dropped > 200


def test_sequence_catalog_on_an_empty_catalogue(gorkha_catalog: Catalog) -> None:
    empty = gorkha_catalog.model_copy(update={"events": ()})
    out = sequence_catalog(
        empty,
        mainshock_time=gorkha_catalog.built_at,
        latitude=0.0,
        longitude=0.0,
        radius_km=10.0,
    )
    assert len(out) == 0


def test_sequence_catalog_window_is_half_open_on_the_left(
    gorkha: SequenceSpec, gorkha_catalog: Catalog
) -> None:
    """An event one microsecond before the mainshock is not in the sequence."""
    shock = gorkha.mainshock
    later = sequence_catalog(
        gorkha_catalog,
        mainshock_time=shock.origin_time + timedelta(microseconds=1),
        latitude=shock.latitude,
        longitude=shock.longitude,
        radius_km=aftershock_zone_radius_km(shock.magnitude),
    )
    assert not any(e.source_event_id == shock.event_id for e in later.events)


def test_distance_is_symmetric_and_zero_at_the_point() -> None:
    assert epicentral_distance_km(10.0, 20.0, [10.0], [20.0])[0] == pytest.approx(0.0)
    forward = epicentral_distance_km(10.0, 20.0, [11.0], [21.0])[0]
    backward = epicentral_distance_km(11.0, 21.0, [10.0], [20.0])[0]
    assert forward == pytest.approx(backward, rel=1e-9)
    # one degree of latitude is about 111.2 km
    assert epicentral_distance_km(0.0, 0.0, [1.0], [0.0])[0] == pytest.approx(111.2, abs=0.3)
    assert math.isfinite(forward)
