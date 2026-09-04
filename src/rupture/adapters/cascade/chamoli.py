"""The Chamoli / Ronti Gad scenario case: the cascade layer's non-ShakeMap route.

Gorkha (:mod:`rupture.adapters.cascade.gorkha`) drives the ground-failure models from a
**published ShakeMap grid** for a real event. This module drives them from a **scenario rupture
through a GSIM**, which is the layer's other declared input route, over the catchment serac maps
as ``chamoli-rishiganga`` — the Ronti Gad / Rishiganga / Dhauliganga corridor of the 7 February
2021 rock and ice avalanche.

What this case is, stated before anything else
----------------------------------------------

*The 2021 Chamoli disaster was not earthquake-triggered.* It was a rock and ice avalanche from
the north face of Ronti Peak; no earthquake preceded it, no ShakeMap exists for it, and the USGS
has published no ``ground-failure`` product for this catchment. There is therefore **no published
answer here to be validated against**, in the sense that the Gorkha case is validated against one.

What this case does is different and is not dressed up as more:

1. it exercises the scenario route end to end — a documented :class:`ScenarioRupture`, the
   verified native GSIM (ADR-0020), PGA and PGV fields, both USGS ground-failure models, and the
   serac slope-unit exposure overlay — on a region the layer exists for;
2. it puts the co-seismic ice/rock avalanche mechanism over a real catchment whose downstream
   receptors serac has actually mapped (two hydropower projects, destroyed in 2021 by a
   non-seismic avalanche of exactly the mechanism this layer screens for);
3. it gives the gate a set of checks that can genuinely fail: unit errors, an unwired mask, a
   static term that stopped being reported, an exposure record that silently fell back to the
   Gorkha ShakeMap.

Every number defining the rupture is an **assumption**, marked ``hypothetical=True`` and listed
in ``ASSUMPTIONS`` below. Nothing here is a published rupture model, and no part of it is a
statement that an earthquake of this size occurs beneath this catchment at any rate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from rupture.adapters.cascade.serac import (
    DEFAULT_PGA_THRESHOLD_G,
    DEFAULT_STEEP_SLOPE_DEG,
    SeracSlopeUnitSource,
)
from rupture.adapters.groundmotion.distances import from_local_frame
from rupture.adapters.groundmotion.native import NativeGsimEngine
from rupture.cascade.models import LogisticGroundFailureModel
from rupture.cascade.models import build as build_model
from rupture.domain.cascade import CascadeExposure, GroundFailureField
from rupture.domain.groundmotion import GroundMotionField, Site
from rupture.domain.hazard import ScenarioRupture

FloatArray = npt.NDArray[np.float64]

AOI_ID = "chamoli-rishiganga"
SCENARIO_ID = "chamoli-ronti-mht-hypothetical"
GSIM = "BooreEtAl2014"
"""The only active-shallow-crust GSIM rupture ships verified (ADR-0020, ADR-0033)."""

# ------------------------------------------------------------------ the rupture, all assumed
STRIKE_DEG = 293.0
DIP_DEG = 7.0
RAKE_DEG = 101.0
LENGTH_KM = 25.0
DOWN_DIP_WIDTH_KM = 25.0
TOP_DEPTH_KM = 10.0
AVERAGE_SLIP_M = 0.6
RIGIDITY_PA = 3.3e10

ASSUMPTIONS: tuple[str, ...] = (
    f"strike {STRIKE_DEG:g} deg, dip {DIP_DEG:g} deg, rake {RAKE_DEG:g} deg: the Main Himalayan "
    "Thrust decollement geometry resolved for central Nepal (rupture's own MHT scenario in "
    "src/rupture/risk/scenarios.py and its citations), ADOPTED for Garhwal without a "
    "Garhwal-specific inversion. rupture holds no published rupture model for this catchment.",
    f"a {LENGTH_KM:g} x {DOWN_DIP_WIDTH_KM:g} km patch of that decollement with its top at "
    f"{TOP_DEPTH_KM:g} km: a mid-crustal, non-surface-rupturing patch. Extent and depth are "
    "modelling choices, not observations.",
    f"average slip {AVERAGE_SLIP_M:g} m and rigidity {RIGIDITY_PA:.1e} Pa, from which the "
    "magnitude is COMPUTED by Hanks and Kanamori (1979) rather than assumed, so the geometry "
    "and the magnitude cannot disagree.",
    "the patch is centred beneath the centroid of serac's chamoli-rishiganga source zone, "
    "because the question the scenario asks is 'what would shaking of this size directly "
    "beneath this catchment do to the screen', not 'where is the next rupture'.",
    "site Vs30 is a single assumed value (see ASSUMED_VS30_M_S); rupture holds no Vs30 raster "
    "for Garhwal and refuses to invent a spatially varying one.",
)

ASSUMED_VS30_M_S = 760.0
"""Vs30 at every site, m/s. **Assumed, not measured.**

