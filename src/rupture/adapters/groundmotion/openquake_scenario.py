"""The authoritative ground-motion path: OpenQuake's scenario calculator in the pinned image.

This wraps :class:`~rupture.adapters.hazard.openquake_docker.OpenQuakeDocker` rather than
duplicating it — the image pin, availability check, staging and log handling are all the hazard
adapter's. What is added here is the ``GroundMotionEngine`` shape: render a scenario ``job.ini``
with a site model (so each site keeps its own Vs30), write the rupture as NRML, run, and parse
the exported ground-motion fields back into a :class:`GroundMotionField`.

**Honesty about what has run.** The container is ``linux/amd64``-only and cannot run on this
project's arm64 development machine (ADR-0011 addendum, ADR-0020), so everything below is
implemented against the engine manual and exercised by ``tests/integration/risk``, which runs in
CI on amd64 and skips locally with the reason printed. Nothing here has been observed to produce
a number on the development machine; ``docs/RISK.md`` says so too.
"""

from __future__ import annotations

import csv
import io
import math
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from rupture import __version__
from rupture.adapters.hazard.job_builder import EXPORT_SUBDIR, JOB_INI
from rupture.adapters.hazard.openquake_docker import ENGINE_VERSION, OpenQuakeDocker, OpenQuakeError
from rupture.domain.common import Provenance, sha256_hex, utc_now
from rupture.domain.groundmotion import GroundMotionEngineId, GroundMotionField, Site
from rupture.domain.hazard import ScenarioRupture

ADAPTER_VERSION = __version__
SITE_MODEL = "site_model.csv"
RUPTURE_MODEL = "rupture.xml"
LICENCE = "AGPL-3.0 (engine); inputs per source model"
DEFAULT_MAX_DISTANCE_KM = 300.0
PLANAR_CORNERS = 4
COORDINATE_TOLERANCE_DEG = 1e-4


class ScenarioExportError(OpenQuakeError):
    """The engine ran but its ground-motion export could not be read."""


def rupture_nrml(rupture: ScenarioRupture) -> str:
    """A ``singlePlaneRupture`` NRML 0.4 document for a four-cornered planar rupture."""
    if len(rupture.corners) != PLANAR_CORNERS:
        msg = (
            "the OpenQuake scenario path needs a planar rupture with four corners; "
            f"{rupture.id!r} has {len(rupture.corners)}. Use native_gsim for a point rupture."
        )
        raise ValueError(msg)
    top_left, top_right, bottom_right, bottom_left = rupture.corners
    names = ("topLeft", "topRight", "bottomLeft", "bottomRight")
    ordered = (top_left, top_right, bottom_left, bottom_right)
    vertices = "\n".join(
        f'        <{name} lon="{lon:.6f}" lat="{lat:.6f}" depth="{depth:.4f}"/>'
        for name, (lon, lat, depth) in zip(names, ordered, strict=True)
    )
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        '<nrml xmlns:gml="http://www.opengis.net/gml"\n'
        '      xmlns="http://openquake.org/xmlns/nrml/0.4">\n'
        "  <singlePlaneRupture>\n"
        f"    <magnitude>{rupture.magnitude}</magnitude>\n"
        f"    <rake>{rupture.rake}</rake>\n"
        f'    <hypocenter lon="{rupture.hypocentre_longitude:.6f}" '
        f'lat="{rupture.hypocentre_latitude:.6f}" '
        f'depth="{rupture.hypocentre_depth_km:.4f}"/>\n'
        f'    <planarSurface strike="{rupture.strike}" dip="{rupture.dip}">\n'
        f"{vertices}\n"
        "    </planarSurface>\n"
        "  </singlePlaneRupture>\n"
        "</nrml>\n"
    )


def site_model_csv(sites: tuple[Site, ...]) -> str:
    """The engine's site model: one row per site, so Vs30 is not flattened to a reference value."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["lon", "lat", "vs30", "vs30measured", "z1pt0", "z2pt5", "backarc"])
    for site in sites:
        writer.writerow(
            [
                f"{site.longitude:.6f}",
                f"{site.latitude:.6f}",
                f"{site.vs30:g}",
                int(site.vs30_measured),
                f"{site.z1pt0:g}" if site.z1pt0 is not None else f"{_z1pt0_default(site.vs30):g}",
                f"{site.z2pt5:g}" if site.z2pt5 is not None else f"{_z2pt5_default(site.vs30):g}",
                0,
            ]
        )
    return buffer.getvalue()


def _z1pt0_default(vs30: float) -> float:
    """Chiou & Youngs (2014) California basin depth, metres — the engine's own default relation."""
    return float(math.exp(-7.15 / 4.0 * math.log((vs30**4 + 571.0**4) / (1360.0**4 + 571.0**4))))


