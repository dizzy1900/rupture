"""The Chamoli / Ronti scenario: the layer's non-ShakeMap route, end to end and offline.

There is no published ground-failure product for this catchment, so nothing here asserts an
agreement with one. What it asserts is everything that can actually be wrong: the rupture is
declared hypothetical and its magnitude is computed rather than assumed, the window comes from
serac's own committed geometry, the shaking lands in a plausible band in the right units, the
masks fire where the assumed site condition says they must, the exposure is driven by the GSIM
field rather than by the Gorkha ShakeMap, and every caveat survives the trip.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.cascade import cases, chamoli
from rupture.cascade.coefficients import ZHU_2017_GENERAL
from rupture.domain.groundmotion import GroundMotionEngineId, GroundMotionField

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture(scope="module")
def window(repo_root: Path) -> chamoli.Window:
    return chamoli.aoi_window(repo_root)


@pytest.fixture(scope="module")
def fields(repo_root: Path, window: chamoli.Window) -> tuple[GroundMotionField, GroundMotionField]:
    return chamoli.ground_motion_fields(repo_root, window=window)


def test_the_window_is_derived_from_seracs_own_geometry(
    repo_root: Path, window: chamoli.Window
) -> None:
    """No coordinate in the scenario is typed in by hand; the AOI files define the extent."""
    assert window.derived_from
    assert any("chamoli-rishiganga" in item for item in window.derived_from)
    # serac's source zone is 79.68-79.80 E / 30.33-30.42 N and its two assets sit north of it
    assert window.min_longitude < 79.68 - 0.5 * chamoli.BUFFER_DEG
    assert window.max_longitude > 79.80
    assert window.max_latitude > 30.49  # the Tapovan asset, buffered
    lons, lats = window.lattice()
    assert lons.size == lats.size > 1000
    assert lons.min() >= window.min_longitude - 1e-9
    assert lats.max() <= window.max_latitude + 1e-9


def test_the_rupture_is_hypothetical_and_says_so(repo_root: Path) -> None:
    rupture_model = chamoli.scenario_rupture(repo_root)
    assert rupture_model.hypothetical is True
    assert rupture_model.id == chamoli.SCENARIO_ID
    assert "HYPOTHETICAL" in (rupture_model.notes or "")
    assert "not a forecast" in (rupture_model.notes or "")
    for assumption in chamoli.ASSUMPTIONS:
        assert assumption in (rupture_model.notes or "")
    assert any("Hanks" in ref for ref in rupture_model.source_refs)


def test_the_magnitude_is_computed_from_the_geometry_not_assumed(repo_root: Path) -> None:
    expected = chamoli.moment_magnitude(
        chamoli.LENGTH_KM * chamoli.DOWN_DIP_WIDTH_KM,
        chamoli.AVERAGE_SLIP_M,
        chamoli.RIGIDITY_PA,
    )
    assert chamoli.scenario_rupture(repo_root).magnitude == pytest.approx(expected, abs=5e-3)


def test_the_local_moment_magnitude_agrees_with_the_loss_layers(repo_root: Path) -> None:
    """The formula is duplicated to keep the cascade adapters off the loss layer; it must agree."""
    from rupture.risk.scenarios import moment_magnitude as risk_moment_magnitude  # noqa: PLC0415

    del repo_root
    for area, slip in ((625.0, 0.6), (10_000.0, 5.0), (120.0, 0.2)):
        assert chamoli.moment_magnitude(area, slip, chamoli.RIGIDITY_PA) == pytest.approx(
            risk_moment_magnitude(area, slip, chamoli.RIGIDITY_PA)
        )


def test_the_rupture_plane_is_closed_and_dips_as_stated(repo_root: Path) -> None:
    rupture_model = chamoli.scenario_rupture(repo_root)
    corners = rupture_model.corners
    assert len(corners) == 4
    depths = sorted({round(c[2], 6) for c in corners})
    assert depths[0] == pytest.approx(chamoli.TOP_DEPTH_KM)
    expected_bottom = chamoli.TOP_DEPTH_KM + chamoli.DOWN_DIP_WIDTH_KM * math.sin(
        math.radians(chamoli.DIP_DEG)
    )
    assert depths[-1] == pytest.approx(expected_bottom)


def test_the_shaking_comes_from_the_verified_native_gsim_in_the_right_units(
    fields: tuple[GroundMotionField, GroundMotionField],
) -> None:
    pgv, pga = fields
    assert pgv.engine is GroundMotionEngineId.NATIVE_GSIM
    assert pgv.gsim == chamoli.GSIM
    assert pgv.imt == "PGV"
    assert pga.imt == "PGA"
    assert pga.scenario_id == chamoli.SCENARIO_ID
    pga_values = pga.median()
    pgv_values = pgv.median()
    # PGA in g, PGV in cm/s: a factor-of-100 unit error cannot survive either band
    assert 0.02 < float(np.median(pga_values)) < 2.0
    assert 1.0 < float(np.median(pgv_values)) < 300.0
    assert np.all(np.isfinite(pga_values))
    assert np.all(pga_values > 0.0)
    assert all(site.vs30 == chamoli.ASSUMED_VS30_M_S for site in pga.sites)


def test_every_site_carries_the_assumed_vs30_and_the_record_says_it_is_assumed(
    fields: tuple[GroundMotionField, GroundMotionField],
) -> None:
    _, pga = fields
    assert all(site.vs30_measured is False for site in pga.sites)


def test_the_landslide_field_is_finite_and_declares_its_missing_covariates(
    repo_root: Path, window: chamoli.Window
) -> None:
    field = chamoli.run_case(repo_root, "landslide", window=window)
    coverage = np.array([c.probability for c in field.cells], dtype=np.float64)
    assert np.all(np.isfinite(coverage))
    assert 0.0 <= coverage.min() <= coverage.max() <= 1.0
    assert field.scenario_id == chamoli.SCENARIO_ID
    assert "INCOMPLETE" in (field.notes or "")
    assert "susceptibility" in (field.notes or "")
    assert "mask slope_deg: NOT APPLIED" in (field.notes or "")


def test_the_liquefaction_model_masks_the_whole_window_at_the_assumed_rock_vs30(
    repo_root: Path, window: chamoli.Window
) -> None:
    """760 m/s is above Zhu's vs30max of 620, so the model declines to speak. That is correct."""
    field = chamoli.run_case(repo_root, ZHU_2017_GENERAL.model_id, window=window)
    coverage = np.array([c.probability for c in field.cells], dtype=np.float64)
    assert coverage.max() == 0.0
    assert f"mask vs30_m_s: {coverage.size} cells zeroed" in (field.notes or "")


