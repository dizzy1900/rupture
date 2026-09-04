"""The authoritative event-based path: OpenQuake's ``event_based`` calculator (ADR-0043).

The scenario calculator answers "what does *this* rupture do?". The event-based calculator
answers "what does a rate model do over an investigation time?" — it samples a stochastic event
set from a source model, computes a ground-motion field for every sampled rupture, and hands back
the events with the rate each carries. That is the engine-side route to an annual loss and to a
loss exceedance curve, and it is the counterpart of rupture's native route through
:mod:`rupture.risk.event_set`.

Both routes exist on purpose and they are not redundant:

* the **native** route samples the event set from a promoted F1 forecast (an ETAS
  ``ForecastGrid``), which is the whole point of rupture having a forecasting half. OpenQuake has
  no notion of a time-dependent gridded forecast;
* the **engine** route samples it from an OpenQuake source model, which is what an F0 long-term
  hazard model is expressed in, and is authoritative.

:func:`grid_source_model_nrml` is the bridge that lets the same ``ForecastGrid`` drive both, by
rendering each grid cell as a point source with an incremental magnitude-frequency distribution
whose rates are the grid's own, annualised.

**Honesty about what has run.** As with the scenario adapter, the pinned image is
``linux/amd64``-only and this project's development machine is arm64 (ADR-0011 addendum), so
nothing here has produced a number on this machine. The job rendering and every export parser are
unit tested against captured export text; the container run is exercised only by
``tests/integration/risk/``, which runs in CI on amd64 and skips locally with the reason printed.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from rupture import __version__
from rupture.adapters.groundmotion.logic_trees import gsim_logic_tree_nrml
from rupture.adapters.groundmotion.openquake_scenario import (
    SITE_MODEL,
    OpenQuakeScenarioEngine,
    ScenarioExportError,
    _first_present,
    _read_one,
    _site_index,
    _strip_comments,
    site_model_csv,
)
from rupture.adapters.hazard.job_builder import EXPORT_SUBDIR, JOB_INI
from rupture.adapters.hazard.openquake_docker import OpenQuakeError
from rupture.domain.common import Provenance, sha256_hex, utc_now
from rupture.domain.forecast import ForecastGrid
from rupture.domain.groundmotion import GroundMotionEngineId, GroundMotionField, GsimLogicTree, Site
from rupture.ports.ground_motion import EventBasedGroundMotion

ADAPTER_VERSION = __version__
SOURCE_MODEL = "source_model.xml"
SOURCE_MODEL_LOGIC_TREE = "source_model_logic_tree.xml"
GSIM_LOGIC_TREE = "gsim_logic_tree.xml"
LICENCE = "AGPL-3.0 (engine); inputs per source model"
DEFAULT_MAX_DISTANCE_KM = 300.0
DEFAULT_SES = 1
DEFAULT_INVESTIGATION_TIME_YEARS = 1000.0
DEFAULT_DEPTH_KM = 15.0
"""Matches :data:`rupture.risk.event_set.DEFAULT_DEPTH_KM` so the two routes agree."""
SECONDS_PER_YEAR = 365.0 * 86400.0
"""The 365-day year of :func:`rupture.domain.forecast.parse_horizon`."""


class EventBasedExportError(ScenarioExportError):
    """The engine ran but its event-based exports could not be read."""


def grid_source_model_nrml(
    grid: ForecastGrid,
    *,
    depth_km: float = DEFAULT_DEPTH_KM,
    tectonic_region: str = "Active Shallow Crust",
    strike: float = 293.0,
    dip: float = 7.0,
    rake: float = 101.0,
    min_magnitude: float = 5.0,
) -> str:
    """A NRML 0.4 point-source model whose rates are ``grid``'s own, annualised.

    One ``pointSource`` per cell, at the cell's centre, with an ``incrementalMFD`` carrying the
    cell's expected counts converted from the grid's horizon to a per-year rate. The geometry
    parameters are the same stated assumptions the native route makes
    (:mod:`rupture.risk.event_set`): one nodal plane, one hypocentral depth, and no fault plane
    manufactured from a magnitude.
    """
    years = grid.horizon.total_seconds() / SECONDS_PER_YEAR
    if years <= 0.0:
        msg = f"forecast grid {grid.id!r} has a non-positive horizon"
        raise OpenQuakeError(msg)
    half = 0.5 * grid.cell_size_deg
    edges = grid.magnitude_bin_edges
    keep = [j for j, edge in enumerate(edges) if edge + grid.magnitude_bin_width > min_magnitude]
    if not keep:
        msg = f"no magnitude bin of {grid.id!r} reaches M {min_magnitude}"
        raise OpenQuakeError(msg)
    bin_min = edges[keep[0]]
    sources: list[str] = []
    for index, ((lon, lat), row) in enumerate(
        zip(grid.cell_origins, grid.expected_counts, strict=True)
    ):
        rates = [row[j] / years for j in keep]
        if sum(rates) <= 0.0:
            continue
        occur = " ".join(f"{r:.10g}" for r in rates)
        sources.append(
            f'    <pointSource id="{grid.id}-c{index}" name="cell {index}"\n'
            f'                 tectonicRegion="{tectonic_region}">\n'
            "      <pointGeometry>\n"
            "        <gml:Point><gml:pos>"
            f"{lon + half:.6f} {lat + half:.6f}"
            "</gml:pos></gml:Point>\n"
            "        <upperSeismoDepth>0.0</upperSeismoDepth>\n"
            f"        <lowerSeismoDepth>{2.0 * depth_km:.1f}</lowerSeismoDepth>\n"
            "      </pointGeometry>\n"
            "      <magScaleRel>WC1994</magScaleRel>\n"
            "      <ruptAspectRatio>1.0</ruptAspectRatio>\n"
            f'      <incrementalMFD minMag="{bin_min:.4g}" '
            f'binWidth="{grid.magnitude_bin_width:.4g}">\n'
            f"        <occurRates>{occur}</occurRates>\n"
            "      </incrementalMFD>\n"
            "      <nodalPlaneDist>\n"
            f'        <nodalPlane probability="1.0" strike="{strike:g}" dip="{dip:g}" '
            f'rake="{rake:g}"/>\n'
            "      </nodalPlaneDist>\n"
            "      <hypoDepthDist>\n"
            f'        <hypoDepth probability="1.0" depth="{depth_km:g}"/>\n'
            "      </hypoDepthDist>\n"
            "    </pointSource>"
        )
    if not sources:
        msg = f"every cell of {grid.id!r} has zero rate above M {min_magnitude}"
        raise OpenQuakeError(msg)
    body = "\n".join(sources)
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<nrml xmlns:gml="http://www.opengis.net/gml"\n'
        '      xmlns="http://openquake.org/xmlns/nrml/0.4">\n'
        f'  <sourceModel name="{grid.id}">\n'
        f"{body}\n"
        "  </sourceModel>\n"
        "</nrml>\n"
    )


def trivial_source_model_logic_tree_nrml(source_model_file: str = SOURCE_MODEL) -> str:
    """A one-branch source-model logic tree; the engine requires one even for a single model."""
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<nrml xmlns:gml="http://www.opengis.net/gml"\n'
        '      xmlns="http://openquake.org/xmlns/nrml/0.4">\n'
        '  <logicTree logicTreeID="lt1">\n'
        '    <logicTreeBranchSet uncertaintyType="sourceModel" branchSetID="bs1">\n'
        '      <logicTreeBranch branchID="b1">\n'
        f"        <uncertaintyModel>{source_model_file}</uncertaintyModel>\n"
        "        <uncertaintyWeight>1.0</uncertaintyWeight>\n"
        "      </logicTreeBranch>\n"
        "    </logicTreeBranchSet>\n"
        "  </logicTree>\n"
        "</nrml>\n"
    )


def event_based_job_ini(
    *,
    description: str,
    imt: str,
    investigation_time_years: float,
    ses_per_logic_tree_path: int,
    n_logic_tree_samples: int,
    truncation_level: float,
    maximum_distance_km: float,
    random_seed: int,
    minimum_magnitude: float,
    rupture_mesh_spacing_km: float = 5.0,
    area_source_discretization_km: float = 10.0,
    width_of_mfd_bin: float = 0.1,
) -> str:
    """``job.ini`` for ``calculation_mode = event_based`` with a GSIM logic tree.

    Key names follow the engine manual's event-based hazard page. ``ground_motion_fields = true``
    and ``minimum_intensity`` unset, because the loss layer needs every sampled event's field,
    not only the ones above a cut-off the engine chose.
    """
    lines = [
        "[general]",
        f"description = {' '.join(description.split())}",
        "calculation_mode = event_based",
        f"random_seed = {random_seed}",
        "",
        "[site_params]",
        f"site_model_file = {SITE_MODEL}",
        "",
        "[erf]",
        f"rupture_mesh_spacing = {rupture_mesh_spacing_km!r}",
        f"width_of_mfd_bin = {width_of_mfd_bin!r}",
        f"area_source_discretization = {area_source_discretization_km!r}",
        "",
        "[logic_tree]",
        f"number_of_logic_tree_samples = {n_logic_tree_samples}",
        "",
        "[calculation]",
        f"source_model_logic_tree_file = {SOURCE_MODEL_LOGIC_TREE}",
        f"gsim_logic_tree_file = {GSIM_LOGIC_TREE}",
        f"investigation_time = {investigation_time_years!r}",
        f"intensity_measure_types = {imt}",
        f"truncation_level = {truncation_level!r}",
        f"maximum_distance = {maximum_distance_km!r}",
        f"minimum_magnitude = {minimum_magnitude!r}",
        "",
        "[event_based_params]",
        f"ses_per_logic_tree_path = {ses_per_logic_tree_path}",
        "ground_motion_fields = true",
        "",
        "[output]",
        f"export_dir = {EXPORT_SUBDIR}",
        "",
    ]
    return "\n".join(lines)


def parse_events_export(events_text: str) -> dict[str, str]:
    """``event_id -> rup_id`` from the engine's ``events`` CSV export."""
    reader = csv.DictReader(io.StringIO(_strip_comments(events_text)))
    fields = reader.fieldnames or []
    event_column = _first_present(fields, ("event_id", "eid", "id"))
    rupture_column = _first_present(fields, ("rup_id", "rupture_id", "rup"))
    out = {row[event_column]: row[rupture_column] for row in reader}
    if not out:
        msg = "the events export has no rows"
        raise EventBasedExportError(msg)
    return out


