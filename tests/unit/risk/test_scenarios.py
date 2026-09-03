"""Scenarios: a published rupture read from its own inversion, and a hypothetical that says so."""

from __future__ import annotations

import hashlib
import json
import math

import pytest

from rupture.adapters.groundmotion import distances as geo
from rupture.risk import scenarios
from tests.unit.risk.conftest import REPO_ROOT, RISK_FIXTURES, site

GORKHA_DIR = RISK_FIXTURES / "scenarios" / "gorkha2015"
PLANAR_CORNERS = 4


def test_the_gorkha_fixture_matches_its_provenance() -> None:
    provenance = json.loads((GORKHA_DIR / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["event_id"] == "us20002926"
    assert provenance["source"] == "usgs-comcat"
    assert provenance["licence"].startswith("US Government work")
    payload = (GORKHA_DIR / "complete_inversion.fsp").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == provenance["sha256"]


def test_the_fsp_header_is_read_as_published() -> None:
    model = scenarios.parse_fsp((GORKHA_DIR / "complete_inversion.fsp").read_text(encoding="utf-8"))
    assert model.magnitude == pytest.approx(7.82)
    assert model.strike == pytest.approx(293.0)
    assert model.dip == pytest.approx(7.0)
    assert model.rake == pytest.approx(108.0)
    assert model.hypocentre_lat == pytest.approx(28.13)
    assert model.hypocentre_lon == pytest.approx(84.65)
    assert len(model.slips_m) == 552


def test_the_effective_rupture_is_smaller_than_the_inversion_grid() -> None:
    """Using the whole grid would put the rupture implausibly close to the corridor."""
    model = scenarios.parse_fsp((GORKHA_DIR / "complete_inversion.fsp").read_text(encoding="utf-8"))
    surface = scenarios.effective_rupture(model)
    assert surface.retained_slip_fraction >= scenarios.MOMENT_FRACTION
    assert surface.length_km < 193.2
    assert surface.width_km < 168.0
    assert surface.ztor_km > 0.0, "the Gorkha rupture did not reach the surface"
    assert len(surface.corners) == PLANAR_CORNERS


def test_a_stricter_threshold_gives_a_smaller_surface() -> None:
    model = scenarios.parse_fsp((GORKHA_DIR / "complete_inversion.fsp").read_text(encoding="utf-8"))
    loose = scenarios.effective_rupture(model, moment_fraction=0.95)
    tight = scenarios.effective_rupture(model, moment_fraction=0.70)
    assert tight.length_km <= loose.length_km
    assert tight.width_km <= loose.width_km


def test_the_corners_are_in_openquake_order() -> None:
    """Top edge shallow, bottom edge deep, and left-to-right along strike."""
    rupture = scenarios.gorkha_2015_repeat(REPO_ROOT)
    top_left, top_right, bottom_right, bottom_left = rupture.corners
    assert top_left[2] == pytest.approx(top_right[2])
    assert bottom_left[2] == pytest.approx(bottom_right[2])
    assert top_left[2] < bottom_left[2]
    # strike 293 degrees is WNW, so the second corner is west of the first
    assert top_right[0] < top_left[0]


def test_the_published_rupture_is_not_marked_hypothetical() -> None:
    rupture = scenarios.gorkha_2015_repeat(REPO_ROOT)
    assert rupture.hypothetical is False
    assert rupture.source_refs
    assert "us20002926" in rupture.source_refs[0]


def test_the_mht_scenario_is_hypothetical_and_says_so() -> None:
    rupture = scenarios.mht_hypothetical()
    assert rupture.hypothetical is True
    assert rupture.notes is not None
    assert rupture.notes.startswith("HYPOTHETICAL")
    assert len(rupture.source_refs) >= 3
    assert any("Hanks" in ref for ref in rupture.source_refs)


def test_the_mht_magnitude_follows_from_its_geometry() -> None:
    """The magnitude is computed, so geometry and magnitude cannot disagree."""
    rupture = scenarios.mht_hypothetical()
    width_km = scenarios.MHT_BOTTOM_DEPTH_KM / math.sin(math.radians(scenarios.MHT_DIP_DEG))
    expected = scenarios.moment_magnitude(
        scenarios.MHT_LENGTH_KM * width_km,
        scenarios.MHT_AVERAGE_SLIP_M,
        scenarios.RIGIDITY_PA,
    )
    assert rupture.magnitude == pytest.approx(round(expected, 2))
    assert rupture.magnitude >= 8.0
    bigger = scenarios.mht_hypothetical(length_km=400.0)
    assert bigger.magnitude > rupture.magnitude


def test_the_mht_rupture_reaches_the_surface() -> None:
    rupture = scenarios.mht_hypothetical()
    assert min(c[2] for c in rupture.corners) == 0.0
    d = geo.distances(rupture, (site("s", 85.2, 27.9),))
    assert d.ztor == 0.0


def test_a_stochastic_event_without_a_plane_becomes_a_point_rupture() -> None:
    rupture = scenarios.from_stochastic_event(
        event_id="etas-000001",
        magnitude=6.4,
        longitude=85.2,
        latitude=28.1,
        depth_km=12.0,
    )
    assert rupture.corners == ()
    assert rupture.hypothetical is True
    assert rupture.notes is not None
    assert "POINT rupture" in rupture.notes
    d = geo.distances(rupture, (site("s", 85.2, 28.1),))
    assert d.rjb[0] == pytest.approx(0.0, abs=1e-9)
    assert d.rrup[0] == pytest.approx(12.0, abs=1e-6)


def test_a_stochastic_event_with_a_plane_keeps_it() -> None:
    corners = scenarios.gorkha_2015_repeat(REPO_ROOT).corners
    rupture = scenarios.from_stochastic_event(
        event_id="etas-000002",
        magnitude=7.1,
        longitude=85.0,
        latitude=28.0,
        depth_km=14.0,
        corners=corners,
        source_ref="a stochastic event set",
    )
    assert rupture.corners == corners
    assert rupture.notes is not None
    assert "POINT" not in rupture.notes


def test_the_builtin_catalogue_is_what_the_cli_offers() -> None:
    catalogue = scenarios.builtin(REPO_ROOT)
    assert set(catalogue) == {"gorkha-2015-repeat", "mht-m8-hypothetical"}


def test_a_missing_fixture_fails_loudly(tmp_path: object) -> None:
    with pytest.raises(scenarios.ScenarioError, match="not committed"):
        scenarios.gorkha_2015_repeat(tmp_path)  # type: ignore[arg-type]
