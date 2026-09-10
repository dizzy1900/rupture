"""``validate-alarm``: the alarm arm end to end, offline, on the committed California fixture.

The gate has two jobs and keeps them apart.

**It checks machinery.** The scorer registry reports what it has and refuses what it has not; a
uniform reference is refused as the reference of record; the metrics ADR-0055 decision 6 bans
raise when called; a reference fitted after the issue time is caught as leakage; and the
calibration identity holds — an alarm that *is* its reference, scored on targets drawn from that
reference, comes out at an area skill score of one half.

**It reports results, and does not judge them.** The measured numbers below are printed as found.
A trivial alarm scoring badly is not a gate failure, and a trivial alarm scoring *well* against a
weak reference is the finding this gate exists to surface rather than an error to be fixed.

The schedule is the six 30-day windows from 2019-07-01, on the fixture that spans the Ridgecrest
sequence. The first window is issued three days before the M6.4, which is what makes it a fair
test of a rule that can only react.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.domain.alarm import AlarmScore, ReferenceKind
from rupture.domain.hypothesis import HypothesisArm
from rupture.models.alarms import alarm_from_forecast_grid, recent_large_alarm
from rupture.scoring import molchan, power
from rupture.scoring import reference as refmod
from rupture.scoring.alarm import score_alarm_set
from rupture.scoring.errors import (
    ArmNotImplementedError,
    LeakyReferenceError,
    RefusedMetricError,
    UniformReferenceRefusedError,
)
from rupture.scoring.refusals import auc, parimutuel, rmse
from rupture.scoring.registry import implemented_arms, registry_table, scorer_for
from rupture.scoring.schedule import WindowInput, score_alarm_schedule
from rupture.validation._fixture import load_fixture
from rupture.validation.result import GateResult, GateStatus

FIT_CUTOFF = datetime(2019, 7, 1, tzinfo=UTC)
HORIZON = timedelta(days=30)
N_WINDOWS = 6
FIXTURE_MC = 3.0
AUXILIARY_YEARS = 0.5
ETAS_SIMULATIONS = 20
SCORE_SIMULATIONS = 5000
SEED = 19
CALIBRATION_TRIALS = 40
CALIBRATION_TOLERANCE = 0.03
AFTERSHOCK_WINDOW = 1
"""The window issued after the M7.1: the one a reactive rule can actually fire in."""


def run(repo_root: Path) -> GateResult:
    findings: list[str] = []
    failures: list[str] = []
    out_dir = repo_root / "reports" / "validate-alarm"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    _check_registry(findings, failures)
    _check_refusals(findings, failures)
    _check_calibration(findings, failures)

    catalog, region = load_fixture(repo_root)
    model = MizrahiETAS(auxiliary_years=AUXILIARY_YEARS)
    fit = model.fit(catalog, region, FIT_CUTOFF, mc=FIXTURE_MC)
    findings.append(
        f"ETAS fitted at {FIT_CUTOFF.date()} on {fit.n_events} events (converged={fit.converged})"
    )

    windows: list[WindowInput] = []
    contrasts: list[WindowInput] = []
    etas_alarms: list[WindowInput] = []
    for k in range(N_WINDOWS):
        issue = FIT_CUTOFF + k * HORIZON
        history = model.training_slice(catalog, region, issue, FIXTURE_MC)
        grid = model.forecast(
            history, issue, HORIZON, n_simulations=ETAS_SIMULATIONS, seed=SEED + k
        )
        ref = refmod.from_forecast_grid(grid, min_magnitude=region.target_min_magnitude)
        alarm = recent_large_alarm(
            catalog,
            region_id=region.id,
            cell_origins=grid.cell_origins,
            cell_size_deg=grid.cell_size_deg,
            issue_time=issue,
            horizon=HORIZON,
            target_min_magnitude=region.target_min_magnitude,
        )
        windows.append(WindowInput(alarm, ref))
        contrasts.append(WindowInput(alarm, refmod.uniform_like(ref)))
        etas_alarms.append(
            WindowInput(
                alarm_from_forecast_grid(
                    grid,
                    target_min_magnitude=region.target_min_magnitude,
                    declared_threshold=None,
                ),
                ref,
            )
        )
    findings.append(
        f"{N_WINDOWS} windows issued from {FIT_CUTOFF.date()}, "
        f"{windows[0].alarm.n_cells} cells each, "
        f"{sum(float(w.reference.expected_events or 0.0) for w in windows):.1f} events expected "
        "by the reference in total"
    )

    _check_leakage(windows, catalog, findings, failures)

    scores: dict[str, AlarmScore] = {}
    single = windows[AFTERSHOCK_WINDOW]
    scores["aftershock-window-vs-etas"] = score_alarm_set(
        single.alarm, catalog, single.reference, seed=SEED, n_simulations=SCORE_SIMULATIONS
    )
    scores["aftershock-window-vs-uniform"] = score_alarm_set(
        single.alarm,
        catalog,
        contrasts[AFTERSHOCK_WINDOW].reference,
        seed=SEED,
        n_simulations=SCORE_SIMULATIONS,
        as_contrast=True,
    )
    scores["schedule-vs-etas"] = score_alarm_schedule(
        windows, catalog, schedule_id="trivial-schedule", seed=SEED, n_simulations=SCORE_SIMULATIONS
    )
    scores["schedule-vs-uniform"] = score_alarm_schedule(
        contrasts,
        catalog,
        schedule_id="trivial-schedule-uniform-contrast",
        seed=SEED,
        n_simulations=SCORE_SIMULATIONS,
        as_contrast=True,
    )
    scores["etas-as-alarm-vs-etas"] = score_alarm_schedule(
        etas_alarms,
        catalog,
        schedule_id="etas-as-alarm",
        seed=SEED,
        n_simulations=SCORE_SIMULATIONS,
    )

    for name, score in scores.items():
        findings.append(f"{name}: {_summarise(score)}")
        failures.extend(_check_completeness(name, score))
        (out_dir / f"{name}.json").write_text(
            json.dumps(json.loads(score.model_dump_json()), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    _report_reference_effect(scores, findings)
    (out_dir / "summary.md").write_text(_markdown(scores, findings), encoding="utf-8")
    findings.append(f"wrote {len(scores) + 1} artefact(s) to {out_dir.relative_to(repo_root)}/")

    if failures:
        return GateResult(
            name="validate-alarm", status=GateStatus.FAILED, findings=findings + failures
        )
    return GateResult(name="validate-alarm", status=GateStatus.PASSED, findings=findings)


def _check_registry(findings: list[str], failures: list[str]) -> None:
    implemented = implemented_arms()
    if implemented != (HypothesisArm.ALARM_SET,):
        failures.append(
            f"registry: expected only the alarm_set arm to be implemented, got "
            f"{[a.value for a in implemented]}"
        )
    missing = [a for a in HypothesisArm if a not in implemented]
    for arm in missing:
        try:
            scorer_for(arm)
        except ArmNotImplementedError:
            continue
        failures.append(f"registry: arm {arm.value!r} has no scorer but did not refuse")
    findings.append(
        f"registry: {len(implemented)} of {len(HypothesisArm)} arms scored "
        f"({', '.join(a.value for a in implemented)}); the rest refuse by name, not by silence"
    )
    for row in registry_table():
        if not row["reference"]:
            failures.append(f"registry: arm {row['arm']!r} declares no mandatory reference")


def _check_refusals(findings: list[str], failures: list[str]) -> None:
    refused = 0
    # Typed as returning a value on purpose: mypy proves these are NoReturn, and a gate that
    # trusted the proof would stop checking the behaviour the proof is about.
    banned: tuple[tuple[Callable[[], object], str], ...] = (
        (auc, "auc"),
        (rmse, "rmse"),
        (parimutuel, "parimutuel"),
    )
    for fn, label in banned:
        try:
            fn()
        except RefusedMetricError:
            refused += 1
        else:
            failures.append(f"refusals: {label} did not refuse")
    findings.append(f"refusals: {refused} of 3 banned metrics raised with their citation")


def _check_calibration(findings: list[str], failures: list[str]) -> None:
    """An alarm that *is* its reference, on targets drawn from it, scores one half."""
    rng = np.random.default_rng(SEED)
    n_cells, n_targets = 4000, 130
    ref = rng.random(n_cells) ** 4
    ref /= ref.sum()
    scores = []
    for _ in range(CALIBRATION_TRIALS):
        counts = rng.multinomial(n_targets, ref).astype(np.int64)
        groups = molchan.group_by_threshold(ref, ref, counts)
        traj = molchan.trajectory(groups, n_targets)
        scores.append(molchan.area_skill_score(traj.tau, traj.hit_rate))
    mean = float(np.mean(scores))
    findings.append(
        f"calibration: alarm == reference over {CALIBRATION_TRIALS} simulated catalogues gives "
        f"mean area skill {mean:.4f} (sd {float(np.std(scores)):.4f}); the identity is 0.5"
    )
    if abs(mean - 0.5) > CALIBRATION_TOLERANCE:
        failures.append(
            f"calibration: mean area skill {mean:.4f} is more than {CALIBRATION_TOLERANCE} from "
            "0.5, so the scorer is biased and no result from it can be read"
        )
    mdg = power.minimum_detectable_gain(n_targets, 0.1)
    if mdg is None or not 1.0 < mdg < 3.0:
        failures.append(f"power: minimum detectable gain at N=130, tau=0.1 is {mdg}, expected ~1.5")
    else:
        findings.append(
            f"power: at N=130 targets and a 10 % alarm fraction the smallest detectable gain is "
            f"G = {mdg:.3f} at 80 % power; {power.events_needed_for_gain(0.1, 2.0)} targets would "
            "be needed to see G = 2"
        )


def _check_leakage(
    windows: list[WindowInput], catalog: Any, findings: list[str], failures: list[str]
) -> None:
    """A reference that saw the window it judges must be refused, not scored."""
    first = windows[0]
    later = windows[-1]
    peeking = refmod.ReferenceMeasure(
        id="ref-peeking",
        kind=ReferenceKind.CLUSTERING_AWARE,
        model_id="etas-mizrahi",
        cell_size_deg=later.reference.cell_size_deg,
        cell_origins=first.alarm.cell_origins,
        probabilities=later.reference.probabilities,
        expected_events=later.reference.expected_events,
        fit_cutoff_iso=later.alarm.issue_time.isoformat(),
    )
    try:
        score_alarm_set(first.alarm, catalog, peeking, n_simulations=10, seed=SEED)
    except LeakyReferenceError:
        findings.append(
            "leakage: a reference fitted after the alarm's issue time was refused, not scored"
        )
    else:
        failures.append("leakage: a reference fitted after the issue time was accepted")

    try:
        score_alarm_set(
            first.alarm,
            catalog,
            refmod.uniform_like(first.reference),
            n_simulations=10,
            seed=SEED,
        )
    except UniformReferenceRefusedError:
        findings.append("reference: a spatially uniform reference of record was refused")
    else:
        failures.append("reference: a spatially uniform reference was accepted as the record")


def _check_completeness(name: str, score: AlarmScore) -> list[str]:
    """No score leaves this gate without the things that make it readable."""
    problems: list[str] = []
    if not score.reference_id or not score.reference_model_id:
        problems.append(f"{name}: a score was produced without naming its reference")
    if score.n_target_events > 0 and score.area_skill_score is None:
        problems.append(f"{name}: targets exist but no area skill score was computed")
    if score.declared_tau is not None and score.n_target_events > 0:
        if score.power is None:
            problems.append(f"{name}: a p-value was published without the power behind it")
        if score.significant is False and score.minimum_detectable_gain is None:
            has_bound = any("upper bound" in n for n in score.notes)
            if not has_bound:
                problems.append(f"{name}: a null result was published without an upper bound")
    return problems


def _summarise(score: AlarmScore) -> str:
    bits = [
        f"N={score.n_target_events}",
        f"ref={score.reference_kind.value}",
        f"ASS={score.area_skill_score:.4f}" if score.area_skill_score is not None else "ASS=n/a",
    ]
    if score.area_skill_p_value is not None:
        bits.append(f"p={score.area_skill_p_value:.4g}")
    if score.declared_probability_gain is not None:
        bits.append(f"G={score.declared_probability_gain:.3f}")
        bits.append(f"tau={score.declared_tau:.4f}")
        if score.declared_p_value is not None:
            bits.append(f"p(G)={score.declared_p_value:.4g}")
    if score.minimum_detectable_gain is not None:
        bits.append(f"MDG={score.minimum_detectable_gain:.3f}")
    elif score.declared_tau is not None:
        bits.append("MDG=none detectable")
    return " ".join(bits)


def _report_reference_effect(scores: dict[str, AlarmScore], findings: list[str]) -> None:
    """The one number this gate exists to produce: what the reference choice was worth."""
    for label, honest_key, contrast_key in (
        ("aftershock window", "aftershock-window-vs-etas", "aftershock-window-vs-uniform"),
        ("pooled schedule", "schedule-vs-etas", "schedule-vs-uniform"),
    ):
        honest, contrast = scores[honest_key], scores[contrast_key]
        if honest.declared_probability_gain is None or contrast.declared_probability_gain is None:
            continue
        findings.append(
            f"reference effect, {label}: the same trivial alarm scores G = "
            f"{contrast.declared_probability_gain:.3f} (p = {contrast.declared_p_value:.4g}) "
            f"against a uniform reference and G = {honest.declared_probability_gain:.3f} "
            f"(p = {honest.declared_p_value:.4g}) against the fitted ETAS one. Area skill "
            f"{contrast.area_skill_score:.4f} against {honest.area_skill_score:.4f}"
        )


def _markdown(scores: dict[str, AlarmScore], findings: list[str]) -> str:
    lines = [
        "# validate-alarm",
        "",
        "Machinery checks and measured results for the `AlarmSet` arm (ADR-0055), on the",
        "committed California fixture. Results are reported as found; a trivial alarm scoring",
        "well against a weak reference is the finding, not an error.",
        "",
        "| score | N | reference | area skill | p | G | tau | p(G) | power(G=2) | MDG |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in scores.items():
        lines.append(
            f"| {name} | {s.n_target_events} | {s.reference_kind.value} | "
            f"{_fmt(s.area_skill_score)} | {_fmt(s.area_skill_p_value)} | "
            f"{_fmt(s.declared_probability_gain)} | {_fmt(s.declared_tau)} | "
            f"{_fmt(s.declared_p_value)} | {_fmt(s.power)} | {_fmt(s.minimum_detectable_gain)} |"
        )
    lines += ["", "## What the gate found", ""]
    lines += [f"- {f}" for f in findings]
    lines += ["", "## Notes carried by each score", ""]
    for name, s in scores.items():
        lines.append(f"### {name}")
        lines += [f"- {n}" for n in s.notes]
        lines.append("")
    return "\n".join(lines) + "\n"


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.4g}"
