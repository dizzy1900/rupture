"""Where the shaking a ground-failure model runs on comes from.

The brief gives the layer two input routes — "ShakeMap grids from libcomcat for real events **or**
OpenQuake scenario GMFs for scenarios" — and this module is the seam that makes both reachable
from one command instead of only the first. Four routes, each carrying its own provenance:

``committed-shakemap``
    A committed slice of a published ShakeMap for a real event: the Gorkha reproduction case.
``scenario-gsim``
    A :class:`~rupture.domain.hazard.ScenarioRupture` evaluated through a verified GSIM
    (:mod:`rupture.adapters.groundmotion.native`, or the OpenQuake engine where the container can
    run): the Chamoli/Ronti case.
``shakemap-grid-xml``
    A real ShakeMap ``grid.xml`` on disk — whatever ``rupture cascade fetch-shakemap`` wrote, or
    a copy fetched by hand — parsed by :func:`rupture.adapters.cascade.shakemap.read_grid_xml`.
``supplied-field``
    A :class:`~rupture.domain.groundmotion.GroundMotionField` JSON produced anywhere else in
    rupture (the loss layer's scenario calculation, an OpenQuake run) and handed in as a file.

Nothing here manufactures shaking. Every route ends in a real grid, a verified GSIM, or a file the
caller produced; a route that cannot be satisfied raises rather than falling back to another one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

from rupture.adapters.cascade import chamoli, gorkha
from rupture.adapters.cascade.shakemap import ShakeMapGrid, read_grid_xml
from rupture.cascade.models import KIND_TO_MODEL
from rupture.cascade.models import build as build_model
from rupture.domain.cascade import CascadeKind
from rupture.domain.groundmotion import GroundMotionField

FloatArray = npt.NDArray[np.float64]

COMMITTED_SHAKEMAP = "committed-shakemap"
SCENARIO_GSIM = "scenario-gsim"
SHAKEMAP_GRID_XML = "shakemap-grid-xml"
SUPPLIED_FIELD = "supplied-field"


class ShakingUnavailableError(ValueError):
    """rupture holds no shaking for this request, and will not invent any."""


@dataclass(frozen=True, slots=True)
class Shaking:
    """The PGV and PGA fields a ground-failure model is evaluated on, and where they came from."""

    pgv: GroundMotionField
    pga: GroundMotionField | None
    magnitude: float | None
    cell_size_deg: float
    route: str
    description: str


@dataclass(frozen=True, slots=True)
class CaseSpec:
    """A scenario rupture knows how to run offline from committed inputs."""

    scenario_id: str
    route: str
    description: str


CASES: tuple[CaseSpec, ...] = (
    CaseSpec(
        scenario_id=gorkha.EVENT_ID,
        route=COMMITTED_SHAKEMAP,
        description=(
            "2015 Gorkha, Nepal (ComCat us20002926): the committed slice of the published USGS "
            "ShakeMap Atlas grid, sampled at the published ground-failure product's own cells"
        ),
    ),
    CaseSpec(
        scenario_id=chamoli.SCENARIO_ID,
        route=SCENARIO_GSIM,
        description=(
            "Chamoli / Ronti Gad (serac AOI chamoli-rishiganga): a HYPOTHETICAL Main Himalayan "
            "Thrust patch beneath the catchment, through the verified native GSIM. No published "
            "ground-failure product exists for this region; see docs/CASCADE.md section 3.5"
        ),
    ),
)

CASE_BY_ID: dict[str, CaseSpec] = {case.scenario_id: case for case in CASES}


def scenario_ids() -> tuple[str, ...]:
    return tuple(case.scenario_id for case in CASES)


def read_ground_motion_field(path: Path) -> GroundMotionField:
    """A :class:`GroundMotionField` from its own JSON (the ``ground-motion-field.v0`` contract)."""
    return GroundMotionField.model_validate_json(path.read_text(encoding="utf-8"))


def _grid_points(grid: ShakeMapGrid, stride: int) -> tuple[FloatArray, FloatArray]:
    if stride < 1:
        msg = f"stride must be at least 1, got {stride}"
        raise ShakingUnavailableError(msg)
    lons = grid.longitudes[::stride]
    lats = grid.latitudes[::stride]
    mesh_lon, mesh_lat = np.meshgrid(lons, lats)
    return mesh_lon.ravel(), mesh_lat.ravel()


def from_grid_xml(
    path: Path,
    *,
    scenario_id: str | None = None,
    stride: int = 1,
    source_url: str | None = None,
    source_sha256: str | None = None,
) -> Shaking:
    """Shaking from a real ShakeMap ``grid.xml`` on disk, on the grid's own cell centres."""
    grid = read_grid_xml(path, source_url=source_url, source_sha256=source_sha256)
    lons, lats = _grid_points(grid, stride)
    event = scenario_id or grid.event_id
    cell_size = (
        float(abs(grid.longitudes[1] - grid.longitudes[0])) * stride
        if grid.longitudes.size > 1
        else 1.0 / 60.0
    )
    return Shaking(
        pgv=grid.ground_motion_field(imt="PGV", lons=lons, lats=lats, scenario_id=event),
        pga=grid.ground_motion_field(imt="PGA", lons=lons, lats=lats, scenario_id=event),
        magnitude=grid.magnitude,
        cell_size_deg=cell_size,
        route=SHAKEMAP_GRID_XML,
        description=f"ShakeMap grid.xml at {path} (event {grid.event_id}), every {stride} cell(s)",
    )


