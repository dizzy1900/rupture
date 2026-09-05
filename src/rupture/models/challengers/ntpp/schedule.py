"""Pseudo-prospective schedule for the challenger, and the paired comparison against ETAS.

This mirrors :mod:`rupture.pipelines.schedule` — same issue times, same target slices, same
leakage assertions, the same :class:`~rupture.adapters.evaluation.pycsep.PyCSEPEvaluator` — and
adds the one thing the baseline runner has no need for: at every issue time it also issues the
ETAS forecast for the same window and runs the paired T- and W-tests between them. Reusing the
baseline's helpers rather than reimplementing them is deliberate; a challenger scored by its own
private harness is not scored against the baseline at all.

Nothing here decides whether the challenger is any good. :func:`promotion_verdict` applies § 10 of
the protocol mechanically and reports which conditions failed.
a challenger that scores well has issued a rate forecast
that was not rejected, which is not a claim about any future event.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from csep import __version__ as csep_version

from rupture.adapters.evaluation.pycsep import PyCSEPEvaluator
from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.adapters.forecasting.leakage import assert_within_window
from rupture.adapters.storage.run_log import JsonlTracker
from rupture.adapters.storage.zarr_store import ZarrGridStore
from rupture.domain import (
    Catalog,
    EvaluationResult,
    FitResult,
    ForecastGrid,
    Region,
    TestName,
    format_horizon,
    parse_horizon,
    utc_now,
)
from rupture.models.challengers.ntpp.adapter import NeuralTPPForecaster, save_fit
from rupture.models.promotion import (
    MIN_CONSECUTIVE_WINDOWS,
    MIN_REGIONS,
    longest_consecutive_run,
    pass_rate_table,
    pooled_paired_test,
    pooling_terms,
    region_verdict,
)
from rupture.pipelines.evaluate import DEFAULT_TESTS, evaluate_forecast, target_slice
from rupture.pipelines.run_forecast import history_for
from rupture.pipelines.schedule import (
    RefitLogEntry,
    RefitPolicy,
    WindowRecord,
    check_fit_training,
    check_snapshot_constancy,
    issue_times,
    refit_boundaries,
)
from rupture.ports import RunRecord, Tracker

CONSISTENCY: tuple[TestName, ...] = DEFAULT_TESTS
#: Aliases: the values live in ``rupture.models.promotion`` and are named here for the CLI.
MIN_PROMOTION_WINDOWS = MIN_CONSECUTIVE_WINDOWS  # protocol § 10 condition 1
MIN_PROMOTION_REGIONS = MIN_REGIONS  # protocol § 10 condition 3


@dataclass
class ChallengerWindow:
    """One scored window: the challenger's consistency tests plus the comparison against ETAS."""

    issue_time: datetime
    window_end: datetime
    forecast_id: str
    fit_cutoff: datetime
    parameter_snapshot_hash: str
    total_expected: float
    benchmark_total_expected: float | None
    n_target_events: int
    n_excluded_non_earthquake: int
    n_only: bool
    tests: dict[str, dict[str, Any]] = field(default_factory=dict)
    comparison: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: the benchmark's own consistency tests on the same target slice, when asked for
    benchmark_tests: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: per-event log rates for both models, which the schedule-pooled paired T-test needs
    #: (ADR-0040 condition 2). ``None`` when there was no benchmark to pair against.
    pooling: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "issue_time": self.issue_time.isoformat(),
            "window_end": self.window_end.isoformat(),
            "forecast_id": self.forecast_id,
            "fit_cutoff": self.fit_cutoff.isoformat(),
            "parameter_snapshot_hash": self.parameter_snapshot_hash,
            "total_expected": self.total_expected,
            "benchmark_total_expected": self.benchmark_total_expected,
            "n_target_events": self.n_target_events,
            "n_excluded_non_earthquake": self.n_excluded_non_earthquake,
            "n_only": self.n_only,
            "tests": self.tests,
            "comparison": self.comparison,
            "benchmark_tests": self.benchmark_tests,
            "pooling": self.pooling,
        }