def test_the_exposure_is_driven_by_the_scenario_field_not_the_gorkha_shakemap(
    repo_root: Path, window: chamoli.Window
) -> None:
    record = chamoli.run_exposure(repo_root, window=window)
    assert record.scenario_id == chamoli.SCENARIO_ID
    assert record.aoi_id == chamoli.AOI_ID
    assert record.shaking_source is not None
    assert record.shaking_source.startswith(chamoli.SCENARIO_ID)
    assert "shakemap" not in record.shaking_source
    assert record.units
    assert "susceptibility" in record.label


def test_the_exposure_carries_the_downstream_assets_serac_maps_there(
    repo_root: Path, window: chamoli.Window
) -> None:
    """serac maps no settlement in this AOI: the receptors are the two hydropower projects."""
    record = chamoli.run_exposure(repo_root, window=window)
    unit = record.units[0]
    assert unit.settlements_below == ()
    assert any("rishiganga-hep" in a for a in unit.assets_below)
    assert any("tapovan-vishnugad-hep" in a for a in unit.assets_below)
    assert "serac maps no settlement in this AOI" in (record.notes or "")


def test_the_exposure_unit_carries_its_footprint(repo_root: Path, window: chamoli.Window) -> None:
    unit = chamoli.run_exposure(repo_root, window=window).units[0]
    assert len(unit.polygon) >= 4
    assert unit.polygon[0] == unit.polygon[-1], "the ring must be closed"
    assert unit.representative_longitude is not None
    assert unit.representative_latitude is not None


def test_the_terrain_screens_are_still_reported_as_not_applied(
    repo_root: Path, window: chamoli.Window
) -> None:
    """The fallback inventory has no slope or glacier cover, and the record must not hide that."""
    record = chamoli.run_exposure(repo_root, window=window)
    assert "steepness screen NOT applied" in (record.notes or "")
    assert "glacier screen NOT applied" in (record.notes or "")


def test_the_case_is_reachable_through_the_shared_route_registry(repo_root: Path) -> None:
    assert chamoli.SCENARIO_ID in cases.scenario_ids()
    shaking = cases.resolve(repo_root, scenario=chamoli.SCENARIO_ID)
    assert shaking.route == cases.SCENARIO_GSIM
    assert shaking.pgv.imt == "PGV"
    assert shaking.pga is not None
    assert shaking.magnitude == pytest.approx(chamoli.scenario_rupture(repo_root).magnitude)
