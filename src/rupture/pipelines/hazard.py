"""Hazard pipeline: build, check and run classical PSHA jobs through a ``HazardEngine``.

Orchestration over the port; the CLI supplies the concrete engine. This module is also the one
place allowed to join the two adapter families the classical lane needs — ``adapters.sources``
(which fetches a provenanced source model) and ``adapters.hazard`` (which renders and runs a job)
— because the import-linter contract keeps adapter families independent of each other.

``eshm20_classical_job`` is the bridge between them: it derives a runnable ``ClassicalPSHAJob``
from the manifest the ESHM20 adapter wrote and the region record, so the job can never name a file
the adapter does not produce. A hand-maintained job JSON pointing at guessed file names is exactly
what went stale before (ADR-0008 said the adapter would be exercised end to end; only the demo
half was).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from rupture.adapters.hazard import job_builder
from rupture.adapters.sources import openquake_sources
from rupture.domain import HazardCurveSet, Region
from rupture.ports.hazard_engine import ClassicalPSHAJob, HazardEngine

CURVE_SET_FILE = "hazard-curve-set.json"
JOB_FILE = "job.json"
ESHM20_REGION = "turkiye-eaf"
"""The only region with a verified openly licensed OpenQuake source model (ADR-0008)."""


class DemoRunner(Protocol):
    """An engine that also ships runnable demos (the OpenQuake image does)."""

    def available(self) -> tuple[bool, str]: ...

    def run_bundled_demo(self, work_dir: Path, demo: str) -> HazardCurveSet: ...


def load_classical_job(path: Path) -> ClassicalPSHAJob:
    """Read a ``ClassicalPSHAJob`` JSON dump; relative input paths resolve against the file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    job = ClassicalPSHAJob.model_validate(payload)
    base = path.resolve().parent
    updates: dict[str, Path] = {}
    for field in ("source_model_logic_tree", "gsim_logic_tree", "sites_csv"):
        value = getattr(job, field)
        if isinstance(value, Path) and not value.is_absolute():
            updates[field] = base / value
    return job.model_copy(update=updates) if updates else job


def region_wkt(region: Region) -> str:
    """The region polygon as a single-ring WKT ``POLYGON`` in ``lon lat`` order.

    OpenQuake's ``region`` key takes an arbitrary simple polygon, so the real region ring is used
    rather than its bounding box: a bounding box would compute hazard over sites the region record
    does not claim, and the two would then disagree about what "the region" is.
    """
    ring = ", ".join(f"{lon:g} {lat:g}" for lon, lat in region.closed_ring())
    return f"POLYGON(({ring}))"


def eshm20_classical_job(
    region: Region,
    *,
    raw_dir: Path = openquake_sources.DEFAULT_RAW_DIR,
    grid_spacing_km: float = 20.0,
    investigation_time_years: float = 50.0,
    imts: dict[str, tuple[float, ...]] | None = None,
    maximum_distance_km: float = 300.0,
    number_of_logic_tree_samples: int = 0,
) -> ClassicalPSHAJob:
    """A runnable ``ClassicalPSHAJob`` for ``region`` from the fetched ESHM20 model.

    Both logic-tree paths come from ``data/raw/eshm20/manifest.json`` — the file the fetching
    adapter wrote — so they are whatever that adapter actually produced. The manifest is also the
    provenance record (commit, sha256 per file, licence, citation), which is why the job is derived
    from it rather than from constants repeated here.

    Raises when the region has no verified source model (ADR-0008 records California and Nepal as
    gaps), when the manifest is absent (nothing has been fetched) or when a file it names is
    missing from disk. It never falls back to a guessed path.
    """
    models, gap = openquake_sources.available_models(region.id)
    if not models:
        msg = f"no OpenQuake source model for region {region.id!r}: {gap}"
        raise ValueError(msg)
    manifest = openquake_sources.read_manifest(raw_dir)
    smlt = Path(raw_dir) / str(manifest["source_model_logic_tree"])
    gslt = Path(raw_dir) / str(manifest["gsim_logic_tree"])
    for label, path in (("source_model_logic_tree", smlt), ("gsim_logic_tree", gslt)):
        if not path.is_file():
            msg = (
                f"{label} named by {Path(raw_dir) / 'manifest.json'} is not on disk: {path}; "
                "re-run the ESHM20 fetch (network) before building the job"
            )
            raise FileNotFoundError(msg)
    model = models[0]
    return ClassicalPSHAJob(
        id=f"{region.id}-classical-{model.model_id}",
        description=(
            f"Coarse classical PSHA over the {region.name} polygon from {model.model_id} "
            f"({manifest['repository']} @ {str(manifest['commit'])[:12]}, {manifest['licence']}); "
            f"{investigation_time_years:g}-year investigation time on a "
            f"{grid_spacing_km:g} km grid. rupture does not forecast individual earthquakes; "
            "this is a long-term probability of exceedance of ground motion."
        ),
        source_model_logic_tree=smlt,
        gsim_logic_tree=gslt,
        region_wkt=region_wkt(region),
        region_grid_spacing_km=grid_spacing_km,
        investigation_time_years=investigation_time_years,
        imts=imts
        or {
            "PGA": (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0),
            "SA(0.3)": (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0, 1.5),
            "SA(1.0)": (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0),
        },
        maximum_distance_km=maximum_distance_km,
        number_of_logic_tree_samples=number_of_logic_tree_samples,
    )