def _as_window_record(window: ChallengerWindow) -> WindowRecord:
    """The baseline's record type, so its leakage check runs unmodified on challenger windows."""
    return WindowRecord(
        issue_time=window.issue_time,
        window_end=window.window_end,
        forecast_id=window.forecast_id,
        fit_cutoff=window.fit_cutoff,
        parameter_snapshot_hash=window.parameter_snapshot_hash,
        total_expected=window.total_expected,
        n_target_events=window.n_target_events,
        n_excluded_non_earthquake=window.n_excluded_non_earthquake,
        n_excluded_no_mw=0,
        n_only=window.n_only,
        tests=window.tests,
    )


def _summary(result: EvaluationResult) -> dict[str, Any]:
    return {
        "statistic": result.statistic,
        "quantile": result.quantile,
        "quantile_low": result.quantile_low,
        "quantile_high": result.quantile_high,
        "p_value": result.p_value,
        "passed": result.passed,
    }


def pass_rates(
    windows: Sequence[ChallengerWindow],
    tests: Sequence[TestName] = CONSISTENCY,
    *,
    attribute: str = "tests",
) -> dict[str, Any]:
    """Pass rate per test with its denominator. Never a bare percentage (protocol § 5).

    ``attribute`` selects which set of results to aggregate: the challenger's (``tests``) or, when
    the benchmark was scored in the same run, its own (``benchmark_tests``).
    """
    out: dict[str, Any] = {}
    for test in tests:
        results = [(w, getattr(w, attribute)) for w in windows]
        scored = [
            (w, r) for w, r in results if test.value in r and r[test.value]["passed"] is not None
        ]
        passed = sum(1 for _, r in scored if r[test.value]["passed"])
        out[test.value] = {
            "passed": passed,
            "scored": len(scored),
            "rate": (passed / len(scored)) if scored else None,
            "denominator_rule": (
                "all evaluated windows" if test == TestName.N else "windows with >= 1 target event"
            ),
        }
    return out


def comparison_summary(windows: Sequence[ChallengerWindow]) -> dict[str, Any]:
    """Aggregate the paired tests: how often the challenger beat ETAS, and by how much."""
    scored = [
        w for w in windows if w.comparison.get(TestName.T.value, {}).get("passed") is not None
    ]
    gains = [float(w.comparison[TestName.T.value]["statistic"]) for w in scored]
    t_wins = sum(1 for w in scored if w.comparison[TestName.T.value]["passed"])
    w_scored = [
        w for w in windows if w.comparison.get(TestName.W.value, {}).get("passed") is not None
    ]
    w_wins = sum(1 for w in w_scored if w.comparison[TestName.W.value]["passed"])
    disagreements = sum(
        1
        for w in scored
        if w.comparison.get(TestName.W.value, {}).get("passed") is not None
        and w.comparison[TestName.T.value]["passed"] != w.comparison[TestName.W.value]["passed"]
    )
    return {
        "windows_compared": len(scored),
        "t_test_wins": t_wins,
        "w_test_wins": w_wins,
        "w_test_windows": len(w_scored),
        "t_w_disagreements": disagreements,
        "mean_information_gain_per_event": (sum(gains) / len(gains)) if gains else None,
        "windows_with_positive_gain": sum(1 for g in gains if g > 0.0),
        "note": (
            "information gain is the challenger's mean per-event log-rate advantage over ETAS; "
            "a positive value in a single window is not a skill claim"
        ),
    }


