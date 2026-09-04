"""CSEP consistency and comparison tests via pycsep 0.8.0 (``Evaluator`` port; ADR-0010).

Mapping to :class:`~rupture.domain.EvaluationResult` (protocol § 4):

- N-test: ``statistic`` = observed count; ``quantile_low`` = P(N <= observed) (pycsep
  ``delta_2``), ``quantile_high`` = P(N >= observed) (``delta_1``); pass iff both >= alpha/2.
- M/S/L/CL: ``statistic`` = observed (normalised) log-likelihood; ``quantile`` = fraction of
  simulated statistics <= observed; pass iff ``quantile >= alpha`` (one-sided, low tail fails).
  With zero target events they are recorded with ``passed = None`` (protocol § 5).
- T-test: ``statistic`` = information gain per event, ``p_value`` from the t statistic; pass iff
  the lower confidence bound of the gain is > 0. W-test: ``statistic`` = z, ``p_value`` = pycsep's
  probability; pass iff ``p_value < alpha`` and z > 0.

Target filtering counts (non-earthquakes, events without ``mw``, below threshold, outside the
grid) are written to ``notes``; ``target_catalog_hash`` is the hash of the slice as given.
"""

from __future__ import annotations

import json
import math
import warnings
from collections.abc import Sequence
from datetime import UTC
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
from csep import __version__ as csep_version
from csep.core import poisson_evaluations as pe
from csep.core.catalogs import CSEPCatalog
from csep.core.forecasts import GriddedForecast
from csep.core.regions import CartesianGrid2D
from scipy import stats

from rupture.domain import Catalog, EvaluationResult, EventType, ForecastGrid, TestName, utc_now

matplotlib.use("Agg")

CONSISTENCY_TESTS: tuple[TestName, ...] = (
    TestName.N,
    TestName.M,
    TestName.S,
    TestName.L,
    TestName.CL,
)
ONE_SIDED: tuple[TestName, ...] = (TestName.M, TestName.S, TestName.L, TestName.CL)
MOST_NEGATIVE = float(np.finfo(np.float64).min)