def missing_classical_inputs(job: ClassicalPSHAJob) -> list[str]:
    """Every file the job names that is not on disk: the logic trees, the sites CSV, and each
    source model the source-model logic tree references by ``<uncertaintyModel>``.

    Empty means the job can be staged. Checked before a container is started so a stale path costs
    a millisecond rather than an image pull.
    """
    missing: list[str] = []
    for path in job_builder.referenced_inputs(job).values():
        if not Path(path).is_file():
            missing.append(str(path))
    smlt = Path(job.source_model_logic_tree)
    if smlt.is_file():
        for name in job_builder.referenced_source_models(smlt.read_text(encoding="utf-8")):
            if not (smlt.parent / name).is_file():
                missing.append(str(smlt.parent / name))
    return missing


def write_classical_job(job: ClassicalPSHAJob, path: Path) -> Path:
    """Dump a job so ``rupture hazard classical --job <path>`` can run it.

    Input paths are written relative to the file when they sit under its parent tree, which is
    what :func:`load_classical_job` resolves them against.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = job.model_dump(mode="json")
    base = path.resolve().parent
    for field in ("source_model_logic_tree", "gsim_logic_tree", "sites_csv"):
        value = getattr(job, field)
        if value is None:
            continue
        try:
            payload[field] = str(Path(value).resolve().relative_to(base, walk_up=True))
        except ValueError:  # pragma: no cover - different drive; keep the absolute path
            payload[field] = str(Path(value).resolve())
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def run_demo(engine: DemoRunner, work_dir: Path, demo: str) -> HazardCurveSet:
    curve_set = engine.run_bundled_demo(work_dir, demo)
    write_curve_set(curve_set, work_dir / CURVE_SET_FILE)
    return curve_set


def run_classical(engine: HazardEngine, job: ClassicalPSHAJob, work_dir: Path) -> HazardCurveSet:
    missing = missing_classical_inputs(job)
    if missing:
        msg = f"classical job {job.id!r} names {len(missing)} file(s) that do not exist: {missing}"
        raise FileNotFoundError(msg)
    curve_set = engine.run_classical(job, work_dir)
    write_curve_set(curve_set, work_dir / CURVE_SET_FILE)
    return curve_set


def write_curve_set(curve_set: HazardCurveSet, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(curve_set.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def summary_lines(curve_set: HazardCurveSet) -> list[str]:
    sites = {(c.site_longitude, c.site_latitude) for c in curve_set.curves}
    imts = sorted({c.imt for c in curve_set.curves})
    return [
        f"id: {curve_set.id}",
        f"engine: {curve_set.engine} {curve_set.engine_version}",
        f"realisation: {curve_set.realisation}",
        f"investigation_time_years: {curve_set.investigation_time_years}",
        f"sites: {len(sites)}, curves: {len(curve_set.curves)}, imts: {', '.join(imts)}",
        f"job_hash: {curve_set.job_hash}",
        f"provenance: {curve_set.provenance.source_url}",
    ]