def parse_ruptures_export(ruptures_text: str) -> dict[str, float]:
    """``rup_id -> magnitude`` from the engine's ``ruptures`` CSV export."""
    reader = csv.DictReader(io.StringIO(_strip_comments(ruptures_text)))
    fields = reader.fieldnames or []
    rupture_column = _first_present(fields, ("rup_id", "rupture_id", "id"))
    magnitude_column = _first_present(fields, ("mag", "magnitude"))
    out = {row[rupture_column]: float(row[magnitude_column]) for row in reader}
    if not out:
        msg = "the ruptures export has no rows"
        raise EventBasedExportError(msg)
    return out


def group_gmf_by_event(
    gmf_text: str, sitemesh_text: str, sites: tuple[Site, ...], imt: str
) -> dict[str, tuple[float, ...]]:
    """``event_id -> one value per site`` from the ``gmf_data`` export.

    Unlike the scenario parser, which folds every event into one field's realisations, an
    event-based run needs the events kept apart: each is a different rupture with a different
    loss, and collapsing them would destroy the exceedance curve.
    """
    index = _site_index(sitemesh_text, sites)
    reader = csv.DictReader(io.StringIO(_strip_comments(gmf_text)))
    fields = reader.fieldnames or []
    column = _gmv_column(fields, imt)
    event_column = _first_present(fields, ("event_id", "eid"))
    site_column = _first_present(fields, ("site_id", "sid"))
    by_event: dict[str, dict[int, float]] = defaultdict(dict)
    for row in reader:
        engine_site = int(float(row[site_column]))
        if engine_site not in index:
            continue
        by_event[row[event_column]][index[engine_site]] = float(row[column])
    if not by_event:
        msg = f"the ground-motion export holds no rows for {imt}"
        raise EventBasedExportError(msg)
    out: dict[str, tuple[float, ...]] = {}
    for event, values in by_event.items():
        # The engine writes a row only where the motion is above its own cut-off; a site the
        # rupture did not reach is a real zero, not a missing value, and is filled as one.
        out[event] = tuple(values.get(i, 0.0) for i in range(len(sites)))
    return out


