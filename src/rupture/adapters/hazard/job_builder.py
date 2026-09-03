"""Render the typed hazard jobs to OpenQuake ``job.ini`` text.

Pure: no I/O, no Docker. Key names follow the OpenQuake engine manual (user guide, "Configuration
file", common hazard / classical PSHA / scenario hazard pages) and the bundled demo
``demos/hazard/AreaSourceClassicalPSHA/job.ini``. The engine flattens every ``[section]`` into one
parameter dictionary (``openquake.commonlib.readinput.get_params``), so section names are the
conventional ones and carry no meaning of their own.

File references are written as bare file names; :class:`~rupture.adapters.hazard.openquake_docker`
copies the referenced inputs next to the rendered ``job.ini``.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from rupture.ports.hazard_engine import ClassicalPSHAJob, ScenarioGroundMotionJob

JOB_INI = "job.ini"
EXPORT_SUBDIR = "out"
"""Where exports land, relative to the work directory (``export_dir`` in ``[output]``)."""


class JobBuilderError(ValueError):
    """The job cannot be rendered to a valid ``job.ini``."""


@dataclass(frozen=True, slots=True)
class ErfSettings:
    """Discretisation of the earthquake rupture forecast (``[erf]`` section).

    Not part of :class:`ClassicalPSHAJob`; defaults follow the classical PSHA page of the manual.
    """

    rupture_mesh_spacing_km: float = 5.0
    width_of_mfd_bin: float = 0.1
    area_source_discretization_km: float = 10.0


@dataclass(frozen=True, slots=True)
class SiteDepthSettings:
    """Reference basin depths for uniform site conditions (``[site_params]``).

    ``ClassicalPSHAJob`` carries only ``reference_vs30``; the two depth parameters default to
    the values used by the bundled demo.
    """

    depth_to_2pt5km_per_sec_km: float = 5.0
    depth_to_1pt0km_per_sec_m: float = 100.0
    vs30_type: str = "measured"


_WKT_POLYGON = re.compile(
    r"^\s*POLYGON\s*\(\s*\((?P<ring>[^()]*)\)\s*(?P<rest>.*)\)\s*$", re.I | re.S
)


def wkt_polygon_to_region(wkt: str) -> str:
    """Convert a single-ring WKT ``POLYGON`` to OpenQuake's ``region`` value (``lon lat, ...``).

    OpenQuake wants an open ring (the closing vertex is dropped) with at least three vertices.
    Holes and multipolygons are rejected: the engine's ``region`` is one simple polygon.
    """
    match = _WKT_POLYGON.match(wkt)
    if match is None:
        msg = f"region_wkt must be a WKT POLYGON with one ring, got {wkt[:60]!r}"
        raise JobBuilderError(msg)
    if match.group("rest").strip():
        msg = "region_wkt must not contain interior rings"
        raise JobBuilderError(msg)
    vertices: list[tuple[float, float]] = []
    for raw in match.group("ring").split(","):
        parts = raw.split()
        if len(parts) < 2:
            msg = f"malformed WKT vertex {raw.strip()!r}"
            raise JobBuilderError(msg)
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError as exc:
            msg = f"malformed WKT vertex {raw.strip()!r}"
            raise JobBuilderError(msg) from exc
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            msg = f"WKT vertex out of range: {(lon, lat)}"
            raise JobBuilderError(msg)
        vertices.append((lon, lat))
    if len(vertices) >= 2 and vertices[0] == vertices[-1]:
        vertices.pop()
    if len(vertices) < 3:
        msg = "region polygon needs at least three distinct vertices"
        raise JobBuilderError(msg)
    return ", ".join(f"{lon:g} {lat:g}" for lon, lat in vertices)


def _fmt(value: float) -> str:
    return repr(float(value))


def _imtls(imts: dict[str, tuple[float, ...]]) -> str:
    if not imts:
        msg = "at least one intensity measure type is required"
        raise JobBuilderError(msg)
    for imt, levels in imts.items():
        if not imt.strip():
            msg = "empty IMT name"
            raise JobBuilderError(msg)
        if len(levels) < 1 or any(lv <= 0.0 for lv in levels):
            msg = f"{imt}: intensity measure levels must be positive"
            raise JobBuilderError(msg)
        if any(b <= a for a, b in pairwise(levels)):
            msg = f"{imt}: intensity measure levels must be strictly increasing"
            raise JobBuilderError(msg)
    return json.dumps({imt: list(levels) for imt, levels in imts.items()})


def _render(sections: list[tuple[str, list[tuple[str, str]]]]) -> str:
    lines: list[str] = []
    for name, items in sections:
        lines.append(f"[{name}]")
        lines.extend(f"{key} = {value}" for key, value in items)
        lines.append("")
    return "\n".join(lines)


def classical_job_ini(
    job: ClassicalPSHAJob,
    *,
    erf: ErfSettings | None = None,
    site: SiteDepthSettings | None = None,
) -> str:
    """``job.ini`` text for a classical PSHA run (``calculation_mode = classical``).

    Exactly one site definition is accepted: ``sites_csv`` or ``region_wkt`` together with
    ``region_grid_spacing_km``.
    """
    erf = erf or ErfSettings()
    site = site or SiteDepthSettings()
    geometry: list[tuple[str, str]]
    if job.sites_csv is not None:
        if job.region_wkt is not None or job.region_grid_spacing_km is not None:
            msg = "give either sites_csv or region_wkt + region_grid_spacing_km, not both"
            raise JobBuilderError(msg)
        geometry = [("sites_csv", job.sites_csv.name)]
    elif job.region_wkt is not None:
        if job.region_grid_spacing_km is None:
            msg = "region_wkt requires region_grid_spacing_km"
            raise JobBuilderError(msg)
        geometry = [
            ("region", wkt_polygon_to_region(job.region_wkt)),
            ("region_grid_spacing", _fmt(job.region_grid_spacing_km)),
        ]
    else:
        msg = "a classical job needs sites_csv or region_wkt + region_grid_spacing_km"
        raise JobBuilderError(msg)

    sections = [
        (
            "general",
            [
                ("description", " ".join(job.description.split())),
                ("calculation_mode", "classical"),
                ("random_seed", str(job.random_seed)),
            ],
        ),
        ("geometry", geometry),
        ("logic_tree", [("number_of_logic_tree_samples", str(job.number_of_logic_tree_samples))]),
        (
            "erf",
            [
                ("rupture_mesh_spacing", _fmt(erf.rupture_mesh_spacing_km)),
                ("width_of_mfd_bin", _fmt(erf.width_of_mfd_bin)),
                ("area_source_discretization", _fmt(erf.area_source_discretization_km)),
            ],
        ),
        ("site_params", _site_params(job.reference_vs30, site)),
        (
            "calculation",
            [
                ("source_model_logic_tree_file", job.source_model_logic_tree.name),
                ("gsim_logic_tree_file", job.gsim_logic_tree.name),
                ("investigation_time", _fmt(job.investigation_time_years)),
                ("intensity_measure_types_and_levels", _imtls(job.imts)),
                ("truncation_level", _fmt(job.truncation_level)),
                ("maximum_distance", _fmt(job.maximum_distance_km)),
            ],
        ),
        (
            "output",
            [
                ("export_dir", EXPORT_SUBDIR),
                ("mean", "true"),
                ("hazard_maps", "false"),
                ("uniform_hazard_spectra", "false"),
            ],
        ),
    ]
    return _render(sections)


def scenario_job_ini(job: ScenarioGroundMotionJob, *, rupture_mesh_spacing_km: float = 2.0) -> str:
    """``job.ini`` text for a scenario ground-motion run (``calculation_mode = scenario``)."""
    if not job.imts:
        msg = "at least one intensity measure type is required"
        raise JobBuilderError(msg)
    if not job.gsim.strip():
        msg = "gsim must name a ground-shaking intensity model"
        raise JobBuilderError(msg)
    sections = [
        (
            "general",
            [
                ("description", " ".join(job.description.split())),
                ("calculation_mode", "scenario"),
                ("random_seed", str(job.random_seed)),
            ],
        ),
        ("geometry", [("sites_csv", job.sites_csv.name)]),
        (
            "rupture",
            [
                ("rupture_model_file", job.rupture_model.name),
                ("rupture_mesh_spacing", _fmt(rupture_mesh_spacing_km)),
            ],
        ),
        ("site_params", _site_params(job.reference_vs30, SiteDepthSettings())),
        (
            "calculation",
            [
                ("intensity_measure_types", ", ".join(job.imts)),
                ("gsim", job.gsim),
                ("number_of_ground_motion_fields", str(job.number_of_ground_motion_fields)),
                ("truncation_level", _fmt(job.truncation_level)),
                ("maximum_distance", _fmt(job.maximum_distance_km)),
            ],
        ),
        ("output", [("export_dir", EXPORT_SUBDIR)]),
    ]
    return _render(sections)


def _site_params(vs30: float, site: SiteDepthSettings) -> list[tuple[str, str]]:
    return [
        ("reference_vs30_type", site.vs30_type),
        ("reference_vs30_value", _fmt(vs30)),
        ("reference_depth_to_2pt5km_per_sec", _fmt(site.depth_to_2pt5km_per_sec_km)),
        ("reference_depth_to_1pt0km_per_sec", _fmt(site.depth_to_1pt0km_per_sec_m)),
    ]


def referenced_inputs(job: ClassicalPSHAJob | ScenarioGroundMotionJob) -> dict[str, Path]:
    """File name → source path for every input the rendered ``job.ini`` names.

    Raises when two inputs would collide on the same bare file name.
    """
    paths: list[Path]
    if isinstance(job, ClassicalPSHAJob):
        paths = [job.source_model_logic_tree, job.gsim_logic_tree]
        if job.sites_csv is not None:
            paths.append(job.sites_csv)
    else:
        paths = [job.rupture_model, job.sites_csv]
    out: dict[str, Path] = {}
    for p in paths:
        if p.name in out and out[p.name] != p:
            msg = f"two inputs share the file name {p.name!r}: {out[p.name]} and {p}"
            raise JobBuilderError(msg)
        out[p.name] = p
    return out


def referenced_source_models(logic_tree_xml: str) -> list[str]:
    """Relative file names named by ``<uncertaintyModel>`` elements of a source-model logic tree.

    A branch may list several files separated by whitespace; only tokens ending in ``.xml``
    are returned, in document order, without duplicates.
    """
    root = ET.fromstring(logic_tree_xml)  # trusted local NRML
    seen: list[str] = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "uncertaintyModel" or not el.text:
            continue
        for token in el.text.split():
            if token.lower().endswith(".xml") and token not in seen:
                seen.append(token)
    return seen
