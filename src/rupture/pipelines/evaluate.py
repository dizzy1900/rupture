"""Pipeline: score one forecast against the frozen target slice and write the report bundle.

Writes, under ``out_dir`` (default ``reports/eval/<forecast_id>/``): ``results.json`` (one
``EvaluationResult`` per test), ``target.parquet`` (the exact slice that was scored, protocol § 9)
and the plot bundle with ``summary.json``.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

from rupture.adapters.forecasting.leakage import assert_within_window
from rupture.domain import Catalog, EvaluationResult, ForecastGrid, Region, TestName, utc_now
from rupture.pipelines import io
from rupture.ports import Evaluator, RunRecord, Tracker

DEFAULT_TESTS: tuple[TestName, ...] = (TestName.N, TestName.M, TestName.S, TestName.L, TestName.CL)
RESULTS_FILE = "results.json"
TARGET_FILE = "target.parquet"


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
) -> list[EvaluationResult]:
    out_dir = Path(out_dir)
    target = target_slice(catalog, grid, region)
    results = evaluator.evaluate(
        grid, target, tests, n_simulations=n_simulations, alpha=alpha, seed=seed
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    io.save_results(results, out_dir / RESULTS_FILE)
    io.write_events_parquet(target.events, out_dir / TARGET_FILE)
    written: list[Path] = []
    if plots:
        written = evaluator.plot_bundle(grid, target, results, out_dir)
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
                    "target_catalog_hash": target.event_hash(),
                    "n_target_given": len(target),
                    "tests": [t.value for t in tests],
                    "n_simulations": n_simulations,
                    "alpha": alpha,
                    "seed": seed,
                },
                outputs={
                    "out_dir": str(out_dir),
                    "passed": {r.test_name.value: r.passed for r in results},
                    "plots": [p.name for p in written],
                },
            )
        )
    return results


def window_end(grid: ForecastGrid) -> timedelta:
    return grid.horizon