def _gmv_column(fieldnames: Sequence[str], imt: str) -> str:
    wanted = f"gmv_{imt}".replace("(", "").replace(")", "")
    for name in fieldnames:
        if name.replace("(", "").replace(")", "") == wanted:
            return name
    msg = f"no gmv_{imt} column in the export; columns are {list(fieldnames)}"
    raise EventBasedExportError(msg)


class OpenQuakeEventBasedEngine(OpenQuakeScenarioEngine):
    """``EventBasedGroundMotionEngine`` backed by the pinned OpenQuake image."""

    def event_based(
        self,
        source_model_xml: str,
        sites: tuple[Site, ...],
        *,
        tree: GsimLogicTree,
        investigation_time_years: float = DEFAULT_INVESTIGATION_TIME_YEARS,
        ses_per_logic_tree_path: int = DEFAULT_SES,
        imt: str = "PGA",
        truncation_level: float = 3.0,
        seed: int | None = None,
        minimum_magnitude: float = 5.0,
        maximum_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
        n_logic_tree_samples: int | None = None,
        work_dir: Path | None = None,
    ) -> EventBasedGroundMotion:
        """Run an event-based calculation and return one field per sampled rupture.

        ``n_logic_tree_samples`` defaults to full enumeration for a one-branch tree and is
        **required** for a multi-branch one. Enumerating a weighted tree gives realisations that
        are not equally likely, and every event of an event set must carry the same rate for the
        rate arithmetic downstream to be right; sampling the tree in proportion to its weights is
        what makes them equally likely. Asking for enumeration of a weighted tree is refused
        rather than silently mis-weighted.
        """
        samples = self._samples(tree, n_logic_tree_samples)
        if work_dir is None:
            msg = "the OpenQuake event-based path needs an explicit work_dir to bind-mount"
            raise OpenQuakeError(msg)
        ok, reason = self.available()
        if not ok:
            msg = f"the OpenQuake container cannot run here: {reason}"
            raise OpenQuakeError(msg)
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / SOURCE_MODEL).write_text(source_model_xml, encoding="utf-8")
        (work_dir / SOURCE_MODEL_LOGIC_TREE).write_text(
            trivial_source_model_logic_tree_nrml(), encoding="utf-8"
        )
        (work_dir / GSIM_LOGIC_TREE).write_text(gsim_logic_tree_nrml(tree), encoding="utf-8")
        (work_dir / SITE_MODEL).write_text(site_model_csv(sites), encoding="utf-8")
        (work_dir / JOB_INI).write_text(
            event_based_job_ini(
                description=f"rupture event_based {tree.id}",
                imt=imt,
                investigation_time_years=investigation_time_years,
                ses_per_logic_tree_path=ses_per_logic_tree_path,
                n_logic_tree_samples=samples,
                truncation_level=truncation_level,
                maximum_distance_km=maximum_distance_km,
                random_seed=42 if seed is None else seed,
                minimum_magnitude=minimum_magnitude,
            ),
            encoding="utf-8",
        )
        self.ensure_image()
        out_dir = self._run_job_dir(work_dir, export_keys=("gmf_data", "events", "ruptures"))
        return self.parse_run(
            out_dir,
            sites,
            imt=imt,
            tree=tree,
            investigation_time_years=investigation_time_years,
            ses_per_logic_tree_path=ses_per_logic_tree_path,
            n_logic_tree_samples=samples,
            truncation_level=truncation_level,
            seed=seed,
            work_dir=work_dir,
        )

    @staticmethod
    def _samples(tree: GsimLogicTree, requested: int | None) -> int:
        if requested is not None:
            if requested < 1:
                msg = "number_of_logic_tree_samples must be at least 1 when sampling"
                raise OpenQuakeError(msg)
            return requested
        if len(tree.branches) == 1:
            return 0
        msg = (
            f"logic tree {tree.id!r} has {len(tree.branches)} branches, so the event set must be "
            "produced by sampling the tree (n_logic_tree_samples >= 1). Enumerating a weighted "
            "tree gives realisations that are not equally likely, and the rate arithmetic "
            "downstream assumes they are"
        )
        raise OpenQuakeError(msg)

    def parse_run(
        self,
        out_dir: Path,
        sites: tuple[Site, ...],
        *,
        imt: str,
        tree: GsimLogicTree,
        investigation_time_years: float,
        ses_per_logic_tree_path: int,
        n_logic_tree_samples: int,
        truncation_level: float,
        seed: int | None,
        work_dir: Path | None = None,
    ) -> EventBasedGroundMotion:
        """Turn one finished run's exports into an :class:`EventBasedGroundMotion`."""
        events = parse_events_export(_read_one(out_dir, ("events*.csv",)))
        magnitudes = parse_ruptures_export(_read_one(out_dir, ("ruptures*.csv",)))
        grouped = group_gmf_by_event(
            _read_one(out_dir, ("gmf-data*.csv", "gmf_data*.csv")),
            _read_one(out_dir, ("sitemesh*.csv", "sites*.csv")),
            sites,
            imt,
        )
        paths = max(n_logic_tree_samples, 1)
        rate = 1.0 / (investigation_time_years * ses_per_logic_tree_path * paths)
        computed_at = utc_now()
        fields: list[GroundMotionField] = []
        mags: list[float] = []
        for event_id in sorted(grouped):
            rupture_id = events.get(event_id)
            if rupture_id is None or rupture_id not in magnitudes:
                msg = f"event {event_id} has no rupture in the ruptures export"
                raise EventBasedExportError(msg)
            mags.append(magnitudes[rupture_id])
            fields.append(
                GroundMotionField(
                    id=f"oq-eb-{tree.id}-e{event_id}",
                    scenario_id=f"{tree.id}-event-set",
                    imt=imt,
                    sites=sites,
                    values=(grouped[event_id],),
                    engine=GroundMotionEngineId.OPENQUAKE_ENGINE,
                    engine_version=self.engine_version,
                    gsim=f"logic-tree:{tree.id}",
                    rupture_id=rupture_id,
                    truncation_level=truncation_level,
                    random_seed=seed,
                    computed_at=computed_at,
                    provenance=Provenance(
                        source=self.engine_id,
                        source_url=f"docker://{self.image}",
                        retrieved_at=computed_at,
                        sha256=sha256_hex(f"{tree.id}|{event_id}|{rupture_id}"),
                        licence=LICENCE,
                        adapter_version=ADAPTER_VERSION,
                        notes=(
                            f"event_based, investigation_time {investigation_time_years} yr, "
                            f"ses_per_logic_tree_path {ses_per_logic_tree_path}, "
                            f"logic-tree paths {paths}"
                        ),
                    ),
                    notes=(
                        "one realisation: this is one sampled rupture of a stochastic event set, "
                        f"carrying an occurrence rate of {rate:.6g} per year"
                    ),
                )
            )
        return EventBasedGroundMotion(
            fields=tuple(fields),
            magnitudes=tuple(mags),
            occurrence_rate_per_year=rate,
            investigation_time_years=investigation_time_years,
            ses_per_logic_tree_path=ses_per_logic_tree_path,
            n_realisations=paths,
            engine_id=self.engine_id,
            engine_version=self.engine_version,
            notes=(
                f"GSIM logic tree {tree.describe()}; work_dir {work_dir}"
                if work_dir
                else f"GSIM logic tree {tree.describe()}"
            ),
        )