760 m/s is the NEHRP B/C boundary, the reference site condition both shipped GSIMs are anchored
on and the value used when nothing site-specific is available. rupture holds no Vs30 raster for
Garhwal: the ShakeMap ``SVEL`` band that the Gorkha case uses exists only where a ShakeMap does,
and this is a scenario, not an event. A single reference value is therefore used and labelled,
rather than a spatially varying field being manufactured.

Consequence, and it is the honest one: 760 m/s is above the Zhu et al. (2017) ``vs30max`` of 620
m/s, so the liquefaction model masks **every** cell of this window. That is the published model
declining to speak about a rock-site mountain catchment, which is the right answer here and is
reported as such rather than being tuned away.
"""

HANKS_KANAMORI = (
    "Hanks, T.C. & Kanamori, H. (1979). A moment magnitude scale. Journal of Geophysical "
    "Research 84(B5), 2348-2350. doi:10.1029/JB084iB05p02348"
)
SOURCE_REFS: tuple[str, ...] = (
    HANKS_KANAMORI,
    "serac AOI chamoli-rishiganga (github.com/dizzy1900/serac, Apache-2.0), committed verbatim "
    "under tests/fixtures/cascade/serac/ with its provenance",
)

# ------------------------------------------------------------------ the evaluation window
BUFFER_DEG = 0.06
"""Margin added around the AOI's own extent so the distance decay of the field is visible."""

CELL_SIZE_DEG = 1.0 / 240.0
"""Grid spacing, degrees (~460 m at this latitude).

The two published USGS products are computed at different native resolutions (1/240 deg for Zhu,
1/480 deg for Nowicki Jessee). Neither is being reproduced here, so rupture uses one grid for
both models and says which, rather than implying a correspondence with a product that does not
exist for this region.
"""


def moment_magnitude(area_km2: float, average_slip_m: float, rigidity_pa: float) -> float:
    """Hanks & Kanamori (1979): ``Mw = (2/3)(log10 M0 - 9.1)`` with ``M0 = mu A D`` in N m.

    Deliberately a local three-line function rather than an import from ``rupture.risk``: the
    cascade adapters do not depend on the loss layer. ``tests/unit/cascade/test_chamoli_scenario``
    asserts the two implementations agree.
    """
    moment = rigidity_pa * area_km2 * 1.0e6 * average_slip_m
    return (2.0 / 3.0) * (math.log10(moment) - 9.1)


@dataclass(frozen=True, slots=True)
class Window:
    """The lon/lat lattice a scenario field is evaluated on, and where it came from."""

    min_longitude: float
    max_longitude: float
    min_latitude: float
    max_latitude: float
    cell_size_deg: float
    derived_from: tuple[str, ...]

    def centre(self) -> tuple[float, float]:
        return (
            0.5 * (self.min_longitude + self.max_longitude),
            0.5 * (self.min_latitude + self.max_latitude),
        )

    def lattice(self) -> tuple[FloatArray, FloatArray]:
        """Cell centres, row-major with latitude descending (the ShakeMap row order)."""
        lons = np.arange(
            self.min_longitude, self.max_longitude + 0.5 * self.cell_size_deg, self.cell_size_deg
        )
        lats = np.arange(
            self.max_latitude, self.min_latitude - 0.5 * self.cell_size_deg, -self.cell_size_deg
        )
        grid_lon, grid_lat = np.meshgrid(lons, lats)
        return grid_lon.ravel(), grid_lat.ravel()