def run_ntpp_schedule(  # noqa: PLR0915 - one linear pass over the schedule
    catalog: Catalog,
    region: Region,
    model: NeuralTPPForecaster,
    *,
    start: datetime,
    end: datetime,
    step: timedelta,
    horizon: timedelta,
    baselines_dir: Path,
    forecasts_dir: Path,
    reports_dir: Path,
    benchmark: MizrahiETAS | None = None,
    benchmark_cache: dict[datetime, ForecastGrid] | None = None,
    evaluate_benchmark: bool = False,
    refit: RefitPolicy = "none",
    evaluator: PyCSEPEvaluator | None = None,
    tracker: Tracker | None = None,
    tests: Sequence[TestName] = CONSISTENCY,
    n_simulations: int = 200,
    benchmark_simulations: int = 200,
    eval_simulations: int = 1000,
    alpha: float = 0.05,
    seed: int | None = None,
    mc: float | None = None,
    plots: bool = False,
    label: str | None = None,
) -> dict[str, Any]:
    """Issue, score and compare on the protocol schedule; write the aggregate report.

    ``model`` must already hold a fit whose cutoff is ``start`` (fit it, or load a persisted one,
    before calling). ``benchmark``, if given, must already hold the ETAS fit for the same cutoff;
    both then see exactly the same history at every issue time, which is the only way the paired
    comparison means anything.

    ``evaluate_benchmark`` additionally scores the benchmark's own consistency tests on the same
    target slices, so the two models' pass rates come from one run and one set of grids rather
    than from two runs that might differ in simulation count or refit policy.

    ``benchmark_cache`` maps issue time to the benchmark's grid. When given it is read from and
    written to, so a later run over the same schedule — an ablation, say — reuses the identical
    benchmark grids instead of resimulating them. Reuse is only sound because the benchmark is
    deterministic given its fit and seed; a grid whose issue time is already in the cache is used
    as-is, and the fit it came from is recorded in the report.
    """
    evaluator = evaluator or PyCSEPEvaluator()
    tracker = tracker or JsonlTracker(JsonlTracker.default_path(forecasts_dir.parent, region.id))
    store = ZarrGridStore(forecasts_dir)
    reports_dir = Path(reports_dir)
    times = issue_times(start, end, step, horizon)
    if not times:
        msg = "no issue time has a window closing at or before the schedule end"
        raise ValueError(msg)
    fit = model.fit_result
    if fit is None:
        msg = "the challenger has no fit loaded; call fit() or load_fit() first"
        raise RuntimeError(msg)
    check_fit_training(fit)
    catalogue_end = catalog.bounds.end_time if catalog.bounds else catalog.max_origin_time()
    pending = list(refit_boundaries(refit, start, times[-1]))

    refits: list[RefitLogEntry] = []
    windows: list[ChallengerWindow] = []
    skipped: list[dict[str, str]] = []
    for issue in times:
        while pending and pending[0] <= issue:
            boundary = pending.pop(0)
            fit = _refit(
                model,
                catalog,
                region,
                boundary,
                baselines_dir=baselines_dir,
                mc=mc,
                tracker=tracker,
            )
            check_fit_training(fit)
            refits.append(
                RefitLogEntry(
                    boundary=boundary,
                    parameter_snapshot_hash=fit.parameter_snapshot_hash,
                    training_catalog_hash=fit.training_catalog_hash,
                    run_id=f"refit-{region.id}-{boundary:%Y%m%dT%H%M%SZ}",
                )
            )
        history = history_for(catalog, issue, fit.mc)
        grid = model.forecast(history, issue, horizon, n_simulations=n_simulations, seed=seed)
        store.save(grid)
        _log_issue(tracker, grid, history, n_simulations, seed)
        window_close = issue + horizon
        if catalogue_end is None or window_close > catalogue_end:
            skipped.append(
                {
                    "issue_time": issue.isoformat(),
                    "reason": "window closes after the catalogue end; issued, not scored",
                }
            )
            continue
        target = target_slice(catalog, grid, region)
        assert_within_window(target, issue, window_close, what="ntpp schedule target")
        results = evaluate_forecast(
            grid,
            catalog,
            evaluator,
            out_dir=reports_dir / "eval" / grid.id,
            region=region,
            tests=tests,
            n_simulations=eval_simulations,
            alpha=alpha,
            seed=seed,
            plots=plots,
            tracker=tracker,
        )
        benchmark_grid: ForecastGrid | None = None
        pooling: dict[str, Any] | None = None
        comparison: list[EvaluationResult] = []
        benchmark_results: list[EvaluationResult] = []
        if benchmark is not None:
            cached = benchmark_cache.get(issue) if benchmark_cache is not None else None
            benchmark_grid = cached or benchmark.forecast(
                history, issue, horizon, n_simulations=benchmark_simulations, seed=seed
            )
            if benchmark_cache is not None and cached is None:
                benchmark_cache[issue] = benchmark_grid
            comparison = evaluator.compare(grid, benchmark_grid, target, alpha=alpha)
            pooling = pooling_terms(evaluator, grid, benchmark_grid, target)
            if evaluate_benchmark:
                benchmark_results = evaluate_forecast(
                    benchmark_grid,
                    catalog,
                    evaluator,
                    out_dir=reports_dir / "eval" / benchmark_grid.id,
                    region=region,
                    tests=tests,
                    n_simulations=eval_simulations,
                    alpha=alpha,
                    seed=seed,
                    plots=False,
                    tracker=tracker,
                )
        by_name = {r.test_name: r for r in results}
        n_target = by_name[tests[0]].n_target_events if results else 0
        windows.append(
            ChallengerWindow(
                issue_time=issue,
                window_end=window_close,
                forecast_id=grid.id,
                fit_cutoff=fit.fit_cutoff,
                parameter_snapshot_hash=grid.parameter_snapshot_hash,
                total_expected=grid.total_expected(),
                benchmark_total_expected=(
                    benchmark_grid.total_expected() if benchmark_grid is not None else None
                ),
                n_target_events=n_target,
                n_excluded_non_earthquake=sum(
                    1 for e in target.events if e.event_type != "earthquake"
                ),
                n_only=n_target == 0,
                tests={r.test_name.value: _summary(r) for r in results},
                comparison={r.test_name.value: _summary(r) for r in comparison},
                benchmark_tests={r.test_name.value: _summary(r) for r in benchmark_results},
                pooling=pooling,
            )
        )

    # Leakage rule 4 is checked by the baseline's own function, on the baseline's own record
    # type, so the challenger cannot drift into a laxer version of the same check.
    check_snapshot_constancy([_as_window_record(w) for w in windows], refits)
    schedule_inputs: dict[str, Any] = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": format_horizon(step),
        "horizon": format_horizon(horizon),
        "refit_policy": refit,
        "n_simulations": n_simulations,
        "benchmark_simulations": benchmark_simulations,
        "eval_simulations": eval_simulations,
        "alpha": alpha,
        "seed": seed,
        "tests": [t.value for t in tests],
    }
    report = {
        "region_id": region.id,
        "model_id": model.model_id,
        "model_version": model.model_version,
        "label": label or model.model_id,
        "benchmark_model_id": benchmark.model_id if benchmark is not None else None,
        "config": model.config.to_dict(),
        "config_hash": model.config.config_hash(),
        "pycsep_version": csep_version,
        "catalog_id": catalog.id,
        "catalog_event_hash": catalog.event_hash(),
        "catalogue_end": catalogue_end.isoformat() if catalogue_end else None,
        "schedule": schedule_inputs,
        "n_issued": len(times),
        "n_scored": len(windows),
        "not_scored": skipped,
        "windows": [w.as_dict() for w in windows],
        "pass_rates": pass_rates(windows, tests),
        "benchmark_pass_rates": (
            pass_rates(windows, tests, attribute="benchmark_tests") if evaluate_benchmark else None
        ),
        "comparison_summary": comparison_summary(windows),
        # Condition 2 of the promotion rule (ADR-0040): one paired T-test over every target event
        # in the schedule, not a tally of per-window tests. Recorded here so the verdict is
        # recomputable from the committed report alone.
        "pooled_paired_test": (
            pooled_paired_test([w.as_dict() for w in windows]) if benchmark is not None else None
        ),
        "refits": [
            {
                "boundary": r.boundary.isoformat(),
                "parameter_snapshot_hash": r.parameter_snapshot_hash,
                "training_catalog_hash": r.training_catalog_hash,
                "run_id": r.run_id,
            }
            for r in refits
        ],
        "leakage_checks": {
            "history_before_issue_time": "asserted per window by the adapter",
            "target_inside_window": "asserted per window",
            "snapshot_constant_between_refits": "asserted over the schedule",
            "training_before_cutoff": "asserted per fit",
        },
        "generated_at": utc_now().isoformat(),
        "note": (
            "Pass means not rejected at alpha; it is not a skill claim. "
            "Rupture research output, not an operational alert."
        ),
    }
    reports_dir.joinpath("eval").mkdir(parents=True, exist_ok=True)
    name = label or model.model_id
    path = reports_dir / "eval" / f"schedule-{region.id}-{name}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tracker.log(
        RunRecord(
            run_id=f"schedule-{region.id}-{uuid.uuid4().hex[:8]}",
            kind="schedule",
            at=utc_now(),
            region_id=region.id,
            model_id=model.model_id,
            parameter_snapshot_hash=fit.parameter_snapshot_hash,
            inputs=schedule_inputs,
            outputs={"report": str(path), "n_scored": len(windows), "n_issued": len(times)},
        )
    )
    report["report_path"] = str(path)
    return report


