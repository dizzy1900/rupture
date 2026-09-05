"""Pseudo-prospective schedule runner (protocol § 6-7, ADR-0015).

From ``start`` to ``end`` in steps of ``step``: at every issue time, issue a forecast from the
current fit using only events with ``origin_time < issue_time``; score the window
``[issue, issue + horizon)`` if it closes at or before the catalogue end; refit only at declared
boundaries (yearly on 1 January, or never) and log each refit. Three leakage assertions run on
every window and raise :class:`LeakageError` (they never filter):

1. the target slice lies inside ``[issue, issue + horizon)``;
2. ``parameter_snapshot_hash`` is constant across windows unless a ``refit`` record exists for a
   boundary in ``(previous issue, issue]``;
3. every fit's training catalogue ends strictly before its cutoff.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from csep import __version__ as csep_version

from rupture.adapters.evaluation.pycsep import PyCSEPEvaluator
from rupture.adapters.forecasting.etas_mizrahi import ETAS_COMMIT, MizrahiETAS, load_fit
from rupture.adapters.forecasting.leakage import LeakageError, assert_within_window
from rupture.adapters.storage.run_log import JsonlTracker
from rupture.adapters.storage.zarr_store import ZarrGridStore
from rupture.domain import (
    Catalog,
    EvaluationResult,
    FitResult,
    Region,
    TestName,
    format_horizon,
    utc_now,
)
from rupture.pipelines.evaluate import DEFAULT_TESTS, evaluate_forecast, target_slice
from rupture.pipelines.fit_etas import fit_etas
from rupture.pipelines.run_forecast import issue_forecast
from rupture.ports import RunRecord, Tracker

RefitPolicy = Literal["yearly", "none"]
ONE_SIDED_TESTS: tuple[TestName, ...] = (TestName.M, TestName.S, TestName.L, TestName.CL)


@dataclass
class WindowRecord:
    issue_time: datetime
    window_end: datetime
    forecast_id: str
    fit_cutoff: datetime
    parameter_snapshot_hash: str
    total_expected: float
    n_target_events: int
    n_excluded_non_earthquake: int
    n_excluded_no_mw: int
    n_only: bool
    tests: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "issue_time": self.issue_time.isoformat(),
            "window_end": self.window_end.isoformat(),
            "forecast_id": self.forecast_id,
            "fit_cutoff": self.fit_cutoff.isoformat(),
            "parameter_snapshot_hash": self.parameter_snapshot_hash,
            "total_expected": self.total_expected,
            "n_target_events": self.n_target_events,
            "n_excluded_non_earthquake": self.n_excluded_non_earthquake,
            "n_excluded_no_mw": self.n_excluded_no_mw,
            "n_only": self.n_only,
            "tests": self.tests,
        }


@dataclass(frozen=True)
class RefitLogEntry:
    boundary: datetime
    parameter_snapshot_hash: str
    training_catalog_hash: str
    run_id: str


def issue_times(
    start: datetime, end: datetime, step: timedelta, horizon: timedelta
) -> list[datetime]:
    """Issue times from ``start`` whose window ``[t, t + horizon)`` closes at or before ``end``."""
    if step <= timedelta(0) or horizon <= timedelta(0):
        msg = "step and horizon must be positive"
        raise ValueError(msg)
    out: list[datetime] = []
    t = start
    while t + horizon <= end:
        out.append(t)
        t += step
    return out


def refit_boundaries(policy: RefitPolicy, start: datetime, last_issue: datetime) -> list[datetime]:
    """Declared refit boundaries strictly after ``start`` and at or before ``last_issue``."""
    if policy == "none":
        return []
    out: list[datetime] = []
    year = start.year + 1
    while True:
        boundary = datetime(year, 1, 1, tzinfo=UTC)
        if boundary > last_issue:
            break
        if boundary > start:
            out.append(boundary)
        year += 1
    return out


def check_fit_training(fit: FitResult) -> None:
    """Leakage rule 3 on the persisted record."""
    latest_text = fit.diagnostics.get("training_max_origin_time")
    if latest_text is None:
        msg = f"fit {fit.parameter_snapshot_hash[:12]} lacks training_max_origin_time diagnostics"
        raise LeakageError(msg)
    latest = datetime.fromisoformat(latest_text)
    if latest >= fit.fit_cutoff:
        msg = (
            f"leakage: fit training catalogue ends {latest.isoformat()} which is not before the "
            f"cutoff {fit.fit_cutoff.isoformat()}"
        )
        raise LeakageError(msg)


def check_snapshot_constancy(
    windows: Sequence[WindowRecord], refits: Sequence[RefitLogEntry]
) -> None:
    """Leakage rule 4 (protocol § 7): hash changes only across a logged refit boundary."""
    previous: WindowRecord | None = None
    for w in windows:
        if previous is not None and w.parameter_snapshot_hash != previous.parameter_snapshot_hash:
            covered = [
                r
                for r in refits
                if previous.issue_time < r.boundary <= w.issue_time
                and r.parameter_snapshot_hash == w.parameter_snapshot_hash
            ]
            if not covered:
                msg = (
                    f"leakage: parameter_snapshot_hash changed between {previous.issue_time} and "
                    f"{w.issue_time} without a logged refit at a declared boundary"
                )
                raise LeakageError(msg)
        previous = w


def _test_summary(r: EvaluationResult) -> dict[str, Any]:
    return {
        "statistic": r.statistic,
        "quantile": r.quantile,
        "quantile_low": r.quantile_low,
        "quantile_high": r.quantile_high,
        "passed": r.passed,
    }


def _pass_rates(windows: Sequence[WindowRecord], tests: Sequence[TestName]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in tests:
        scored = [
            w for w in windows if t.value in w.tests and w.tests[t.value]["passed"] is not None
        ]
        passed = sum(1 for w in scored if w.tests[t.value]["passed"])
        out[t.value] = {
            "passed": passed,
            "scored": len(scored),
            "rate": (passed / len(scored)) if scored else None,
            "denominator_rule": "all evaluated windows"
            if t == TestName.N
            else "windows with >= 1 target event",
        }
    return out


def run_schedule(
    catalog: Catalog,
    region: Region,
    *,
    start: datetime,
    end: datetime,
    step: timedelta,
    horizon: timedelta,
    baselines_dir: Path,
    forecasts_dir: Path,
    reports_dir: Path,
    refit: RefitPolicy = "yearly",
    model: MizrahiETAS | None = None,
    evaluator: PyCSEPEvaluator | None = None,
    tracker: Tracker | None = None,
    tests: Sequence[TestName] = DEFAULT_TESTS,
    n_simulations: int = 100,
    eval_simulations: int = 1000,
    alpha: float = 0.05,
    seed: int | None = None,
    mc: float | None = None,
    plots: bool = False,
    use_existing_fit: bool = True,
) -> dict[str, Any]:
    """Run the schedule and write ``reports/eval/schedule-<region>-<model>.json``."""
    model = model or MizrahiETAS()
    evaluator = evaluator or PyCSEPEvaluator()
    tracker = tracker or JsonlTracker(JsonlTracker.default_path(forecasts_dir.parent, region.id))
    store = ZarrGridStore(forecasts_dir)
    reports_dir = Path(reports_dir)
    times = issue_times(start, end, step, horizon)
    if not times:
        msg = "no issue time has a window closing at or before the schedule end"
        raise ValueError(msg)
    catalogue_end = catalog.bounds.end_time if catalog.bounds else catalog.max_origin_time()
    boundaries = refit_boundaries(refit, start, times[-1])

    fit = _initial_fit(
        catalog,
        region,
        start,
        baselines_dir=baselines_dir,
        mc=mc,
        model=model,
        tracker=tracker,
        use_existing_fit=use_existing_fit,
    )

    refits: list[RefitLogEntry] = []
    windows: list[WindowRecord] = []
    skipped: list[dict[str, str]] = []
    pending = list(boundaries)
    for issue in times:
        while pending and pending[0] <= issue:
            boundary = pending.pop(0)
            fit = fit_etas(
                catalog,
                region,
                boundary,
                baselines_dir=baselines_dir,
                mc=mc,
                model=model,
                tracker=tracker,
                kind="refit",
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
        grid = issue_forecast(
            model,
            catalog,
            issue,
            horizon,
            n_simulations=n_simulations,
            seed=seed,
            store=store,
            tracker=tracker,
        )
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
        assert_within_window(target, issue, window_close, what="schedule target")
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
        by_name = {r.test_name: r for r in results}
        n_target = by_name[tests[0]].n_target_events if results else 0
        n_non_eq = sum(1 for e in target.events if e.event_type != "earthquake")
        n_no_mw = sum(1 for e in target.events if e.event_type == "earthquake" and e.mw is None)
        windows.append(
            WindowRecord(
                issue_time=issue,
                window_end=window_close,
                forecast_id=grid.id,
                fit_cutoff=fit.fit_cutoff,
                parameter_snapshot_hash=grid.parameter_snapshot_hash,
                total_expected=grid.total_expected(),
                n_target_events=n_target,
                n_excluded_non_earthquake=n_non_eq,
                n_excluded_no_mw=n_no_mw,
                n_only=n_target == 0,
                tests={r.test_name.value: _test_summary(r) for r in results},
            )
        )

    check_snapshot_constancy(windows, refits)
    schedule = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "step": format_horizon(step),
        "horizon": format_horizon(horizon),
        "refit_policy": refit,
        "n_simulations": n_simulations,
        "eval_simulations": eval_simulations,
        "alpha": alpha,
        "seed": seed,
        "tests": [t.value for t in tests],
    }
    report = _report(
        catalog=catalog,
        region=region,
        model=model,
        schedule=schedule,
        times=times,
        windows=windows,
        skipped=skipped,
        refits=refits,
        catalogue_end=catalogue_end,
        tests=tests,
    )
    reports_dir.joinpath("eval").mkdir(parents=True, exist_ok=True)
    path = reports_dir / "eval" / f"schedule-{region.id}-{model.model_id}.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tracker.log(
        RunRecord(
            run_id=f"schedule-{region.id}-{uuid.uuid4().hex[:8]}",
            kind="schedule",
            at=utc_now(),
            region_id=region.id,
            model_id=model.model_id,
            parameter_snapshot_hash=fit.parameter_snapshot_hash,
            inputs=schedule,
            outputs={"report": str(path), "n_scored": len(windows), "n_issued": len(times)},
        )
    )
    report["report_path"] = str(path)
    return report


def _initial_fit(
    catalog: Catalog,
    region: Region,
    start: datetime,
    *,
    baselines_dir: Path,
    mc: float | None,
    model: MizrahiETAS,
    tracker: Tracker,
    use_existing_fit: bool,
) -> FitResult:
    """Reuse a persisted, converged fit with the same cutoff *and* training slice; else fit now."""
    fit: FitResult | None = None
    if use_existing_fit:
        try:
            candidate = load_fit(baselines_dir, region.id)
        except FileNotFoundError:
            candidate = None
        if candidate is not None and candidate.fit_cutoff == start and candidate.converged:
            in_hand = MizrahiETAS.training_slice(catalog, region, start, candidate.mc)
            if in_hand.event_hash() != candidate.training_catalog_hash:
                msg = (
                    f"persisted fit for {region.id} at {start.isoformat()} was trained on a "
                    f"different slice (training_catalog_hash "
                    f"{candidate.training_catalog_hash[:12]} vs {in_hand.event_hash()[:12]} for "
                    f"the catalogue in hand, {len(in_hand)} events); refit, or pass a catalogue "
                    "that matches the fit"
                )
                raise ValueError(msg)
            fit = candidate
            model.load_fit(fit, region)
    if fit is None:
        fit = fit_etas(
            catalog,
            region,
            start,
            baselines_dir=baselines_dir,
            mc=mc,
            model=model,
            tracker=tracker,
            kind="fit",
        )
    check_fit_training(fit)
    return fit


def _report(
    *,
    catalog: Catalog,
    region: Region,
    model: MizrahiETAS,
    schedule: dict[str, Any],
    times: Sequence[datetime],
    windows: Sequence[WindowRecord],
    skipped: Sequence[dict[str, str]],
    refits: Sequence[RefitLogEntry],
    catalogue_end: datetime | None,
    tests: Sequence[TestName],
) -> dict[str, Any]:
    return {
        "region_id": region.id,
        "model_id": model.model_id,
        "model_version": model.model_version,
        "etas_commit": ETAS_COMMIT,
        "pycsep_version": csep_version,
        "catalog_id": catalog.id,
        "catalog_event_hash": catalog.event_hash(),
        "catalogue_end": catalogue_end.isoformat() if catalogue_end else None,
        "schedule": schedule,
        "n_issued": len(times),
        "n_scored": len(windows),
        "not_scored": skipped,
        "windows": [w.as_dict() for w in windows],
        "pass_rates": _pass_rates(windows, tests),
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
            "target_inside_window": "asserted per window",
            "snapshot_constant_between_refits": "asserted over the schedule",
            "training_before_cutoff": "asserted per fit",
        },
        "generated_at": utc_now().isoformat(),
        "note": "Pass means not rejected at alpha; it is not a skill claim. "
        "Rupture research output, not an operational alert.",
    }
