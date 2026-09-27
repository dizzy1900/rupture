"""``validate-asof``: how much of a result rests on records of unproven vintage.

RELEASE_STATUS records two claims as hypotheses that underwrite the whole programme, and this
gate is about the first: *nobody has measured (final-data skill - as-of skill) for a set of
published models, and if that difference sits inside bootstrap noise everywhere then the as-of
layer should be demoted from an evaluation requirement to a data-engineering convenience.*

This gate does not settle that. It measures the part that **can** be measured from a single
vintage, which is the *exposure*: how much of a fit and how much of a scored window rests on
records that are not provably the records that existed at the time. On the committed California
fixture the answer is not marginal, and it is invisible to every existing leakage assertion
because those compare ``origin_time`` and this is about the other clock.

What the numbers below are, exactly:

* **Exposure** is a measurement. ComCat's ``updated`` is the last time a record changed, so
  ``updated >= t`` proves the record in hand is not the record that existed at *t*.
* **The two ablations are bounds, not the effect.** Dropping the events of unproven vintage is
  not the same as restoring their old values -- the events were in the catalogue at the time,
  with values nobody kept -- so a fit on what remains is a *different, smaller* fit. If the score
  barely moves, revision cannot reach the result through that path; if it moves, revision
  *might*. One direction is conclusive and the other is not, and the gate says which is which.
* **The skill difference is not computed here and cannot be.** It needs archived vintages.
  ADR-0064 names that as the next step rather than approximating it.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rupture.adapters.evaluation.pycsep import PyCSEPEvaluator
from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.adapters.forecasting.leakage import LeakageError, assert_available_before
from rupture.domain import Catalog, TestName, VintagePolicy
from rupture.validation._fixture import load_fixture
from rupture.validation.result import GateResult, GateStatus

FIT_CUTOFF = datetime(2019, 7, 1, tzinfo=UTC)
HORIZON = timedelta(days=30)
N_WINDOWS = 6
FIXTURE_MC = 3.0
AUXILIARY_YEARS = 0.5
ETAS_SIMULATIONS = 20
EVAL_SIMULATIONS = 500
SEED = 23
TESTS = (TestName.N, TestName.M, TestName.S, TestName.L, TestName.CL)
MIN_VINTAGE_COVERAGE = 0.99
"""The ComCat fixture carries `updated` on every feature; less than this means the adapter
stopped reading it, which would make every number in this gate silently meaningless."""


def run(repo_root: Path) -> GateResult:
    findings: list[str] = []
    failures: list[str] = []
    out_dir = repo_root / "reports" / "validate-asof"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    catalog, region = load_fixture(repo_root)
    whole = catalog.vintage_summary()
    findings.append(f"fixture vintage: {whole.render()}")
    if whole.coverage < MIN_VINTAGE_COVERAGE:
        failures.append(
            f"vintage coverage {whole.coverage:.1%} is below {MIN_VINTAGE_COVERAGE:.0%}: the "
            "adapter is not reading ComCat's `updated`, so every figure in this gate is void"
        )

    payload: dict[str, Any] = {"fixture": json.loads(whole.model_dump_json())}

    # -- exposure on the training side ----------------------------------------------------------
    training = catalog.earthquakes().before(FIT_CUTOFF).at_least(FIXTURE_MC)
    train_vintage = training.vintage_summary(FIT_CUTOFF)
    findings.append(f"training slice at {FIT_CUTOFF.date()}: {train_vintage.render()}")
    payload["training"] = json.loads(train_vintage.model_dump_json())

    provable = training.as_of(FIT_CUTOFF, VintagePolicy.EXCLUDE_UNKNOWN)
    findings.append(
        f"of {len(training)} event(s) a fit at {FIT_CUTOFF.date()} would train on, "
        f"{len(provable)} are provably available by then and {len(training) - len(provable)} "
        f"are not ({train_vintage.exposed_fraction:.0%} exposed)"
    )

    # -- exposure on the target side ------------------------------------------------------------
    per_window: list[dict[str, Any]] = []
    total_targets = 0
    total_exposed = 0
    for k in range(N_WINDOWS):
        start = FIT_CUTOFF + k * HORIZON
        end = start + HORIZON
        targets = catalog.earthquakes().between(start, end).at_least(region.target_min_magnitude)
        exposed = len(targets.revised_after(end))
        total_targets += len(targets)
        total_exposed += exposed
        per_window.append(
            {
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "n_targets": len(targets),
                "n_revised_after_window_end": exposed,
            }
        )
    payload["windows"] = per_window
    share = 0.0 if total_targets == 0 else total_exposed / total_targets
    findings.append(
        f"target exposure over {N_WINDOWS} windows: {total_exposed} of {total_targets} scored "
        f"target(s) ({share:.0%}) carry a record last modified after the window they were "
        "scored in"
    )

    # -- machinery: the assertion can see what the origin-time one cannot ------------------------
    _check_assertion(training, findings, failures)

    # -- bound 1: does the fit depend on the records of unproven vintage? ------------------------
    model_all = MizrahiETAS(auxiliary_years=AUXILIARY_YEARS)
    fit_all = model_all.fit(catalog, region, FIT_CUTOFF, mc=FIXTURE_MC)
    model_provable = MizrahiETAS(auxiliary_years=AUXILIARY_YEARS)
    provable_catalog = _as_of_catalog(catalog, FIT_CUTOFF)
    try:
        fit_provable = model_provable.fit(provable_catalog, region, FIT_CUTOFF, mc=FIXTURE_MC)
    except ValueError as exc:
        findings.append(
            f"the provable-vintage fit could not run ({exc}); the exposure figures above stand "
            "and this bound is not available"
        )
        fit_provable = None

    if fit_provable is not None:
        moved = {
            k: (fit_all.parameters[k], fit_provable.parameters[k])
            for k in sorted(fit_all.parameters)
            if k in fit_provable.parameters
        }
        worst = max(
            moved.items(),
            key=lambda kv: abs(kv[1][1] - kv[1][0]) / max(abs(kv[1][0]), 1e-9),
            default=("", (0.0, 0.0)),
        )
        findings.append(
            f"fit sensitivity: {fit_all.n_events} events -> {fit_provable.n_events} when "
            f"restricted to provable vintage; largest relative parameter move {worst[0]} "
            f"{worst[1][0]:.4g} -> {worst[1][1]:.4g}"
        )
        payload["fit"] = {
            "all": {"n_events": fit_all.n_events, "parameters": fit_all.parameters},
            "provable_vintage": {
                "n_events": fit_provable.n_events,
                "parameters": fit_provable.parameters,
            },
        }
        _score_both(
            repo_root,
            catalog,
            region,
            model_all,
            model_provable,
            findings,
            failures,
            payload,
        )

    findings.append(
        "NOT established by this gate: the skill difference between a final-data and an as-of "
        "evaluation. A single vintage cannot reconstruct the values a record held before it was "
        "last changed, so the ablations above bound the effect of *dropping* those records, not "
        "of *restoring* them. ADR-0064 names archived vintages as the next step"
    )

    (out_dir / "vintage.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    findings.append(f"wrote {(out_dir / 'vintage.json').relative_to(repo_root)}")

    if failures:
        return GateResult(
            name="validate-asof", status=GateStatus.FAILED, findings=findings + failures
        )
    return GateResult(name="validate-asof", status=GateStatus.PASSED, findings=findings)


def _as_of_catalog(catalog: Catalog, cutoff: datetime) -> Catalog:
    """The whole catalogue with unproven-vintage records removed before the cutoff only.

    Events after the cutoff are left alone: they are the targets, and removing them here would
    change what the fit is scored against as well as what it saw, which would confound the two
    effects this gate is trying to keep apart.
    """
    keep = tuple(
        e
        for e in catalog.events
        if e.origin_time >= cutoff or (e.available_time is not None and e.available_time <= cutoff)
    )
    return catalog.model_copy(update={"events": keep, "id": f"{catalog.id}/asof-{cutoff.date()}"})


def _check_assertion(training: Catalog, findings: list[str], failures: list[str]) -> None:
    """The origin-time assertion passes on this slice; the vintage one must not."""
    try:
        assert_available_before(
            training,
            FIT_CUTOFF,
            what="training slice",
            policy=VintagePolicy.EXCLUDE_UNKNOWN,
        )
    except LeakageError as exc:
        findings.append(f"vintage assertion refused the training slice, as it should: {exc}")
    else:
        failures.append(
            "the vintage assertion accepted a training slice with 69 records last modified "
            "after the cutoff, so it is not checking the second clock at all"
        )
    clean = training.as_of(FIT_CUTOFF, VintagePolicy.EXCLUDE_UNKNOWN)
    try:
        assert_available_before(
            clean, FIT_CUTOFF, what="provable slice", policy=VintagePolicy.EXCLUDE_UNKNOWN
        )
    except LeakageError as exc:
        failures.append(f"the vintage assertion refused a slice it filtered itself: {exc}")
    else:
        findings.append(
            f"the same assertion accepts the {len(clean)}-event provable slice, so it is "
            "filtering rather than always failing"
        )


def _score_both(  # noqa: PLR0917 - one call site, all of it needed
    repo_root: Path,
    catalog: Catalog,
    region: Any,
    model_all: MizrahiETAS,
    model_provable: MizrahiETAS,
    findings: list[str],
    failures: list[str],
    payload: dict[str, Any],
) -> None:
    """Issue and score one window from each fit, against the identical target slice."""
    evaluator = PyCSEPEvaluator()
    start, end = FIT_CUTOFF, FIT_CUTOFF + HORIZON
    targets = catalog.earthquakes().between(start, end).at_least(region.target_min_magnitude)
    history = model_all.training_slice(catalog, region, FIT_CUTOFF, FIXTURE_MC)
    results: dict[str, dict[str, float | None]] = {}
    passed: dict[str, dict[str, bool | None]] = {}
    for label, model in (("all", model_all), ("provable_vintage", model_provable)):
        grid = model.forecast(
            history, FIT_CUTOFF, HORIZON, n_simulations=ETAS_SIMULATIONS, seed=SEED
        )
        scored = evaluator.evaluate(grid, targets, TESTS, n_simulations=EVAL_SIMULATIONS, seed=SEED)
        results[label] = {r.test_name.value: _statistic_quantile(r) for r in scored}
        passed[label] = {r.test_name.value: r.passed for r in scored}
        findings.append(
            f"window {start.date()} scored from the '{label}' fit "
            f"(total expected {grid.total_expected():.3f}, {len(targets)} target(s)): "
            + ", ".join(f"{r.test_name.value}={_fmt_quantile(r)} passed={r.passed}" for r in scored)
        )
    payload["scores"] = {"quantiles": results, "passed": passed}
    moved = [
        name
        for name in results["all"]
        if results["all"][name] is not None
        and results["provable_vintage"].get(name) is not None
        and abs((results["all"][name] or 0) - (results["provable_vintage"][name] or 0)) > 0.05
    ]
    flipped = [
        name
        for name in passed["all"]
        if passed["all"][name] is not None
        and passed["all"][name] != passed["provable_vintage"].get(name)
    ]
    findings.append(
        "score sensitivity to training vintage: "
        + (
            f"{len(moved)} of {len(results['all'])} test quantile(s) moved by more than 0.05 "
            f"({', '.join(moved)})"
            if moved
            else "no test quantile moved by more than 0.05"
        )
        + "; "
        + (
            f"{len(flipped)} test verdict(s) flipped ({', '.join(flipped)})"
            if flipped
            else "no test verdict flipped, so on this window revision cannot reach the result "
            "through the training path -- which is one window, and evidence for demoting the "
            "as-of layer only if it holds across many"
        )
    )


def _statistic_quantile(result: Any) -> float | None:
    """The N-test is two-sided and reports no single quantile; everything else reports one.

    Reading `quantile` for all five tests silently prints `n/a` for the N-test -- the one a
    reader looks at first on a window holding 123 targets against about one expected event.
    """
    if result.quantile is not None:
        return float(result.quantile)
    if result.quantile_low is not None:
        return float(result.quantile_low)
    return None


def _fmt_quantile(result: Any) -> str:
    if result.quantile is not None:
        return f"{result.quantile:.3f}"
    if result.quantile_low is not None and result.quantile_high is not None:
        return f"[{result.quantile_low:.3f}, {result.quantile_high:.3f}]"
    return "n/a"
