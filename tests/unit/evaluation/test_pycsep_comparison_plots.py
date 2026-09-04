"""Comparison plots for the paired T/W tests (docs/EVALUATION_PROTOCOL.md § 8).

The consistency half of the plot bundle was always written; the comparison half was promised by
the protocol and produced by nothing, so a T/W verdict that decides a promotion had no visual
record. ``compare()`` now keeps the pycsep result objects and ``comparison_plot_bundle`` renders
them. Offline: no basemap, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rupture.adapters.evaluation.pycsep import PyCSEPEvaluator
from rupture.domain import Catalog, ForecastGrid, TestName
from tests.unit.forecasting.conftest import FIT_CUTOFF, HORIZON


@pytest.fixture(scope="module")
def target(fixture_catalog: Catalog) -> Catalog:
    return fixture_catalog.between(FIT_CUTOFF, FIT_CUTOFF + HORIZON)


@pytest.fixture(scope="module")
def challenger(ridgecrest_grid: ForecastGrid) -> ForecastGrid:
    """A rescaled copy standing in for a challenger: real grid, real cells, a different rate."""
    return ridgecrest_grid.model_copy(
        update={
            "id": ridgecrest_grid.id + "-x2",
            "model_id": "scaled",
            "expected_counts": tuple(
                tuple(2.0 * v for v in row) for row in ridgecrest_grid.expected_counts
            ),
        }
    )


def test_the_bundle_writes_a_t_test_plot_and_its_json(
    challenger: ForecastGrid, ridgecrest_grid: ForecastGrid, target: Catalog, tmp_path: Path
) -> None:
    evaluator = PyCSEPEvaluator()
    results = evaluator.compare(challenger, ridgecrest_grid, target)
    written = evaluator.comparison_plot_bundle(challenger, ridgecrest_grid, results, tmp_path)
    names = [p.name for p in written]
    assert "t-test.png" in names, names
    assert "comparison.json" in names
    assert (tmp_path / "t-test.png").stat().st_size > 0
    summary = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    assert summary["skipped"] == []
    assert summary["benchmark_model_id"] == "etas-mizrahi"
    assert summary["model_id"] == "scaled"
    assert {r["test"] for r in summary["results"]} == {TestName.T.value, TestName.W.value}


def test_without_a_compare_call_the_reason_is_recorded_not_a_plot_invented(
    challenger: ForecastGrid, ridgecrest_grid: ForecastGrid, target: Catalog, tmp_path: Path
) -> None:
    evaluator = PyCSEPEvaluator()
    results = PyCSEPEvaluator().compare(challenger, ridgecrest_grid, target)
    written = evaluator.comparison_plot_bundle(challenger, ridgecrest_grid, results, tmp_path)
    assert [p.name for p in written] == ["comparison.json"]
    assert not (tmp_path / "t-test.png").exists()
    summary = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    assert len(summary["skipped"]) == 1
    assert "call compare() first" in summary["skipped"][0]["reason"]


def test_an_undefined_comparison_leaves_no_stale_result_behind(
    challenger: ForecastGrid, ridgecrest_grid: ForecastGrid, target: Catalog, tmp_path: Path
) -> None:
    """A second comparison with no target events must not plot the previous one's numbers."""
    evaluator = PyCSEPEvaluator()
    evaluator.compare(challenger, ridgecrest_grid, target)
    empty = target.model_copy(update={"events": ()})
    evaluator.compare(challenger, ridgecrest_grid, empty)
    results = evaluator.compare(challenger, ridgecrest_grid, empty)
    written = evaluator.comparison_plot_bundle(challenger, ridgecrest_grid, results, tmp_path)
    assert [p.name for p in written] == ["comparison.json"]
    summary = json.loads((tmp_path / "comparison.json").read_text(encoding="utf-8"))
    assert "no target events" in summary["skipped"][0]["reason"]
