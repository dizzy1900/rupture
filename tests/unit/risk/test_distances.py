"""Distance metrics against cases whose answer is known by construction.

Each case is set up so the correct value follows from plane geometry, not from another
implementation: a point source, a vertical plane, a 45-degree dipping plane, and a site inside
the surface projection. The tolerance quoted in each assertion is the projection error of the
local azimuthal-equidistant frame at these separations (tens of metres), not a fudge factor.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from rupture.adapters.groundmotion import distances as geo
from rupture.domain.hazard import ScenarioRupture
from tests.unit.risk.conftest import site

KM_PER_DEG = 2.0 * math.pi * geo.EARTH_RADIUS_KM / 360.0


def _rupture(**overrides: object) -> ScenarioRupture:
    base: dict[str, object] = {
        "id": "geo",
        "magnitude": 7.0,
        "hypocentre_longitude": 0.0,
        "hypocentre_latitude": 0.0,
        "hypocentre_depth_km": 10.0,
        "strike": 0.0,
        "dip": 90.0,
        "rake": 0.0,
        "hypothetical": True,
    }
    base.update(overrides)
    return ScenarioRupture(**base)  # type: ignore[arg-type]


def test_point_rupture_gives_epicentral_and_hypocentral_distances() -> None:
    rupture = _rupture(hypocentre_depth_km=12.0)
    offset_deg = 30.0 / KM_PER_DEG
    sites = (site("s", offset_deg, 0.0),)
    d = geo.distances(rupture, sites)
    assert d.rjb[0] == pytest.approx(30.0, abs=1e-6)
    assert d.rrup[0] == pytest.approx(math.hypot(30.0, 12.0), abs=1e-6)
    assert d.rhypo[0] == pytest.approx(math.hypot(30.0, 12.0), abs=1e-6)
    assert d.rx[0] == 0.0
    assert d.ztor == 12.0


def test_vertical_fault_rjb_equals_perpendicular_offset() -> None:
    """A vertical plane reaching the surface: Rjb, Rrup and |Rx| all equal the offset."""
    half_length_deg = 20.0 / KM_PER_DEG
    rupture = _rupture(
        corners=(
            (0.0, -half_length_deg, 0.0),
            (0.0, half_length_deg, 0.0),
            (0.0, half_length_deg, 15.0),
            (0.0, -half_length_deg, 15.0),
        )
    )
    offset_km = 8.0
    east = site("east", offset_km / KM_PER_DEG, 0.0)
    west = site("west", -offset_km / KM_PER_DEG, 0.0)
    d = geo.distances(rupture, (east, west))
    assert d.ztor == 0.0
    assert d.rjb[0] == pytest.approx(offset_km, abs=0.02)
    assert d.rrup[0] == pytest.approx(offset_km, abs=0.02)
    # strike points north, so east is to the right of the strike: positive Rx.
    assert d.rx[0] == pytest.approx(offset_km, abs=0.02)
    assert d.rx[1] == pytest.approx(-offset_km, abs=0.02)


def test_site_inside_the_surface_projection_has_zero_rjb() -> None:
    """A 45-degree dipping plane; the site sits over the middle of its footprint."""
    half_length_deg = 30.0 / KM_PER_DEG
    width_horizontal_km = 20.0 / math.sqrt(2.0)
    east_deg = width_horizontal_km / KM_PER_DEG
    rupture = _rupture(
        dip=45.0,
        corners=(
            (0.0, -half_length_deg, 0.0),
            (0.0, half_length_deg, 0.0),
            (east_deg, half_length_deg, width_horizontal_km),
            (east_deg, -half_length_deg, width_horizontal_km),
        ),
    )
    offset_km = 5.0
    sites = (site("hanging-wall", offset_km / KM_PER_DEG, 0.0),)
    d = geo.distances(rupture, sites)
    assert d.rjb[0] == 0.0
    # perpendicular distance from a surface site to a plane dipping 45 degrees is offset/sqrt(2)
    assert d.rrup[0] == pytest.approx(offset_km / math.sqrt(2.0), abs=0.02)
    assert d.rx[0] == pytest.approx(offset_km, abs=0.02)


def test_footwall_site_of_a_dipping_plane() -> None:
    """West of a plane dipping east: Rjb is the offset, Rrup the 3-D distance to the top edge."""
    half_length_deg = 30.0 / KM_PER_DEG
    width_horizontal_km = 20.0 / math.sqrt(2.0)
    rupture = _rupture(
        dip=45.0,
        corners=(
            (0.0, -half_length_deg, 0.0),
            (0.0, half_length_deg, 0.0),
            (width_horizontal_km / KM_PER_DEG, half_length_deg, width_horizontal_km),
            (width_horizontal_km / KM_PER_DEG, -half_length_deg, width_horizontal_km),
        ),
    )
    offset_km = 12.0
    d = geo.distances(rupture, (site("footwall", -offset_km / KM_PER_DEG, 0.0),))
    assert d.rjb[0] == pytest.approx(offset_km, abs=0.02)
    assert d.rrup[0] == pytest.approx(offset_km, abs=0.02)
    assert d.rx[0] == pytest.approx(-offset_km, abs=0.02)


def test_local_frame_reproduces_great_circle_distance() -> None:
    lons = np.array([85.5, 84.0])
    lats = np.array([28.5, 27.0])
    x, y = geo.local_frame(85.0, 28.0, lons, lats)
    for index in range(2):
        expected = _haversine(85.0, 28.0, float(lons[index]), float(lats[index]))
        assert math.hypot(float(x[index]), float(y[index])) == pytest.approx(expected, rel=1e-12)


def _haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((p2 - p1) / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2.0) ** 2
    )
    return 2.0 * geo.EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def test_a_rupture_with_the_wrong_number_of_corners_is_refused() -> None:
    rupture = _rupture(corners=((0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.1, 0.1, 5.0)))
    with pytest.raises(geo.GeometryError, match="exactly 4 corners"):
        geo.distances(rupture, (site("s", 0.5, 0.0),))