class PyCSEPEvaluator:
    evaluator_version: str = f"pycsep-{csep_version}"

    def __init__(self) -> None:
        # pycsep result objects from the last evaluate() call, per forecast id, for plotting.
        self._csep_results: dict[str, dict[TestName, Any]] = {}
        # T/W result objects from compare(), keyed by (forecast id, benchmark id), so the paired
        # comparison can be plotted afterwards without re-running the tests.
        self._comparison_results: dict[tuple[str, str], dict[TestName, Any]] = {}

    # ------------------------------------------------------------------ conversions
    @staticmethod
    def to_gridded_forecast(grid: ForecastGrid) -> GriddedForecast:
        origins = np.asarray(grid.cell_origins, dtype=np.float64)
        magnitudes = np.asarray(grid.magnitude_bin_edges, dtype=np.float64)
        region = CartesianGrid2D.from_origins(
            origins, dh=grid.cell_size_deg, magnitudes=magnitudes, name=grid.region_id
        )
        return GriddedForecast(
            start_time=grid.issue_time,
            end_time=grid.window_end,
            data=grid.counts(),
            region=region,
            magnitudes=magnitudes,
            name=grid.id,
        )

    @staticmethod
    def to_csep_catalog(
        target: Catalog, forecast: GriddedForecast, grid: ForecastGrid
    ) -> tuple[CSEPCatalog, dict[str, int]]:
        """Earthquakes with ``mw`` >= threshold inside the grid; everything else is counted."""
        counts = {
            "given": len(target),
            "not_earthquake": 0,
            "no_mw": 0,
            "below_threshold": 0,
            "outside_grid": 0,
            "used": 0,
        }
        threshold = grid.magnitude_bin_edges[0]
        rows: list[tuple[bytes, int, float, float, float, float]] = []
        for e in target.events:
            if e.event_type != EventType.EARTHQUAKE:
                counts["not_earthquake"] += 1
                continue
            if e.mw is None:
                counts["no_mw"] += 1
                continue
            if e.mw < threshold:
                counts["below_threshold"] += 1
                continue
            masked = forecast.region.get_masked(np.asarray([e.longitude]), np.asarray([e.latitude]))
            if bool(masked[0]):
                counts["outside_grid"] += 1
                continue
            epoch_ms = round(e.origin_time.astimezone(UTC).timestamp() * 1000.0)
            depth = e.depth_km if e.depth_km is not None else float("nan")
            rows.append((e.id.encode("utf-8"), epoch_ms, e.latitude, e.longitude, depth, e.mw))
        counts["used"] = len(rows)
        data = np.array(rows, dtype=CSEPCatalog.dtype) if rows else np.empty(0, CSEPCatalog.dtype)
        catalog = CSEPCatalog(data=data, region=forecast.region, name=target.id)
        return catalog, counts

    # ------------------------------------------------------------------ port
    def evaluate(
        self,
        forecast: ForecastGrid,
        target: Catalog,
        tests: Sequence[TestName],
        *,
        n_simulations: int = 1000,
        alpha: float = 0.05,
        seed: int | None = None,
    ) -> list[EvaluationResult]:
        bad = [t for t in tests if t not in CONSISTENCY_TESTS]
        if bad:
            msg = f"evaluate() runs consistency tests only; use compare() for {bad}"
            raise ValueError(msg)
        self._check_window(forecast, target)
        gridded = self.to_gridded_forecast(forecast)
        catalog, counts = self.to_csep_catalog(target, gridded, forecast)
        n_obs = counts["used"]
        notes = json.dumps({"target_filter": counts, "seed": seed}, sort_keys=True)
        common = {
            "forecast_id": forecast.id,
            "model_id": forecast.model_id,
            "alpha": alpha,
            "n_target_events": n_obs,
            "target_window_start": forecast.issue_time,
            "target_window_end": forecast.window_end,
            "target_catalog_hash": target.event_hash(),
            "evaluated_at": utc_now(),
            "evaluator_version": self.evaluator_version,
        }
        out: list[EvaluationResult] = []
        csep_results: dict[TestName, Any] = {}
        for test in tests:
            if test == TestName.N:
                res = pe.number_test(gridded, catalog)
                delta_1, delta_2 = (float(q) for q in res.quantile)
                csep_results[test] = res
                out.append(
                    EvaluationResult(
                        test_name=test,
                        statistic=float(res.observed_statistic),
                        quantile_low=_unit(delta_2),
                        quantile_high=_unit(delta_1),
                        passed=bool(delta_1 >= alpha / 2.0 and delta_2 >= alpha / 2.0),
                        n_simulations=None,
                        notes=notes
                        + f"; forecast_total={gridded.event_count:.4f}; two-sided at alpha/2",
                        **common,
                    )
                )
                continue
            if n_obs == 0:
                out.append(
                    EvaluationResult(
                        test_name=test,
                        statistic=0.0,
                        quantile=None,
                        passed=None,
                        n_simulations=n_simulations,
                        notes=notes + "; no target events: statistic undefined, N-test only",
                        **common,
                    )
                )
                continue
            res = _run_one_sided(test, gridded, catalog, n_simulations, seed)
            csep_results[test] = res
            quantile = _unit(float(res.quantile))
            statistic = float(res.observed_statistic)
            if math.isfinite(statistic):
                out.append(
                    EvaluationResult(
                        test_name=test,
                        statistic=statistic,
                        quantile=quantile,
                        passed=bool(quantile >= alpha),
                        n_simulations=n_simulations,
                        notes=notes,
                        **common,
                    )
                )
            else:
                # log-likelihood -inf: an observed event sits in a bin the forecast gave zero
                # rate. That is a rejection, recorded with the most negative finite float.
                out.append(
                    EvaluationResult(
                        test_name=test,
                        statistic=MOST_NEGATIVE,
                        quantile=0.0,
                        passed=False,
                        n_simulations=n_simulations,
                        notes=notes
                        + "; observed log-likelihood is -inf (event in a zero-rate bin): "
                        "rejected; statistic recorded as the most negative finite float",
                        **common,
                    )
                )
        self._csep_results[forecast.id] = csep_results
        return out

    def compare(
        self,
        forecast: ForecastGrid,
        benchmark: ForecastGrid,
        target: Catalog,
        *,
        alpha: float = 0.05,
    ) -> list[EvaluationResult]:
        if (
            forecast.cell_origins != benchmark.cell_origins
            or forecast.magnitude_bin_edges != benchmark.magnitude_bin_edges
        ):
            msg = "forecast and benchmark must share cells and magnitude bins"
            raise ValueError(msg)
        if forecast.issue_time != benchmark.issue_time or forecast.horizon != benchmark.horizon:
            msg = "forecast and benchmark must cover the same window"
            raise ValueError(msg)
        self._check_window(forecast, target)
        g1 = self.to_gridded_forecast(forecast)
        g2 = self.to_gridded_forecast(benchmark)
        catalog, counts = self.to_csep_catalog(target, g1, forecast)
        n_obs = counts["used"]
        notes = json.dumps({"target_filter": counts}, sort_keys=True)
        common = {
            "forecast_id": forecast.id,
            "model_id": forecast.model_id,
            "alpha": alpha,
            "benchmark_model_id": benchmark.model_id,
            "n_target_events": n_obs,
            "target_window_start": forecast.issue_time,
            "target_window_end": forecast.window_end,
            "target_catalog_hash": target.event_hash(),
            "evaluated_at": utc_now(),
            "evaluator_version": self.evaluator_version,
        }
        key = (forecast.id, benchmark.id)
        self._comparison_results.pop(key, None)
        if n_obs == 0:
            return [
                EvaluationResult(
                    test_name=t,
                    statistic=0.0,
                    passed=None,
                    notes=notes + "; no target events: comparison undefined",
                    **common,
                )
                for t in (TestName.T, TestName.W)
            ]
        t_res = pe.paired_t_test(g1, g2, catalog, alpha=alpha)
        ig = float(t_res.observed_statistic)
        ig_lower, ig_upper = (float(x) for x in t_res.test_distribution)
        t_stat, t_crit, _ = (float(x) for x in t_res.quantile)
        t_defined = n_obs > 1 and math.isfinite(t_stat) and math.isfinite(ig_lower)
        p_t = float(2.0 * stats.t.sf(abs(t_stat), df=n_obs - 1)) if t_defined else None
        out = [
            EvaluationResult(
                test_name=TestName.T,
                statistic=ig if math.isfinite(ig) else 0.0,
                p_value=_unit(p_t) if p_t is not None and math.isfinite(p_t) else None,
                passed=bool(ig_lower > 0.0) if t_defined else None,
                notes=notes
                + f"; ig_ci=[{ig_lower:.5f},{ig_upper:.5f}]; t={t_stat:.4f}; t_crit={t_crit:.4f}"
                + ("" if t_defined else "; t statistic undefined (zero variance or n < 2)"),
                **common,
            )
        ]
        w_res = pe.w_test(g1, g2, catalog)
        z = float(w_res.observed_statistic)
        p_w = float(w_res.quantile)
        w_defined = math.isfinite(z) and math.isfinite(p_w)
        out.append(
            EvaluationResult(
                test_name=TestName.W,
                statistic=z if math.isfinite(z) else 0.0,
                p_value=_unit(p_w) if w_defined else None,
                passed=bool(p_w < alpha and z > 0.0) if w_defined else None,
                notes=notes + "; Wilcoxon signed-rank on log-rate differences",
                **common,
            )
        )
        self._comparison_results[key] = {TestName.T: t_res, TestName.W: w_res}
        return out

    def comparison_plot_bundle(
        self,
        forecast: ForecastGrid,
        benchmark: ForecastGrid,
        results: Sequence[EvaluationResult],
        out_dir: Path,
    ) -> list[Path]:
        """``t-test.png`` (information gain with its CI, W-test overlaid) and ``comparison.json``.

        ``docs/EVALUATION_PROTOCOL.md`` § 8 promises comparison plots in the bundle alongside the
        consistency ones; without them a T/W verdict that decides a promotion has no visual record.

        Must follow a :meth:`compare` call for the same pair on this evaluator: the pycsep result
        objects carry the test distribution the plot needs and are not reconstructible from an
        :class:`EvaluationResult`. When they are absent (a comparison undefined for want of target
        events, or a bundle written by a different evaluator instance) the reason is recorded in
        ``comparison.json`` under ``skipped`` and no plot is invented.
        """
        from csep import plots as csep_plots  # noqa: PLC0415 - heavy import (cartopy) kept local
        from matplotlib import pyplot as plt  # noqa: PLC0415

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        skipped: list[dict[str, str]] = []
        stashed = self._comparison_results.get((forecast.id, benchmark.id))
        path = out_dir / "t-test.png"
        if stashed is None:
            skipped.append(
                {
                    "plot": path.name,
                    "reason": (
                        f"no pycsep comparison result for {forecast.id!r} against "
                        f"{benchmark.id!r} on this evaluator: call compare() first, or the "
                        "comparison was undefined (no target events)"
                    ),
                }
            )
        else:
            t_res, w_res = stashed[TestName.T], stashed[TestName.W]
            t_res.sim_name = forecast.model_id
            t_res.obs_name = benchmark.model_id
            w_res.sim_name = forecast.model_id
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    ax = csep_plots.plot_comparison_test([t_res], [w_res], show=False)
                    ax.set_title(
                        f"{forecast.model_id} vs {benchmark.model_id} — {forecast.id}", fontsize=9
                    )
                    ax.get_figure().savefig(path, dpi=120, bbox_inches="tight")
                    plt.close(ax.get_figure())
                written.append(path)
            except (OSError, RuntimeError, ValueError, AttributeError) as exc:
                skipped.append({"plot": path.name, "reason": f"{type(exc).__name__}: {exc}"})

        summary = {
            "forecast_id": forecast.id,
            "model_id": forecast.model_id,
            "benchmark_forecast_id": benchmark.id,
            "benchmark_model_id": benchmark.model_id,
            "issue_time": forecast.issue_time.isoformat(),
            "window_end": forecast.window_end.isoformat(),
            "evaluator_version": self.evaluator_version,
            "results": [
                {
                    "test": r.test_name.value,
                    "statistic": r.statistic,
                    "p_value": r.p_value,
                    "passed": r.passed,
                    "n_target_events": r.n_target_events,
                    "notes": r.notes,
                }
                for r in results
                if r.test_name in (TestName.T, TestName.W)
            ],
            "plots": [p.name for p in written],
            "skipped": skipped,
            "note": (
                "information gain per earthquake of the forecast over the benchmark, with the "
                "T-test confidence interval; a rate comparison, not a statement about "
                "individual earthquakes."
            ),
        }
        spath = out_dir / "comparison.json"
        spath.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(spath)
        return written

    def plot_bundle(
        self,
        forecast: ForecastGrid,
        target: Catalog,
        results: Sequence[EvaluationResult],
        out_dir: Path,
    ) -> list[Path]:
        """PNG per consistency test plus a rate map and ``summary.json``; never needs network.

        Plots that cannot be produced offline are listed under ``skipped`` in the summary with the
        reason rather than failing the bundle.
        """
        from csep import plots as csep_plots  # noqa: PLC0415 - heavy import (cartopy) kept local
        from matplotlib import pyplot as plt  # noqa: PLC0415

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        skipped: list[dict[str, str]] = []
        csep_results = self._csep_results.get(forecast.id) or self._recompute(
            forecast, target, results
        )
        gridded = self.to_gridded_forecast(forecast)

        for test, res in csep_results.items():
            path = out_dir / f"{test.value.lower()}-test.png"
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    ax = csep_plots.plot_consistency_test(
                        [res], one_sided_lower=test in ONE_SIDED, show=False
                    )
                    ax.set_title(f"{res.name} — {forecast.id}", fontsize=9)
                    ax.get_figure().savefig(path, dpi=120, bbox_inches="tight")
                    plt.close(ax.get_figure())
                written.append(path)
            except (OSError, RuntimeError, ValueError) as exc:
                skipped.append({"plot": path.name, "reason": f"{type(exc).__name__}: {exc}"})
            if test in ONE_SIDED:
                hpath = out_dir / f"{test.value.lower()}-test-distribution.png"
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        ax = csep_plots.plot_test_distribution(res, show=False)
                        ax.get_figure().savefig(hpath, dpi=120, bbox_inches="tight")
                        plt.close(ax.get_figure())
                    written.append(hpath)
                except (OSError, RuntimeError, ValueError) as exc:
                    skipped.append({"plot": hpath.name, "reason": f"{type(exc).__name__}: {exc}"})

        map_path = out_dir / "expected-counts-map.png"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                spatial = gridded.spatial_counts(cartesian=True)
                with np.errstate(divide="ignore"):
                    data = np.log10(np.where(spatial > 0, spatial, np.nan))
                # No basemap, coastline or borders: those need Natural Earth downloads.
                ax = csep_plots.plot_gridded_dataset(
                    data,
                    gridded.region,
                    basemap=None,
                    coastline=False,
                    borders=False,
                    clabel="log10 expected count per cell",
                    title=f"{forecast.id}: expected M>={forecast.magnitude_bin_edges[0]} counts",
                    show=False,
                )
                ax.get_figure().savefig(map_path, dpi=120, bbox_inches="tight")
                plt.close(ax.get_figure())
            written.append(map_path)
        except (OSError, RuntimeError, ValueError) as exc:
            skipped.append({"plot": map_path.name, "reason": f"{type(exc).__name__}: {exc}"})

        summary = {
            "forecast_id": forecast.id,
            "model_id": forecast.model_id,
            "issue_time": forecast.issue_time.isoformat(),
            "window_end": forecast.window_end.isoformat(),
            "total_expected": forecast.total_expected(),
            "evaluator_version": self.evaluator_version,
            "results": [
                {
                    "test": r.test_name.value,
                    "statistic": r.statistic,
                    "quantile": r.quantile,
                    "quantile_low": r.quantile_low,
                    "quantile_high": r.quantile_high,
                    "p_value": r.p_value,
                    "passed": r.passed,
                    "n_target_events": r.n_target_events,
                }
                for r in results
            ],
            "plots": [p.name for p in written],
            "skipped": skipped,
            "note": (
                "basemap and coastlines omitted: they need network downloads; "
                "rupture does not predict earthquakes."
            ),
        }
        spath = out_dir / "summary.json"
        spath.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(spath)
        return written

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _check_window(forecast: ForecastGrid, target: Catalog) -> None:
        earliest = target.min_origin_time()
        latest = target.max_origin_time()
        if earliest is not None and earliest < forecast.issue_time:
            msg = "target slice starts before the forecast issue time"
            raise ValueError(msg)
        if latest is not None and latest >= forecast.window_end:
            msg = "target slice reaches past the forecast window end"
            raise ValueError(msg)

    def _recompute(
        self, forecast: ForecastGrid, target: Catalog, results: Sequence[EvaluationResult]
    ) -> dict[TestName, Any]:
        gridded = self.to_gridded_forecast(forecast)
        catalog, counts = self.to_csep_catalog(target, gridded, forecast)
        out: dict[TestName, Any] = {}
        for r in results:
            if r.test_name == TestName.N:
                out[r.test_name] = pe.number_test(gridded, catalog)
            elif r.test_name in ONE_SIDED and counts["used"] > 0 and r.n_simulations:
                seed = _seed_from_notes(r.notes)
                out[r.test_name] = _run_one_sided(
                    r.test_name, gridded, catalog, r.n_simulations, seed
                )
        return out


def _run_one_sided(
    test: TestName, gridded: GriddedForecast, catalog: CSEPCatalog, n_sim: int, seed: int | None
) -> Any:
    fn = {
        TestName.M: pe.magnitude_test,
        TestName.S: pe.spatial_test,
        TestName.L: pe.likelihood_test,
        TestName.CL: pe.conditional_likelihood_test,
    }[test]
    return fn(gridded, catalog, num_simulations=n_sim, seed=seed)


def _unit(x: float) -> float:
    """Clamp to [0, 1] (pycsep's epsilon can push a quantile a hair outside)."""
    return float(min(1.0, max(0.0, x)))


def _seed_from_notes(notes: str | None) -> int | None:
    if not notes:
        return None
    try:
        head = json.loads(notes.split(";", 1)[0])
    except json.JSONDecodeError:
        return None
    seed = head.get("seed")
    return int(seed) if seed is not None else None