def from_fields(
    pgv_path: Path, pga_path: Path | None = None, *, magnitude: float | None = None
) -> Shaking:
    """Shaking from GroundMotionField JSON files produced elsewhere in rupture."""
    pgv = read_ground_motion_field(pgv_path)
    if pgv.imt.upper() != "PGV":
        msg = f"{pgv_path} carries imt={pgv.imt!r}; the ground-failure models need a PGV field"
        raise ShakingUnavailableError(msg)
    pga = read_ground_motion_field(pga_path) if pga_path is not None else None
    if pga is not None and pga.imt.upper() != "PGA":
        msg = f"{pga_path} carries imt={pga.imt!r}, expected PGA"
        raise ShakingUnavailableError(msg)
    return Shaking(
        pgv=pgv,
        pga=pga,
        magnitude=magnitude,
        cell_size_deg=1.0 / 60.0,
        route=SUPPLIED_FIELD,
        description=(
            f"supplied ground-motion field {pgv.id} "
            f"({pgv.engine.value} {pgv.engine_version}, gsim {pgv.gsim})"
            + (f" with PGA field {pga.id}" if pga is not None else "; no PGA field supplied")
        ),
    )


def gorkha_shaking(repo_root: Path, *, model_id: str) -> Shaking:
    """The committed Gorkha ShakeMap slice, sampled at the published product's own cells."""
    case = gorkha.CASE_FOR_MODEL[model_id]
    shakemap = gorkha.load_shakemap(repo_root)
    published = gorkha.load_published(repo_root, case)
    return Shaking(
        pgv=shakemap.ground_motion_field(
            imt="PGV",
            lons=published.longitudes,
            lats=published.latitudes,
            scenario_id=gorkha.EVENT_ID,
        ),
        pga=shakemap.ground_motion_field(
            imt="PGA",
            lons=published.longitudes,
            lats=published.latitudes,
            scenario_id=gorkha.EVENT_ID,
        ),
        magnitude=gorkha.MAGNITUDE,
        cell_size_deg=case.cell_size_deg,
        route=COMMITTED_SHAKEMAP,
        description=CASE_BY_ID[gorkha.EVENT_ID].description,
    )


def chamoli_shaking(repo_root: Path) -> Shaking:
    """The Chamoli/Ronti hypothetical scenario, through the verified native GSIM."""
    window = chamoli.aoi_window(repo_root)
    rupture_model = chamoli.scenario_rupture(repo_root)
    pgv, pga = chamoli.ground_motion_fields(repo_root, window=window, rupture=rupture_model)
    return Shaking(
        pgv=pgv,
        pga=pga,
        magnitude=rupture_model.magnitude,
        cell_size_deg=window.cell_size_deg,
        route=SCENARIO_GSIM,
        description=CASE_BY_ID[chamoli.SCENARIO_ID].description,
    )