def _z2pt5_default(vs30: float) -> float:
    """Campbell & Bozorgnia (2014) California basin depth, kilometres."""
    return float(math.exp(7.089 - 1.144 * math.log(vs30)))


def scenario_job_ini(
    *,
    description: str,
    gsim: str,
    imt: str,
    n_realisations: int,
    truncation_level: float,
    maximum_distance_km: float,
    random_seed: int,
    rupture_mesh_spacing_km: float = 2.0,
) -> str:
    """``job.ini`` for ``calculation_mode = scenario`` with a site model.

    The hazard adapter's :func:`job_builder.scenario_job_ini` renders the same calculation from a
    ``ScenarioGroundMotionJob``, which carries a single ``reference_vs30`` rather than a site
    model. A portfolio's sites do not share one Vs30, so this variant is rendered here instead.
    Making ``ScenarioGroundMotionJob`` carry a ``site_model_file`` would remove the duplication;
    that is a port change and belongs to the architect.
    """
    lines = [
        "[general]",
        f"description = {' '.join(description.split())}",
        "calculation_mode = scenario",
        f"random_seed = {random_seed}",
        "",
        "[site_params]",
        f"site_model_file = {SITE_MODEL}",
        "",
        "[rupture]",
        f"rupture_model_file = {RUPTURE_MODEL}",
        f"rupture_mesh_spacing = {rupture_mesh_spacing_km!r}",
        "",
        "[calculation]",
        f"intensity_measure_types = {imt}",
        f"gsim = {gsim}",
        f"number_of_ground_motion_fields = {n_realisations}",
        f"truncation_level = {truncation_level!r}",
        f"maximum_distance = {maximum_distance_km!r}",
        "",
        "[output]",
        f"export_dir = {EXPORT_SUBDIR}",
        "",
    ]
    return "\n".join(lines)


def parse_gmf_export(
    gmf_text: str, sitemesh_text: str, sites: tuple[Site, ...], imt: str
) -> tuple[tuple[float, ...], ...]:
    """``values[realisation][site]`` from the engine's ``gmf_data`` CSV export.

    The export is one row per (event, site) with a ``gmv_<IMT>`` column; ``sitemesh`` maps the
    engine's ``site_id`` to a location, which is matched back to the caller's site order. Rows
    for other intensity measures are ignored; a missing (event, site) pair is an error, never a
    zero.
    """
    site_index = _site_index(sitemesh_text, sites)
    reader = csv.DictReader(io.StringIO(_strip_comments(gmf_text)))
    column = _gmv_column(reader.fieldnames or [], imt)
    event_column = _first_present(reader.fieldnames or [], ("event_id", "eid"))
    site_column = _first_present(reader.fieldnames or [], ("site_id", "sid"))
    by_event: dict[str, dict[int, float]] = defaultdict(dict)
    for row in reader:
        engine_site = int(float(row[site_column]))
        if engine_site not in site_index:
            continue
        by_event[row[event_column]][site_index[engine_site]] = float(row[column])
    if not by_event:
        msg = f"the ground-motion export holds no rows for {imt}"
        raise ScenarioExportError(msg)
    out: list[tuple[float, ...]] = []
    for event in sorted(by_event, key=_event_sort_key):
        row_values = by_event[event]
        missing = [i for i in range(len(sites)) if i not in row_values]
        if missing:
            msg = f"event {event} has no ground motion at site index {missing[0]}"
            raise ScenarioExportError(msg)
        out.append(tuple(row_values[i] for i in range(len(sites))))
    return tuple(out)


def _event_sort_key(event: str) -> tuple[int, float | str]:
    try:
        return (0, float(event))
    except ValueError:
        return (1, event)


def _strip_comments(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.startswith("#"))