def aoi_window(
    repo_root: Path,
    *,
    buffer_deg: float = BUFFER_DEG,
    cell_size_deg: float = CELL_SIZE_DEG,
    source: SeracSlopeUnitSource | None = None,
) -> Window:
    """The evaluation window, derived from serac's committed AOI files and nothing else.

    The extent is the union of every slope-unit footprint and every exposed asset serac maps for
    the AOI, buffered by ``buffer_deg``. No coordinate in this module is typed in by hand.
    """
    src = source or SeracSlopeUnitSource(repo_root=repo_root)
    inventory = src.inventory(AOI_ID)
    lons: list[float] = []
    lats: list[float] = []
    for unit in inventory.units:
        geometry = unit.get("geometry") or {}
        ring = geometry.get("coordinates", [[]])
        flat = ring[0] if geometry.get("type") == "Polygon" else ring[0][0]
        for point in flat:
            lons.append(float(point[0]))
            lats.append(float(point[1]))
    for _, _, lon, lat in src.exposed_assets(AOI_ID):
        lons.append(lon)
        lats.append(lat)
    if not lons:
        msg = f"serac's AOI {AOI_ID!r} carries no geometry to build a window from"
        raise ValueError(msg)
    return Window(
        min_longitude=min(lons) - buffer_deg,
        max_longitude=max(lons) + buffer_deg,
        min_latitude=min(lats) - buffer_deg,
        max_latitude=max(lats) + buffer_deg,
        cell_size_deg=cell_size_deg,
        derived_from=(*inventory.derived_from, f"serac AOI {AOI_ID} exposed assets"),
    )


def scenario_rupture(
    repo_root: Path, *, source: SeracSlopeUnitSource | None = None
) -> ScenarioRupture:
    """The hypothetical MHT patch beneath the Ronti Gad / Rishiganga catchment.

    HYPOTHETICAL. The magnitude is computed from the stated area and slip; nothing about this
    rupture is observed, and ``ScenarioRupture.hypothetical`` is True so no consumer can lose
    that.
    """
    window = aoi_window(repo_root, source=source)
    centre_lon, centre_lat = window.centre()
    magnitude = moment_magnitude(LENGTH_KM * DOWN_DIP_WIDTH_KM, AVERAGE_SLIP_M, RIGIDITY_PA)

    dip = math.radians(DIP_DEG)
    strike = math.radians(STRIKE_DEG)
    along = (math.sin(strike), math.cos(strike))
    down_dip = (math.cos(strike), -math.sin(strike))
    horizontal = DOWN_DIP_WIDTH_KM * math.cos(dip)
    bottom_depth = TOP_DEPTH_KM + DOWN_DIP_WIDTH_KM * math.sin(dip)
    local = (
        (-0.5 * LENGTH_KM, -0.5 * horizontal, TOP_DEPTH_KM),
        (0.5 * LENGTH_KM, -0.5 * horizontal, TOP_DEPTH_KM),
        (0.5 * LENGTH_KM, 0.5 * horizontal, bottom_depth),
        (-0.5 * LENGTH_KM, 0.5 * horizontal, bottom_depth),
    )
    xs = np.array([a * along[0] + b * down_dip[0] for a, b, _ in local])
    ys = np.array([a * along[1] + b * down_dip[1] for a, b, _ in local])
    lons, lats = from_local_frame(centre_lon, centre_lat, xs, ys)
    corners = tuple(
        (float(lon), float(lat), float(depth))
        for lon, lat, (_, _, depth) in zip(lons, lats, local, strict=True)
    )
    return ScenarioRupture(
        id=SCENARIO_ID,
        magnitude=round(magnitude, 2),
        hypocentre_longitude=centre_lon,
        hypocentre_latitude=centre_lat,
        hypocentre_depth_km=0.5 * (TOP_DEPTH_KM + bottom_depth),
        strike=STRIKE_DEG,
        dip=DIP_DEG,
        rake=RAKE_DEG,
        tectonic_region="Active Shallow Crust",
        corners=corners,
        source_refs=SOURCE_REFS,
        hypothetical=True,
        notes=(
            "HYPOTHETICAL. A "
            f"{LENGTH_KM:g} x {DOWN_DIP_WIDTH_KM:g} km patch of the Main Himalayan Thrust "
            f"decollement, top at {TOP_DEPTH_KM:g} km, centred beneath serac's "
            f"{AOI_ID} source zone; magnitude computed from that area and {AVERAGE_SLIP_M:g} m "
            "average slip. Not a published rupture model, not a forecast, and not a statement "
            "that an event of this size occurs here. Assumptions: " + " | ".join(ASSUMPTIONS)
        ),
    )


