"""Hazard pipeline: run the bundled demo or a classical PSHA job through a ``HazardEngine``.

Pure orchestration over the port; the CLI supplies the concrete engine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from rupture.domain import HazardCurveSet
from rupture.ports.hazard_engine import ClassicalPSHAJob, HazardEngine

CURVE_SET_FILE = "hazard-curve-set.json"


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


def run_demo(engine: DemoRunner, work_dir: Path, demo: str) -> HazardCurveSet:
    curve_set = engine.run_bundled_demo(work_dir, demo)
    write_curve_set(curve_set, work_dir / CURVE_SET_FILE)
    return curve_set


def run_classical(engine: HazardEngine, job: ClassicalPSHAJob, work_dir: Path) -> HazardCurveSet:
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