def exposure_pga(
    repo_root: Path,
    *,
    scenario: str | None,
    lons: FloatArray,
    lats: FloatArray,
    pga_field: Path | None = None,
    grid_xml: Path | None = None,
) -> tuple[GroundMotionField, str]:
    """The PGA field the slope-unit overlay screens on, and the route it came from.

    A grid-backed route is sampled **at the slope units' own representative points**, which is
    exact; a lattice-backed route (a GSIM scenario, or a field supplied as a file) is used as it
    stands and the overlay takes each unit's nearest site. Sampling a ShakeMap outside its own
    grid raises, as it does everywhere else in this layer: rupture does not extrapolate one.
    """
    if pga_field is not None:
        field = read_ground_motion_field(pga_field)
        if field.imt.upper() != "PGA":
            msg = f"{pga_field} carries imt={field.imt!r}, expected PGA"
            raise ShakingUnavailableError(msg)
        return field, SUPPLIED_FIELD
    if grid_xml is not None:
        grid = read_grid_xml(grid_xml)
        return (
            grid.ground_motion_field(
                imt="PGA", lons=lons, lats=lats, scenario_id=scenario or grid.event_id
            ),
            SHAKEMAP_GRID_XML,
        )
    if scenario == chamoli.SCENARIO_ID:
        _, pga = chamoli.ground_motion_fields(repo_root)
        return pga, SCENARIO_GSIM
    if scenario is None or scenario == gorkha.EVENT_ID:
        grid = gorkha.load_shakemap(repo_root)
        return (
            grid.ground_motion_field(
                imt="PGA", lons=lons, lats=lats, scenario_id=scenario or gorkha.EVENT_ID
            ),
            COMMITTED_SHAKEMAP,
        )
    known = ", ".join(scenario_ids())
    msg = (
        f"rupture has no ground-motion field for scenario {scenario!r}. Committed cases: {known}. "
        f"Supply one with --grid-xml or --pga-field; rupture does not invent a field."
    )
    raise ShakingUnavailableError(msg)


def resolve(
    repo_root: Path,
    *,
    scenario: str | None,
    model_id: str | None = None,
    pgv_field: Path | None = None,
    pga_field: Path | None = None,
    grid_xml: Path | None = None,
    stride: int = 1,
    magnitude: float | None = None,
) -> Shaking:
    """Pick a route and return the shaking, or say precisely why there is none.

    Explicit inputs win over the committed cases: a supplied ``--pgv-field`` or ``--grid-xml`` is
    what the caller asked for. Where neither is given, ``scenario`` must name one of
    :func:`scenario_ids`.
    """
    if pgv_field is not None:
        return from_fields(pgv_field, pga_field, magnitude=magnitude)
    if grid_xml is not None:
        return from_grid_xml(grid_xml, scenario_id=scenario, stride=stride)
    if scenario is None:
        msg = "no shaking requested: pass --scenario, --pgv-field or --grid-xml"
        raise ShakingUnavailableError(msg)
    if scenario == gorkha.EVENT_ID:
        resolved = model_id or KIND_TO_MODEL[CascadeKind.LANDSLIDE]
        return gorkha_shaking(repo_root, model_id=build_model(resolved).model_id)
    if scenario == chamoli.SCENARIO_ID:
        return chamoli_shaking(repo_root)
    known = ", ".join(scenario_ids())
    msg = (
        f"rupture has no ground-motion field for scenario {scenario!r}. Committed cases: {known}. "
        f"For any other event or scenario, supply the shaking: --grid-xml <ShakeMap grid.xml> "
        f"(see `rupture cascade fetch-shakemap`) or --pgv-field/--pga-field "
        f"<ground-motion-field.v0 JSON>. rupture does not invent a field."
    )
    raise ShakingUnavailableError(msg)