def sites(window: Window, *, vs30_m_s: float = ASSUMED_VS30_M_S) -> tuple[Site, ...]:
    """One site per grid cell, all at the same assumed Vs30 (see :data:`ASSUMED_VS30_M_S`)."""
    lons, lats = window.lattice()
    return tuple(
        Site(
            id=str(index),
            longitude=float(lon),
            latitude=float(lat),
            vs30=vs30_m_s,
            vs30_measured=False,
        )
        for index, (lon, lat) in enumerate(zip(lons, lats, strict=True))
    )


def ground_motion_fields(
    repo_root: Path,
    *,
    window: Window | None = None,
    rupture: ScenarioRupture | None = None,
    vs30_m_s: float = ASSUMED_VS30_M_S,
    engine: NativeGsimEngine | None = None,
) -> tuple[GroundMotionField, GroundMotionField]:
    """``(pgv_field, pga_field)`` for the scenario, from the verified native GSIM.

    Median fields (one realisation): the ground-failure models are deterministic functions of the
    shaking, and rupture does not propagate the GSIM's aleatory variability into a susceptibility
    product it has no uncertainty model for (docs/CASCADE.md, limitation 7).
    """
    grid = window or aoi_window(repo_root)
    source_rupture = rupture or scenario_rupture(repo_root)
    gsim_engine = engine or NativeGsimEngine()
    site_tuple = sites(grid, vs30_m_s=vs30_m_s)
    pgv = gsim_engine.scenario(source_rupture, site_tuple, imt="PGV", gsim=GSIM, n_realisations=1)
    pga = gsim_engine.scenario(source_rupture, site_tuple, imt="PGA", gsim=GSIM, n_realisations=1)
    return pgv, pga


def model_for(model_id: str, *, cell_size_deg: float = CELL_SIZE_DEG) -> LogisticGroundFailureModel:
    return build_model(model_id, cell_size_deg=cell_size_deg)


def run_case(
    repo_root: Path,
    model_id: str = "landslide",
    *,
    window: Window | None = None,
    vs30_m_s: float = ASSUMED_VS30_M_S,
) -> GroundFailureField:
    """Evaluate one ground-failure model over the scenario's shaking."""
    grid = window or aoi_window(repo_root)
    rupture = scenario_rupture(repo_root)
    pgv, pga = ground_motion_fields(repo_root, window=grid, rupture=rupture, vs30_m_s=vs30_m_s)
    model = model_for(model_id, cell_size_deg=grid.cell_size_deg)
    return model.evaluate(pgv, scenario_id=SCENARIO_ID, pga_field=pga, magnitude=rupture.magnitude)


def run_exposure(
    repo_root: Path,
    *,
    pga_threshold_g: float | None = None,
    steep_slope_deg: float | None = None,
    window: Window | None = None,
    vs30_m_s: float = ASSUMED_VS30_M_S,
    source: SeracSlopeUnitSource | None = None,
) -> CascadeExposure:
    """The co-seismic ice/rock avalanche screen over the AOI, driven by the scenario field."""
    src = source or SeracSlopeUnitSource(repo_root=repo_root)
    grid = window or aoi_window(repo_root, source=src)
    _, pga = ground_motion_fields(repo_root, window=grid, vs30_m_s=vs30_m_s)
    return src.exposure(
        pga,
        aoi_id=AOI_ID,
        pga_threshold_g=DEFAULT_PGA_THRESHOLD_G if pga_threshold_g is None else pga_threshold_g,
        steep_slope_deg=DEFAULT_STEEP_SLOPE_DEG if steep_slope_deg is None else steep_slope_deg,
        scenario_id=SCENARIO_ID,
    )
