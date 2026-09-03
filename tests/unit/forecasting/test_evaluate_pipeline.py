"""Results are keyed by target hash, never overwritten, and re-scoring is idempotent (M2)."""

from __future__ import annotations

import json
from pathlib import Path

from rupture.adapters.evaluation.pycsep import PyCSEPEvaluator
from rupture.adapters.storage.run_log import JsonlTracker
from rupture.domain import Catalog, ForecastGrid, Region, TestName
from rupture.pipelines import io
from rupture.pipelines.evaluate import (
    LATEST_FILE,
    TARGET_FILE,
    bundle_dir,
    evaluate_forecast,
    results_file,
    target_slice,
)


def test_results_are_hash_keyed_idempotent_and_never_overwritten(
    tmp_path: Path, ridgecrest_grid: ForecastGrid, fixture_catalog: Catalog, region: Region
) -> None:
    evaluator = PyCSEPEvaluator()
    tracker = JsonlTracker(tmp_path / "runs.jsonl")
    out = tmp_path / "eval" / ridgecrest_grid.id
    kw = {"out_dir": out, "region": region, "tests": (TestName.N, TestName.M), "n_simulations": 20}
    first = evaluate_forecast(
        ridgecrest_grid, fixture_catalog, evaluator, seed=1, plots=False, tracker=tracker, **kw
    )
    h1 = target_slice(fixture_catalog, ridgecrest_grid, region).event_hash()
    path1 = results_file(out, h1)
    assert path1.name == f"results-{h1[:12]}.json"
    assert path1.exists()
    assert (bundle_dir(out, h1) / TARGET_FILE).exists()
    latest = json.loads((out / LATEST_FILE).read_text(encoding="utf-8"))
    assert latest["results"] == path1.name
    assert latest["bundle_dir"] == h1[:12]
    mtime = path1.stat().st_mtime_ns

    # same catalogue again: skipped, stored results returned, file untouched
    again = evaluate_forecast(
        ridgecrest_grid, fixture_catalog, evaluator, seed=99, plots=False, tracker=tracker, **kw
    )
    assert again == first
    assert path1.stat().st_mtime_ns == mtime
    skipped = [r for r in tracker.records(kind="evaluate") if r.outputs.get("skipped")]
    assert len(skipped) == 1

    # a revised catalogue (one target event dropped) -> new hash, new file next to the old one
    window = fixture_catalog.between(ridgecrest_grid.issue_time, ridgecrest_grid.window_end)
    drop = next(e.id for e in window.events if e.mw is not None and e.mw >= 3.95)
    revised = fixture_catalog.model_copy(
        update={"events": tuple(e for e in fixture_catalog.events if e.id != drop)}
    )
    third = evaluate_forecast(
        ridgecrest_grid, revised, evaluator, seed=1, plots=False, tracker=tracker, **kw
    )
    h2 = target_slice(revised, ridgecrest_grid, region).event_hash()
    assert h2 != h1
    assert results_file(out, h2).exists()
    assert path1.exists()
    assert io.load_results(path1) == first
    assert third[0].n_target_events == first[0].n_target_events - 1
    assert json.loads((out / LATEST_FILE).read_text(encoding="utf-8"))["results"] == (
        f"results-{h2[:12]}.json"
    )
    assert sorted(p.name for p in out.glob("results-*.json")) == sorted(
        [f"results-{h1[:12]}.json", f"results-{h2[:12]}.json"]
    )

    # force re-scores in place for the current hash
    forced = evaluate_forecast(
        ridgecrest_grid, fixture_catalog, evaluator, seed=1, plots=False, force=True, **kw
    )
    assert [r.test_name for r in forced] == [r.test_name for r in first]
    assert path1.stat().st_mtime_ns >= mtime