def _refit(
    model: NeuralTPPForecaster,
    catalog: Catalog,
    region: Region,
    boundary: datetime,
    *,
    baselines_dir: Path,
    mc: float | None,
    tracker: Tracker,
) -> FitResult:
    """Refit at a declared boundary with the frozen configuration, archived but not canonical."""
    fit = model.fit(catalog, region, boundary, mc=mc)
    save_fit(fit, model.state_dict_json(), baselines_dir, canonical=False)
    tracker.log(
        RunRecord(
            run_id=f"refit-{region.id}-{boundary:%Y%m%dT%H%M%SZ}",
            kind="refit",
            at=utc_now(),
            region_id=region.id,
            model_id=model.model_id,
            parameter_snapshot_hash=fit.parameter_snapshot_hash,
            inputs={"boundary": boundary.isoformat(), "catalog_id": catalog.id},
            outputs={
                "training_catalog_hash": fit.training_catalog_hash,
                "n_events": fit.n_events,
                "converged": fit.converged,
            },
        )
    )
    return fit


def _log_issue(
    tracker: Tracker,
    grid: ForecastGrid,
    history: Catalog,
    n_simulations: int,
    seed: int | None,
) -> None:
    tracker.log(
        RunRecord(
            run_id=f"issue-{grid.id}-{uuid.uuid4().hex[:8]}",
            kind="issue",
            at=utc_now(),
            region_id=grid.region_id,
            model_id=grid.model_id,
            parameter_snapshot_hash=grid.parameter_snapshot_hash,
            inputs={
                "issue_time": grid.issue_time.isoformat(),
                "horizon_seconds": int(grid.horizon.total_seconds()),
                "history_events": len(history),
                "history_hash": history.event_hash(),
                "n_simulations": n_simulations,
                "seed": seed,
            },
            outputs={"forecast_id": grid.id, "total_expected": grid.total_expected()},
        )
    )


