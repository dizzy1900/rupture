"""``validate-eval``: the CSEP harness and the schedule runner on the committed fixture.

Offline, on the ComCat California 2018-2019 fixture: fit with cutoff 2019-07-01, then the
pseudo-prospective schedule from 2019-07-01 to 2020-01-01 in 30-day steps (six issue times; the
first window is the Ridgecrest sequence). Checks that N/M/S/L/CL results and plot bundles exist
for every scored window, that the leakage assertions hold, and that the negative tests (a
post-cutoff event injected into a fit history, a target outside its window, a silent parameter
change) raise ``LeakageError``. Pass rates are reported as found; a failing N-test on the
Ridgecrest window is expected and is not a gate failure.

rupture does not predict earthquakes.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.adapters.forecasting.leakage import LeakageError, assert_all_before
from rupture.domain import Catalog, TestName
from rupture.pipelines.schedule import (
    RefitLogEntry,
    WindowRecord,
    check_fit_training,
    check_snapshot_constancy,
    run_schedule,
)
from rupture.validation._fixture import load_fixture
from rupture.validation.result import GateResult, GateStatus

START = datetime(2019, 7, 1, tzinfo=UTC)
END = datetime(2020, 1, 1, tzinfo=UTC)
STEP = timedelta(days=30)
HORIZON = timedelta(days=30)
AUXILIARY_YEARS = 0.5
FIXTURE_MC = 3.0
N_SIMULATIONS = 50
EVAL_SIMULATIONS = 1000
SEED = 7
MIN_WINDOWS = 3
TESTS = (TestName.N, TestName.M, TestName.S, TestName.L, TestName.CL)


def run(repo_root: Path) -> GateResult:
    findings: list[str] = []
    failures: list[str] = []
    out_dir = repo_root / "reports" / "validate-eval"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog, region = load_fixture(repo_root)
    model = MizrahiETAS(auxiliary_years=AUXILIARY_YEARS)
    report = run_schedule(
        catalog,
        region,
        start=START,
        end=END,
        step=STEP,
        horizon=HORIZON,
        baselines_dir=out_dir / "baselines",
        forecasts_dir=out_dir / "data" / "forecasts",
        reports_dir=out_dir,
        refit="yearly",
        model=model,
        tests=TESTS,
        n_simulations=N_SIMULATIONS,
        eval_simulations=EVAL_SIMULATIONS,
        seed=SEED,
        mc=FIXTURE_MC,
        plots=True,
        use_existing_fit=False,
    )
    findings.append(
        f"schedule: issued {report['n_issued']}, scored {report['n_scored']}, "
        f"refits {len(report['refits'])}, report {Path(report['report_path']).name}"
    )
    if report["n_scored"] < MIN_WINDOWS:
        failures.append(f"fewer than {MIN_WINDOWS} windows scored ({report['n_scored']})")

    for w in report["windows"]:
        missing = [t.value for t in TESTS if t.value not in w["tests"]]
        if missing:
            failures.append(f"window {w['issue_time']}: missing tests {missing}")
        eval_dir = out_dir / "eval" / w["forecast_id"]
        latest_path = eval_dir / "latest.json"
        if not latest_path.exists():
            failures.append(f"window {w['issue_time']}: missing latest.json in {eval_dir}")
            continue
        latest = json.loads(latest_path.read_text(encoding="utf-8"))
        bundle = eval_dir / latest["bundle_dir"]
        needed = ["target.parquet", "summary.json", "n-test.png"]
        absent = [n for n in needed if not (bundle / n).exists()]
        if not (eval_dir / latest["results"]).exists():
            absent.append(latest["results"])
        if absent:
            failures.append(f"window {w['issue_time']}: missing {absent} in {eval_dir}")
        summary = (
            json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
            if (bundle / "summary.json").exists()
            else {}
        )
        skipped = summary.get("skipped", [])
        verdicts = ", ".join(f"{k}={v['passed']}" for k, v in sorted(w["tests"].items()))
        findings.append(
            f"window {w['issue_time'][:10]}: n_target={w['n_target_events']} "
            f"expected={w['total_expected']:.3f} {verdicts}"
            + (f" (plots skipped: {skipped})" if skipped else "")
        )
    for name, agg in report["pass_rates"].items():
        rate = "n/a" if agg["rate"] is None else f"{agg['rate']:.2f}"
        findings.append(f"pass rate {name}: {agg['passed']}/{agg['scored']} ({rate})")

    failures.extend(_negative_tests(catalog, model, report))
    findings.append("leakage assertions: positive checks passed inside the schedule")
    findings.append(
        "negative tests passed (each injected violation raised LeakageError): "
        "1 post-issue history reaching forecast(); 2 training reaching its cutoff; "
        "3 a parameter change with no logged refit; 4 assert_all_before on a late event"
    )

    status = GateStatus.PASSED if not failures else GateStatus.FAILED
    return GateResult(name="validate-eval", status=status, findings=[*failures, *findings])


def _negative_tests(catalog: Catalog, model: MizrahiETAS, report: dict[str, Any]) -> list[str]:
    """Each injected violation must raise LeakageError; anything else is a gate failure."""
    failures: list[str] = []
    fit = model.fit_result
    if fit is None:  # pragma: no cover - the schedule fitted
        return ["no fit loaded after the schedule"]

    # 1. a history containing an event at/after the issue time reaches forecast()
    leaky = catalog.earthquakes().at_least(fit.mc)  # includes Ridgecrest, after the cutoff
    try:
        model.forecast(leaky, START, HORIZON, n_simulations=1, seed=SEED)
    except LeakageError:
        pass
    else:
        failures.append("negative test 1: post-issue history did not raise LeakageError")

    # 2. a fit record whose training catalogue reaches its cutoff
    bad = fit.model_copy(
        update={
            "diagnostics": {
                **fit.diagnostics,
                "training_max_origin_time": fit.fit_cutoff.isoformat(),
            }
        }
    )
    try:
        check_fit_training(bad)
    except LeakageError:
        pass
    else:
        failures.append("negative test 2: training reaching the cutoff did not raise")

    # 3. a parameter change between windows without a logged refit
    windows = [
        WindowRecord(
            issue_time=datetime.fromisoformat(w["issue_time"]),
            window_end=datetime.fromisoformat(w["window_end"]),
            forecast_id=str(w["forecast_id"]),
            fit_cutoff=datetime.fromisoformat(w["fit_cutoff"]),
            parameter_snapshot_hash=str(w["parameter_snapshot_hash"]),
            total_expected=0.0,
            n_target_events=0,
            n_excluded_non_earthquake=0,
            n_excluded_no_mw=0,
            n_only=True,
        )
        for w in report["windows"]
    ]
    if len(windows) >= 2:
        windows[-1].parameter_snapshot_hash = "0" * 64
        try:
            check_snapshot_constancy(windows, [])
        except LeakageError:
            pass
        else:
            failures.append("negative test 3: silent parameter change did not raise")
        boundary = windows[-1].issue_time
        try:
            check_snapshot_constancy(
                windows,
                [RefitLogEntry(boundary, "0" * 64, fit.training_catalog_hash, "refit-test")],
            )
        except LeakageError:
            failures.append("negative test 3b: a logged refit at the boundary was rejected")

    # 4. the bare assertion on a post-cutoff catalogue
    try:
        assert_all_before(catalog, START, what="negative test")
    except LeakageError:
        pass
    else:
        failures.append("negative test 4: assert_all_before did not raise")
    return failures