def _first_present(fieldnames: Sequence[str], candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if candidate in fieldnames:
            return candidate
    msg = f"the export has none of {candidates}; columns are {fieldnames}"
    raise ScenarioExportError(msg)


def _gmv_column(fieldnames: Sequence[str], imt: str) -> str:
    wanted = f"gmv_{imt}"
    for name in fieldnames:
        if name == wanted or name.replace("(", "").replace(")", "") == wanted.replace(
            "(", ""
        ).replace(")", ""):
            return name
    msg = f"no {wanted} column in the export; columns are {fieldnames}"
    raise ScenarioExportError(msg)


def _site_index(sitemesh_text: str, sites: tuple[Site, ...]) -> dict[int, int]:
    """Engine ``site_id`` -> index into ``sites``, matched on coordinates."""
    reader = csv.DictReader(io.StringIO(_strip_comments(sitemesh_text)))
    fields = reader.fieldnames or []
    site_column = _first_present(fields, ("site_id", "sid"))
    lon_column = _first_present(fields, ("lon", "longitude"))
    lat_column = _first_present(fields, ("lat", "latitude"))
    out: dict[int, int] = {}
    for row in reader:
        lon, lat = float(row[lon_column]), float(row[lat_column])
        for index, site in enumerate(sites):
            if (
                abs(site.longitude - lon) <= COORDINATE_TOLERANCE_DEG
                and abs(site.latitude - lat) <= COORDINATE_TOLERANCE_DEG
            ):
                out[int(float(row[site_column]))] = index
                break
    if len(out) != len(sites):
        msg = f"the engine returned {len(out)} of {len(sites)} requested sites"
        raise ScenarioExportError(msg)
    return out


class OpenQuakeScenarioEngine(OpenQuakeDocker):
    """``GroundMotionEngine`` backed by the pinned OpenQuake image.

    Subclasses the hazard adapter so the image pin, availability logic, Docker invocation and log
    capture are shared rather than copied; only the scenario rendering and the ground-motion
    export parsing are new.
    """

    engine_id = GroundMotionEngineId.OPENQUAKE_ENGINE.value
    engine_version = ENGINE_VERSION

    #: GSIMs rupture asks the engine for. The engine knows hundreds; these are the ones rupture
    #: also implements natively, so the two paths can be cross-checked on the same names.
    ENGINE_GSIMS: tuple[str, ...] = ("BooreEtAl2014", "AbrahamsonEtAl2015SInter")

    def supported_gsims(self) -> tuple[str, ...]:
        return self.ENGINE_GSIMS

    def scenario(
        self,
        rupture: ScenarioRupture,
        sites: tuple[Site, ...],
        *,
        imt: str = "PGA",
        gsim: str = "BooreEtAl2014",
        n_realisations: int = 1,
        truncation_level: float = 3.0,
        seed: int | None = None,
        work_dir: Path | None = None,
        maximum_distance_km: float = DEFAULT_MAX_DISTANCE_KM,
    ) -> GroundMotionField:
        """Run one scenario in the container and return the parsed field.

        ``work_dir`` is required in practice (the container bind-mounts it); when omitted the
        caller gets a clear error rather than a temporary directory that disappears with the log.
        """
        if work_dir is None:
            msg = "the OpenQuake scenario path needs an explicit work_dir to bind-mount"
            raise OpenQuakeError(msg)
        ok, reason = self.available()
        if not ok:
            msg = f"the OpenQuake container cannot run here: {reason}"
            raise OpenQuakeError(msg)
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / RUPTURE_MODEL).write_text(rupture_nrml(rupture), encoding="utf-8")
        (work_dir / SITE_MODEL).write_text(site_model_csv(sites), encoding="utf-8")
        (work_dir / JOB_INI).write_text(
            scenario_job_ini(
                description=f"rupture scenario {rupture.id}",
                gsim=gsim,
                imt=imt,
                n_realisations=n_realisations,
                truncation_level=truncation_level,
                maximum_distance_km=maximum_distance_km,
                random_seed=42 if seed is None else seed,
            ),
            encoding="utf-8",
        )
        self.ensure_image()
        out_dir = self._run_job_dir(work_dir, export_keys=("gmf_data",))
        values = parse_gmf_export(
            _read_one(out_dir, ("gmf-data*.csv", "gmf_data*.csv")),
            _read_one(out_dir, ("sitemesh*.csv", "sites*.csv")),
            sites,
            imt,
        )
        computed_at = utc_now()
        digest = self.image_digest()
        return GroundMotionField(
            id=f"{rupture.id}-oq-{gsim.lower()}-{imt.lower()}-n{len(values)}",
            scenario_id=rupture.id,
            imt=imt,
            sites=sites,
            values=values,
            engine=GroundMotionEngineId.OPENQUAKE_ENGINE,
            engine_version=self.engine_version,
            gsim=gsim,
            rupture_id=rupture.id,
            truncation_level=truncation_level,
            random_seed=seed,
            computed_at=computed_at,
            provenance=Provenance(
                source=self.engine_id,
                source_url=f"docker://{digest or self.image}",
                retrieved_at=computed_at,
                sha256=sha256_hex((work_dir / JOB_INI).read_text(encoding="utf-8")),
                licence=LICENCE,
                adapter_version=ADAPTER_VERSION,
                notes=f"image {self.image}; work_dir {work_dir}",
            ),
            notes=None,
        )


def _read_one(directory: Path, patterns: tuple[str, ...]) -> str:
    for pattern in patterns:
        matches = sorted(directory.glob(pattern))
        if matches:
            return matches[0].read_text(encoding="utf-8")
    msg = f"no export matching {patterns} in {directory}"
    raise ScenarioExportError(msg)
