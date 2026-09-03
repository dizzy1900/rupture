"""The pycsep evaluator: conversions, protocol decisions, zero-target rule, comparisons, plots."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.evaluation.pycsep import MOST_NEGATIVE, PyCSEPEvaluator
from rupture.domain import Catalog, EventType, ForecastGrid, TestName
from rupture.ports import Evaluator
from tests.unit.forecasting.conftest import FIT_CUTOFF, HORIZON

ALL = (TestName.N, TestName.M, TestName.S, TestName.L, TestName.CL)


@pytest.fixture(scope="module")
def evaluator() -> PyCSEPEvaluator:
    return PyCSEPEvaluator()


@pytest.fixture(scope="module")
def ridgecrest_target(fixture_catalog: Catalog) -> Catalog:
    return fixture_catalog.between(FIT_CUTOFF, FIT_CUTOFF + HORIZON)


def test_port_and_version(evaluator: PyCSEPEvaluator) -> None:
    assert isinstance(evaluator, Evaluator)
    assert evaluator.evaluator_version == "pycsep-0.8.0"


def test_gridded_forecast_conversion(
    evaluator: PyCSEPEvaluator, ridgecrest_grid: ForecastGrid
) -> None:
    g = evaluator.to_gridded_forecast(ridgecrest_grid)
    assert g.data.shape == (4400, 51)
    assert g.event_count == pytest.approx(ridgecrest_grid.total_expected())
    assert g.region.num_nodes == 4400
    assert list(g.magnitudes[:2]) == [3.95, 4.05]
    assert g.start_time == ridgecrest_grid.issue_time
    assert g.end_time == ridgecrest_grid.window_end


def test_target_conversion_counts_exclusions(
    evaluator: PyCSEPEvaluator, ridgecrest_grid: ForecastGrid, ridgecrest_target: Catalog
) -> None:
    g = evaluator.to_gridded_forecast(ridgecrest_grid)
    cat, counts = evaluator.to_csep_catalog(ridgecrest_target, g, ridgecrest_grid)
    assert counts["given"] == len(ridgecrest_target)
    assert counts["used"] == cat.event_count == 123
    assert counts["below_threshold"] == counts["given"] - counts["used"]
    assert counts["not_earthquake"] == 0
    assert counts["no_mw"] == 0
    assert counts["outside_grid"] == 0
    assert cat.get_magnitudes().min() >= 3.95


def test_ridgecrest_window_results(
    evaluator: PyCSEPEvaluator, ridgecrest_grid: ForecastGrid, ridgecrest_target: Catalog
) -> None:
    results = evaluator.evaluate(ridgecrest_grid, ridgecrest_target, ALL, n_simulations=50, seed=1)
    by = {r.test_name: r for r in results}
    assert set(by) == set(ALL)
    n = by[TestName.N]
    assert n.statistic == 123.0
    assert n.n_target_events == 123
    assert n.quantile_low is not None
    assert n.quantile_high is not None
    assert n.quantile is None
    assert n.quantile_high == pytest.approx(0.0, abs=1e-9), "P(N >= 123 | ~1 expected)"
    assert n.passed is False
    for t in (TestName.M, TestName.S, TestName.L, TestName.CL):
        r = by[t]
        assert r.quantile is not None
        assert 0.0 <= r.quantile <= 1.0
        assert r.n_simulations == 50
        assert r.passed is not None
        assert r.statistic <= 0.0
    assert by[TestName.S].passed is False, "a quiet-year fit puts almost no rate on Ridgecrest"
    for r in results:
        assert r.target_catalog_hash == ridgecrest_target.event_hash()
        assert r.target_window_start == FIT_CUTOFF
        assert r.target_window_end == FIT_CUTOFF + HORIZON
        assert r.forecast_id == ridgecrest_grid.id
        assert r.alpha == 0.05
        assert '"seed": 1' in (r.notes or "")


def test_zero_target_window_is_n_only(
    evaluator: PyCSEPEvaluator, ridgecrest_grid: ForecastGrid, ridgecrest_target: Catalog
) -> None:
    empty = ridgecrest_target.of_type(EventType.LANDSLIDE)
    assert len(empty) == 0
    results = evaluator.evaluate(ridgecrest_grid, empty, ALL, n_simulations=20, seed=1)
    by = {r.test_name: r for r in results}
    assert by[TestName.N].statistic == 0.0
    assert by[TestName.N].passed is not None
    for t in (TestName.M, TestName.S, TestName.L, TestName.CL):
        assert by[t].passed is None
        assert by[t].n_target_events == 0
        assert by[t].quantile is None


def test_target_outside_window_is_refused(
    evaluator: PyCSEPEvaluator, ridgecrest_grid: ForecastGrid, fixture_catalog: Catalog
) -> None:
    with pytest.raises(ValueError, match="before the forecast issue time"):
        evaluator.evaluate(ridgecrest_grid, fixture_catalog, [TestName.N])
    late = fixture_catalog.between(FIT_CUTOFF, FIT_CUTOFF + HORIZON + timedelta(days=1))
    with pytest.raises(ValueError, match="past the forecast window end"):
        evaluator.evaluate(ridgecrest_grid, late, [TestName.N])
    with pytest.raises(ValueError, match="compare"):
        evaluator.evaluate(
            ridgecrest_grid, late.between(FIT_CUTOFF, FIT_CUTOFF + HORIZON), [TestName.T]
        )


def test_zero_rate_bins_are_a_rejection(
    evaluator: PyCSEPEvaluator, ridgecrest_grid: ForecastGrid, ridgecrest_target: Catalog
) -> None:
    counts = ridgecrest_grid.counts()
    counts[:, 1:] = 0.0  # keep only the first magnitude bin: M>=4.05 targets hit zero-rate bins
    grid = ridgecrest_grid.model_copy(
        update={"expected_counts": tuple(tuple(float(v) for v in row) for row in counts)}
    )
    results = evaluator.evaluate(grid, ridgecrest_target, [TestName.M], n_simulations=20, seed=1)
    (m,) = results
    assert m.passed is False
    assert m.statistic == MOST_NEGATIVE
    assert "zero-rate bin" in (m.notes or "")


def test_compare_against_a_rescaled_copy(
    evaluator: PyCSEPEvaluator, ridgecrest_grid: ForecastGrid, ridgecrest_target: Catalog
) -> None:
    doubled = ridgecrest_grid.model_copy(
        update={
            "id": ridgecrest_grid.id + "-x2",
            "model_id": "scaled",
            "expected_counts": tuple(
                tuple(2.0 * v for v in row) for row in ridgecrest_grid.expected_counts
            ),
        }
    )
    results = evaluator.compare(doubled, ridgecrest_grid, ridgecrest_target)
    by = {r.test_name: r for r in results}
    t, w = by[TestName.T], by[TestName.W]
    assert t.benchmark_model_id == "etas-mizrahi"
    assert w.benchmark_model_id == "etas-mizrahi"
    # per-event gain is log 2 minus the rate-difference term; identical for every event, so the
    # t statistic has zero variance and is undefined -> passed is None, not a verdict
    assert t.statistic == pytest.approx(
        np.log(2.0) - ridgecrest_grid.total_expected() / 123, abs=1e-6
    )
    assert t.passed is None
    assert t.p_value is None
    assert w.p_value is not None
    assert 0.0 <= w.p_value <= 1.0
    assert w.passed is not None
    with pytest.raises(ValueError, match="same window"):
        evaluator.compare(
            doubled.model_copy(update={"issue_time": FIT_CUTOFF + timedelta(days=1)}),
            ridgecrest_grid,
            ridgecrest_target,
        )


def test_plot_bundle_writes_pngs_and_summary(
    tmp_path: Path,
    evaluator: PyCSEPEvaluator,
    ridgecrest_grid: ForecastGrid,
    ridgecrest_target: Catalog,
) -> None:
    results = evaluator.evaluate(ridgecrest_grid, ridgecrest_target, ALL, n_simulations=20, seed=1)
    files = evaluator.plot_bundle(ridgecrest_grid, ridgecrest_target, results, tmp_path)
    names = {f.name for f in files}
    assert {
        "n-test.png",
        "m-test.png",
        "s-test-distribution.png",
        "expected-counts-map.png",
        "summary.json",
    } <= names
    for f in files:
        assert f.exists()
        assert f.stat().st_size > 0
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert summary["skipped"] == [], summary["skipped"]
    assert {r["test"] for r in summary["results"]} == {t.value for t in ALL}
    assert summary["results"][0]["passed"] is False


def test_evaluated_at_is_utc(
    evaluator: PyCSEPEvaluator, ridgecrest_grid: ForecastGrid, ridgecrest_target: Catalog
) -> None:
    (r,) = evaluator.evaluate(ridgecrest_grid, ridgecrest_target, [TestName.N])
    assert r.evaluated_at.tzinfo is UTC or r.evaluated_at.utcoffset() == timedelta(0)
    assert r.evaluated_at > datetime(2026, 1, 1, tzinfo=UTC)