def promotion_verdict(
    challenger: dict[str, Any], baseline_pass_rates: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Apply protocol § 10 to one region's report, through the single encoding in ``promotion``.

    This function once held its own reading of condition 2 — a strict majority of per-window
    T-test wins — which differed from the ensemble runner's pooled test. ADR-0040 settled the
    reading (the pooled test over the schedule's target events, because "over those windows" is
    one test, and a 30-day window here holds one or two target events); what remains here is the
    plumbing from this report's shapes to the rule's arguments.

    ``baseline_pass_rates`` is the ETAS pass-rate table to compare against. Passing ``None`` is
    not a favourable default: every test then has no comparable rate and condition 1 fails.
    """
    schedule = challenger.get("schedule") or {}
    step = parse_horizon(str(schedule.get("step") or "30d"))
    consecutive = longest_consecutive_run(
        [w.get("issue_time") for w in challenger.get("windows") or []], step
    )
    verdict = region_verdict(
        region_id=str(challenger.get("region_id") or ""),
        model_id=str(challenger.get("model_id") or ""),
        challenger_rates=pass_rate_table(challenger),
        baseline_rates=pass_rate_table({"pass_rates": baseline_pass_rates or {}}),
        consecutive_windows=consecutive,
        pooled=challenger.get("pooled_paired_test"),
        per_window=challenger.get("comparison_summary"),
        baseline_label=str(challenger.get("benchmark_model_id") or "etas-mizrahi"),
    )
    return {"n_scored_windows": int(challenger.get("n_scored", 0)), **verdict}
