"""Pipeline: score one forecast against the frozen target slice and write the report bundle.

Results are keyed by the target slice hash (protocol § 9) and never overwritten. Under
``out_dir`` (default ``reports/eval/<forecast_id>/``):

- ``results-<hash12>.json`` — one ``EvaluationResult`` per test for that target slice;
- ``<hash12>/`` — ``target.parquet`` (the exact slice scored), the plot bundle, ``summary.json``;
- ``latest.json`` — pointer to the most recent hash, its results file and bundle directory.

``hash12`` is ``target_catalog_hash[:12]``. If ``results-<hash12>.json`` already exists the window
is not re-scored (idempotence) and the stored results are returned; a revised catalogue gives a
new hash and a new file next to the old one.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from pathlib import Path

from rupture.adapters.forecasting.leakage import assert_within_window
from rupture.domain import Catalog, EvaluationResult, ForecastGrid, Region, TestName, utc_now
from rupture.pipelines import io
from rupture.ports import Evaluator, RunRecord, Tracker

DEFAULT_TESTS: tuple[TestName, ...] = (TestName.N, TestName.M, TestName.S, TestName.L, TestName.CL)
LATEST_FILE = "latest.json"
TARGET_FILE = "target.parquet"
HASH_PREFIX = 12


def results_file(out_dir: Path, target_catalog_hash: str) -> Path:
    return Path(out_dir) / f"results-{target_catalog_hash[:HASH_PREFIX]}.json"


def bundle_dir(out_dir: Path, target_catalog_hash: str) -> Path:
    return Path(out_dir) / target_catalog_hash[:HASH_PREFIX]


def target_slice(catalog: Catalog, grid: ForecastGrid, region: Region | None = None) -> Catalog:
    """``[issue_time, issue_time + horizon)`` on ``origin_time``; depth-filtered given a region.

    Event-type and magnitude filters are the evaluator's job (it counts what it excludes); the
    slice keeps non-earthquake entries so the report can say how many were excluded.
    """
    target = catalog.between(grid.issue_time, grid.window_end)
    if region is not None:
        kept = tuple(
            e
            for e in target.events
            if e.depth_km is None or region.depth_min_km <= e.depth_km <= region.depth_max_km
        )
        target = target.model_copy(update={"events": kept, "id": f"{target.id}/depth"})
    assert_within_window(target, grid.issue_time, grid.window_end, what="target slice")
    return target


def evaluate_forecast(
    grid: ForecastGrid,
    catalog: Catalog,
    evaluator: Evaluator,
    *,
    out_dir: Path,
    region: Region | None = None,
    tests: Sequence[TestName] = DEFAULT_TESTS,
    n_simulations: int = 1000,
    alpha: float = 0.05,
    seed: int | None = None,
    plots: bool = True,
    tracker: Tracker | None = None,
    force: bool = False,
) -> list[EvaluationResult]:
    """Score ``grid`` on its window; skip when results for this target hash already exist."""
    out_dir = Path(out_dir)
    target = target_slice(catalog, grid, region)
    target_hash = target.event_hash()
    path = results_file(out_dir, target_hash)
    if path.exists() and not force:
        existing = io.load_results(path)
        if tracker is not None:
            tracker.log(
                RunRecord(
                    run_id=f"evaluate-{grid.id}-{uuid.uuid4().hex[:8]}",
                    kind="evaluate",
                    at=utc_now(),
                    region_id=grid.region_id,
                    model_id=grid.model_id,
                    parameter_snapshot_hash=grid.parameter_snapshot_hash,
                    inputs={"forecast_id": grid.id, "target_catalog_hash": target_hash},
                    outputs={"skipped": True, "reason": f"{path.name} already exists"},
                )
            )
        return existing

    results = evaluator.evaluate(
        grid, target, tests, n_simulations=n_simulations, alpha=alpha, seed=seed
    )
    bundle = bundle_dir(out_dir, target_hash)
    bundle.mkdir(parents=True, exist_ok=True)
    io.write_events_parquet(target.events, bundle / TARGET_FILE)
    written: list[Path] = []
    if plots:
        written = evaluator.plot_bundle(grid, target, results, bundle)
    io.save_results(results, path)  # written last: its presence means the bundle is complete
    _write_latest(out_dir, grid, target_hash, path, bundle)
    if tracker is not None:
        tracker.log(
            RunRecord(
                run_id=f"evaluate-{grid.id}-{uuid.uuid4().hex[:8]}",
                kind="evaluate",
                at=utc_now(),
                region_id=grid.region_id,
                model_id=grid.model_id,
                parameter_snapshot_hash=grid.parameter_snapshot_hash,
                inputs={
                    "forecast_id": grid.id,
                    "catalog_id": catalog.id,
                    "target_catalog_hash": target_hash,
                    "n_target_given": len(target),
                    "tests": [t.value for t in tests],
                    "n_simulations": n_simulations,
                    "alpha": alpha,
                    "seed": seed,
                    "force": force,
                },
                outputs={
                    "results": str(path),
                    "bundle_dir": str(bundle),
                    "passed": {r.test_name.value: r.passed for r in results},
                    "plots": [p.name for p in written],
                },
            )
        )
    return results


def _write_latest(
    out_dir: Path, grid: ForecastGrid, target_hash: str, results: Path, bundle: Path
) -> None:
    payload = {
        "forecast_id": grid.id,
        "target_catalog_hash": target_hash,
        "results": results.name,
        "bundle_dir": bundle.name,
        "written_at": utc_now().isoformat(),
        "note": "pointer only; earlier results-<hash>.json files are kept (protocol section 9)",
    }
    (out_dir / LATEST_FILE).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
