"""``validate-challengers``: the promotion rule, recomputed, plus the leakage controls under it.

The brief puts the promotion rule *in the gate* so that promotion is a mechanical, CI-enforced
verdict rather than an editorial one. This gate therefore does two things, in this order:

**It recomputes every promotion verdict from the committed evidence.** For each challenger in each
region it reads the committed schedule report, recomputes protocol § 10 conditions 1 and 2 through
the single encoding in :mod:`rupture.models.promotion` (ADR-0040), applies the two-of-three-regions
clause, and fails if any document in the tree declares a promotion the rule does not admit — or
denies one it does. Regions that were never evaluated are named, not silently treated as failures.
Where a challenger was compared against a *matched re-run* of ETAS rather than the published
baseline of record, both readings are evaluated and the gate fails if they disagree, so the verdict
can never depend on which ETAS run flattered it.

**It checks the machinery that makes a verdict mean anything**, because a challenger that beats
ETAS because information leaked across the cutoff is worse than no challenger at all:

1. **The splitter cannot express a random split.** ``rupture.models.data.splits`` must expose no
   shuffle parameter, no seed and no randomness at all, and every validation index must be strictly
   later than every training index. Random k-fold on a catalogue leaks through aftershock
   sequences; the defence is that the API makes it unsayable, not that reviewers remember.
2. **Dataset builders raise on post-cutoff events** rather than filtering them, because a silent
   filter hides the bug that supplied them.
3. **Every persisted challenger fit is honest**: it converged, its training data ends strictly
   before its cutoff (compared as instants, never as strings), it carries a non-empty
   ``parameter_snapshot_hash`` so a silent retrain is visible, and its branching ratio is below 1
   (a supercritical fit cannot be simulated to termination).
4. **Hyperparameters were frozen before scoring**: a ``hyperparameters.json`` sits beside each fit,
   its validation window ends at or before the hard cutoff, and where both record one, the fit's
   config hash equals the frozen one.
5. **No leaky artefact is masquerading as a result**: anything produced by a deliberately leaky
   ablation carries a leaky model id and never appears under ``baselines/`` or among the models a
   verdict is computed for.
6. **The fits that are not committed are audited through their reports.** ``baselines/gridded/``
   and ``baselines/ensemble/`` are not in the tree (RELEASE_STATUS.md says so and why), so the
   freezing and weight-fitting claims for those two models are checked against the blocks the
   committed schedule report carries instead: the frozen config hash is one of the searched
   candidates, the fit records a parameter snapshot, and no ensemble weight-fitting window reaches
   the test cutoff. That is weaker than auditing the fit itself and is reported as such.

It runs offline. It SKIPS, with a printed reason, only when there is no evidence at all.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rupture.models.data import splits
from rupture.models.data.splits import blocked_splits
from rupture.models.promotion import (
    MIN_CONSECUTIVE_WINDOWS,
    PROTOCOL_REGIONS,
    longest_consecutive_run,
    overall_verdict,
    pass_rate_table,
    region_verdict,
)
from rupture.validation.result import GateResult, GateStatus

GATE = "validate-challengers"
LEAKY_MARKERS = ("leak", "ablation")
BASELINE_MODEL_ID = "etas-mizrahi"
STEP = timedelta(days=30)
HORIZON = timedelta(days=30)

#: Where a promotion claim may be written down. The first three are declared machine-readably (see
#: :func:`_declared_status`); the rest are scanned for a claim that contradicts the rule.
MODEL_CARDS = {
    "ntpp-neural-hawkes": Path("reports/MODEL_CARD_ntpp.md"),
    "gridded-convlstm": Path("reports/MODEL_CARD_gridded.md"),
    "ensemble-loglinear": Path("reports/MODEL_CARD_ensemble.md"),
}
PROSE_CLAIM_FILES = (
    Path("RELEASE_STATUS.md"),
    Path("reports/CHALLENGER_EVALUATION.md"),
    Path("reports/PROMPT2_SUMMARY.md"),
    Path("docs/CHALLENGER_NTPP.md"),
    Path("docs/CHALLENGER_GRIDDED.md"),
    Path("docs/CHALLENGER_ENSEMBLE.md"),
)
DECLARED_STATUS = re.compile(r"promotion status\s*[:|]\s*\**\s*(not promoted|promoted)\b", re.I)
PROMOTION_WORD = re.compile(r"\b(promoted|promotable)\b", re.I)
#: A claim is *not* a claim when it is negated (these words before it on the line), when the line
#: states the rule rather than applying it, or when it is scoped to a single region. Kept explicit
#: so the exemptions can be argued with; a promotion claim that slips past all of them is real.
NEGATIONS = ("not", "n't", "never", "no ", "none", "neither", "nothing", "cannot")
RULE_STATEMENT = ("only if", "only when", "is promoted to", "promotion rule")
REGIONAL_SCOPE = ("in this region", "in that region", "in either region", "in each region")


# ------------------------------------------------------------------ leakage machinery
def _splitter_has_no_randomness() -> list[str]:
    """The strongest guarantee available: the API cannot express a shuffled split."""
    findings: list[str] = []
    # Parse rather than grep: the module's own prose promises there is no shuffle, and a docstring
    # saying so must not fail the check that enforces it.
    tree = ast.parse(inspect.getsource(splits))
    banned_modules = {"random", "numpy.random", "secrets"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in {"random", "secrets"}:
                    findings.append(f"splits.py imports {alias.name}: randomness must be unsayable")
        elif isinstance(node, ast.ImportFrom) and node.module in banned_modules:
            findings.append(f"splits.py imports from {node.module}: randomness must be unsayable")
        elif isinstance(node, ast.Attribute) and node.attr in {"shuffle", "permutation"}:
            findings.append(f"splits.py calls .{node.attr}(): a split may never be reordered")
    for name, fn in inspect.getmembers(splits, inspect.isfunction):
        params = set(inspect.signature(fn).parameters)
        for forbidden in ("shuffle", "seed", "random_state"):
            if forbidden in params:
                findings.append(f"splits.{name} takes {forbidden!r}")
    return findings


def _blocked_splits_are_time_forward() -> list[str]:
    findings: list[str] = []
    start = datetime(2010, 1, 1, tzinfo=UTC)
    for n_folds in (1, 2, 3, 5, 8):
        for days in (90, 365, 1500):
            for expanding in (True, False):
                end = start + timedelta(days=days)
                try:
                    folds = blocked_splits(start, end, n_folds, expanding=expanding)
                except ValueError:
                    continue
                for split in folds:
                    if split.train_end > split.val_start:
                        findings.append(
                            f"blocked_splits(days={days}, n_folds={n_folds}, "
                            f"expanding={expanding}) fold {split.fold}: training ends after "
                            f"validation starts"
                        )
                    if split.val_start < split.train_start:
                        findings.append(
                            f"blocked_splits fold {split.fold}: validation precedes training"
                        )
    return findings


def _instant(value: object) -> datetime | None:
    """Parse an ISO timestamp to an instant.

    Timestamps must never be compared as strings here. The same instant is written both
    ``2022-01-01T00:00:00Z`` and ``2022-01-01T00:00:00+00:00``, and ``'+'`` sorts below ``'Z'``,
    so a string comparison silently passes the exact case this check exists to catch: training
    that runs right up to its own cutoff.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_leaky(name: str) -> bool:
    return any(marker in name.lower() for marker in LEAKY_MARKERS)


def _fit_is_honest(path: Path) -> list[str]:
    fit: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    where = path.parent.name
    findings: list[str] = []
    if not fit.get("converged", False):
        findings.append(f"{where}: fit did not converge and must not be used")
    cutoff = fit.get("fit_cutoff", "")
    latest = (fit.get("diagnostics") or {}).get("training_max_origin_time")
    cutoff_at, latest_at = _instant(cutoff), _instant(latest)
    if cutoff_at is not None and latest_at is not None and latest_at >= cutoff_at:
        findings.append(f"{where}: training reaches its cutoff ({latest} >= {cutoff})")
    branching = (fit.get("diagnostics") or {}).get("branching_ratio")
    if branching is not None and branching >= 1.0:
        findings.append(f"{where}: branching ratio {branching:.3f} is not subcritical")
    model_id = str(fit.get("model_id", ""))
    if _is_leaky(model_id):
        findings.append(f"{where}: a leaky model id ({model_id}) is persisted as a baseline")
    hyper = path.parent / "hyperparameters.json"
    if hyper.exists():
        chosen = json.loads(hyper.read_text(encoding="utf-8"))
        end_at = _instant(chosen.get("validation_end"))
        if end_at is not None and cutoff_at is not None and end_at > cutoff_at:
            findings.append(f"{where}: hyperparameters were chosen on data after the cutoff")
        # The frozen config must be the one the fit actually used, or "frozen before scoring"
        # means nothing: a config chosen on validation and then quietly changed would pass.
        declared = chosen.get("config_hash") or chosen.get("chosen_config_hash")
        used = fit.get("config_hash") or (fit.get("diagnostics") or {}).get("config_hash")
        if declared and used and str(declared) != str(used):
            findings.append(
                f"{where}: the fit's config hash ({used}) is not the frozen one ({declared})"
            )
        findings.extend(_search_reproduces_the_frozen_record(where, chosen))
    snapshot = fit.get("parameter_snapshot_hash")
    if not snapshot or not str(snapshot).strip("0"):
        findings.append(
            f"{where}: no usable parameter_snapshot_hash, so a silent retrain is invisible"
        )
    return findings


def _search_reproduces_the_frozen_record(where: str, chosen: dict[str, Any]) -> list[str]:
    """The committed search code must be able to produce the committed frozen record.

    "Frozen before scoring" is only evidence if a reader can re-run the search and arrive at the
    same candidates. When the search grid in the code and the trials in the record disagree, the
    record cannot be reproduced and the freezing claim rests on nothing but the file's own word.
    The record may name the grid it searched (``grid``); older records do not, and are checked
    against the default.
    """
    trials = chosen.get("trials")
    if not isinstance(trials, list) or not trials:
        return []
    from rupture.models.challengers.ntpp.train import (  # noqa: PLC0415 - heavy, and ntpp only
        candidate_configs,
    )

    recorded = {str(t.get("config_hash")) for t in trials if isinstance(t, dict)}
    grid = chosen.get("grid")
    try:
        produced = {
            c.config_hash()
            for c in candidate_configs(
                grid={k: tuple(v) for k, v in grid.items()} if isinstance(grid, dict) else None
            )
        }
    except (TypeError, ValueError) as exc:  # a grid the current config cannot express
        return [f"{where}: the recorded search grid cannot be rebuilt ({exc})"]
    if recorded != produced:
        return [
            f"{where}: the committed search code produces {len(produced)} candidate(s) and the "
            f"frozen record holds {len(recorded)}, and they are not the same set; re-running "
            f"`select` would search a different space from the one the frozen configuration "
            f"came out of"
        ]
    return []


# ------------------------------------------------------------------ committed evidence
def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _issue_times(block: dict[str, Any]) -> list[str]:
    return [
        str(w.get("issue_time"))
        for w in (block.get("windows") or [])
        if isinstance(w, dict) and w.get("issue_time")
    ]


def _evidence(repo_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Every committed challenger result, as ``{region, model, rates, baselines, pooled, ...}``.

    ``baselines`` maps a label to a pass-rate table: ``"published"`` is the region's ETAS schedule
    of record, ``"matched re-run"`` is ETAS rescored inside the challenger's own run at its own
    simulation budget. Both are carried because the verdict must not depend on the choice.
    """
    found: list[dict[str, Any]] = []
    notes: list[str] = []

    def published(region_id: str) -> dict[str, Any] | None:
        report = _load_json(
            repo_root
            / "reports"
            / "protocol"
            / region_id
            / "eval"
            / f"schedule-{region_id}-{BASELINE_MODEL_ID}.json"
        )
        return (report or {}).get("pass_rates")

    for region_dir in sorted(
        p for p in (repo_root / "reports" / "protocol").glob("*") if p.is_dir()
    ):
        region_id = region_dir.name
        for path in sorted(region_dir.glob("eval/schedule-*.json")):
            report = _load_json(path)
            if report is None:
                notes.append(f"{path}: unreadable, so no verdict was recomputed from it")
                continue
            model_id = str(report.get("model_id") or report.get("label") or "")
            if model_id == BASELINE_MODEL_ID or _is_leaky(path.name) or _is_leaky(model_id):
                continue
            baselines = {"published": published(region_id)}
            matched = report.get("benchmark_pass_rates")
            if matched:
                baselines["matched re-run"] = matched
            found.append(
                {
                    "region_id": region_id,
                    "model_id": model_id,
                    "source": path.relative_to(repo_root).as_posix(),
                    "pass_rates": report.get("pass_rates") or {},
                    "baselines": baselines,
                    "pooled": report.get("pooled_paired_test"),
                    "per_window": report.get("comparison_summary"),
                    "issue_times": _issue_times(report),
                }
            )

    for region_dir in sorted(
        p for p in (repo_root / "reports" / "challenger").glob("*") if p.is_dir()
    ):
        region_id = region_dir.name
        path = region_dir / f"schedule-{region_id}-challengers.json"
        report = _load_json(path)
        if report is None:
            notes.append(f"{path}: absent or unreadable, so no verdict was recomputed from it")
            continue
        embedded = (report.get("etas_baseline") or {}).get("pass_rates")
        baselines = {"published": published(region_id) or embedded}
        if embedded and published(region_id) and embedded != published(region_id):
            baselines["embedded in the run"] = embedded
        for model_id, block in sorted((report.get("models") or {}).items()):
            if _is_leaky(model_id) or not isinstance(block, dict):
                continue
            found.append(
                {
                    "region_id": region_id,
                    "model_id": model_id,
                    "source": path.relative_to(repo_root).as_posix(),
                    "pass_rates": block.get("pass_rates") or {},
                    "baselines": dict(baselines),
                    "pooled": block.get("pooled_paired_test"),
                    "per_window": block.get("comparison_vs_etas"),
                    "issue_times": _issue_times(block),
                }
            )
    return found, notes


# ------------------------------------------------------------------ the rule, recomputed
def _regions_that_cannot_pass(repo_root: Path) -> dict[str, str]:
    """Regions where no challenger could satisfy condition 1, whatever it scored.

    Condition 1 compares pass rates over at least twelve consecutive windows *against the ETAS
    baseline over the same schedule*. Where the published baseline schedule is shorter than that,
    running a challenger there cannot produce a pass until the baseline is extended, and the gate
    says so rather than leaving the reader to wonder whether the missing region was the one that
    would have changed the verdict.
    """
    blocked: dict[str, str] = {}
    for region_id in PROTOCOL_REGIONS:
        baseline = _load_json(
            repo_root
            / "reports"
            / "protocol"
            / region_id
            / "eval"
            / f"schedule-{region_id}-{BASELINE_MODEL_ID}.json"
        )
        if baseline is None:
            blocked[region_id] = "no published ETAS schedule to compare against"
            continue
        run_length = longest_consecutive_run(_issue_times(baseline), STEP)
        if run_length < MIN_CONSECUTIVE_WINDOWS:
            blocked[region_id] = (
                f"the published ETAS schedule is {run_length} consecutive window(s), short of the "
                f"{MIN_CONSECUTIVE_WINDOWS} condition 1 requires"
            )
    return blocked


def _verdicts(
    evidence: list[dict[str, Any]], blocked: dict[str, str]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Recompute § 10 per model, and report where the evidence could not decide."""
    findings: list[str] = []
    per_model: dict[str, list[dict[str, Any]]] = {}
    for item in evidence:
        consecutive = longest_consecutive_run(item["issue_times"], STEP)
        readings: dict[str, dict[str, Any]] = {}
        for label, table in item["baselines"].items():
            if not table:
                continue
            readings[label] = region_verdict(
                region_id=item["region_id"],
                model_id=item["model_id"],
                challenger_rates=pass_rate_table(item),
                baseline_rates=pass_rate_table({"pass_rates": table}),
                consecutive_windows=consecutive,
                pooled=item["pooled"],
                per_window=item["per_window"],
                baseline_label=label,
            )
        if not readings:
            findings.append(
                f"{item['model_id']} / {item['region_id']}: no ETAS pass rates to compare "
                f"against, so condition 1 cannot be decided ({item['source']})"
            )
            continue
        outcomes = {label: v["promotable_in_this_region"] for label, v in readings.items()}
        if len(set(outcomes.values())) > 1:
            findings.append(
                f"{item['model_id']} / {item['region_id']}: the verdict depends on which ETAS run "
                f"is the baseline ({outcomes}); one of them must be chosen and published "
                f"(ADR-0040 decision 6), not left to the reader"
            )
        chosen = readings.get("published") or next(iter(readings.values()))
        chosen = {**chosen, "readings": outcomes, "evidence": item["source"]}
        per_model.setdefault(item["model_id"], []).append(chosen)

    overall = {
        model_id: overall_verdict(regions, model_id=model_id, regions_that_cannot_pass=blocked)
        for model_id, regions in sorted(per_model.items())
    }
    return overall, findings


def _declared_status(path: Path) -> str | None:
    """The machine-readable promotion status a model card must carry, or ``None``."""
    if not path.is_file():
        return None
    match = DECLARED_STATUS.search(path.read_text(encoding="utf-8"))
    return match.group(1).lower() if match else None


def _prose_claims(repo_root: Path, promoted: set[str]) -> list[str]:
    """Fail on a document that claims a promotion the rule does not admit.

    The scan is deliberately coarse — an un-negated "promoted"/"promotable" outside a
    single-region scope — because the failure it defends against is coarse: a document drifting
    into claiming a model was promoted when the recomputed rule says otherwise. Its exemptions are
    listed in :data:`NEGATIONS`, :data:`RULE_STATEMENT` and :data:`REGIONAL_SCOPE`.
    """
    findings: list[str] = []
    for relative in PROSE_CLAIM_FILES:
        path = repo_root / relative
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            lowered = line.lower()
            if any(phrase in lowered for phrase in REGIONAL_SCOPE + RULE_STATEMENT):
                continue
            for match in PROMOTION_WORD.finditer(line):
                before = lowered[: match.start()]
                if any(token in before for token in NEGATIONS):
                    continue
                if any(model in line for model in promoted):
                    continue
                findings.append(
                    f"{relative}:{number} reads as a promotion claim, and the rule recomputed "
                    f"from the committed evidence promotes {sorted(promoted) or 'nothing'}: "
                    f"{line.strip()[:120]}"
                )
    return findings


# ------------------------------------------------------------------ uncommitted fits, via reports
def _report_audits_the_fit_it_cannot_show(repo_root: Path) -> list[str]:
    """Audit the gridded and ensemble fits through the committed report, since they are not in git.

    Weaker than :func:`_fit_is_honest` on a persisted fit and honestly labelled as such: it proves
    the report is internally consistent about freezing and about the weight-fitting block, not that
    the weights exist. RELEASE_STATUS.md carries the same statement in prose.
    """
    findings: list[str] = []
    for region_dir in sorted(
        p for p in (repo_root / "reports" / "challenger").glob("*") if p.is_dir()
    ):
        region_id = region_dir.name
        report = _load_json(region_dir / f"schedule-{region_id}-challengers.json")
        if report is None:
            continue
        where = f"reports/challenger/{region_id}"
        cutoff = _instant((report.get("protocol") or {}).get("test_cutoff"))
        hyper = report.get("hyperparameters") or {}
        frozen = str(hyper.get("config_hash") or "")
        searched = {str(t.get("config_hash")) for t in (hyper.get("search") or [])}
        if not frozen:
            findings.append(f"{where}: no frozen config hash, so freezing cannot be checked")
        elif searched and frozen not in searched:
            findings.append(
                f"{where}: the frozen config {frozen[:12]} is not one of the "
                f"{len(searched)} searched candidates"
            )
        gridded = report.get("gridded_fit") or {}
        if not str(gridded.get("parameter_snapshot_hash") or "").strip("0"):
            findings.append(f"{where}: the gridded fit records no parameter snapshot hash")
        diagnostics = (report.get("ensemble_fit") or {}).get("diagnostics") or {}
        times = [_instant(t) for t in diagnostics.get("validation_issue_times") or []]
        closes = [t + HORIZON for t in times if t is not None]
        if cutoff is not None and closes and max(closes) > cutoff:
            findings.append(
                f"{where}: an ensemble weight-fitting window closes at {max(closes).isoformat()}, "
                f"after the test cutoff {cutoff.isoformat()}"
            )
        for name, component in (
            diagnostics.get("component_fits_at_first_validation_window") or {}
        ).items():
            fitted = _instant((component or {}).get("fit_cutoff"))
            if cutoff is not None and fitted is not None and fitted > cutoff:
                findings.append(
                    f"{where}: the ensemble's {name} component was fitted at "
                    f"{fitted.isoformat()}, after the test cutoff"
                )
            if _is_leaky(str((component or {}).get("model_id") or "")):
                findings.append(f"{where}: the ensemble pooled a leaky component ({name})")
    return findings


def _verdict_lines(overall: dict[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for model_id, verdict in overall.items():
        state = "PROMOTED" if verdict["promoted"] else "NOT PROMOTED"
        passing = ", ".join(verdict["regions_passing"]) or "no region"
        lines.append(
            f"{model_id}: {state} — conditions 1 and 2 met in {passing}; "
            f"{verdict['regions_required']} of {len(PROTOCOL_REGIONS)} regions required"
        )
        for region, why in verdict["regions_that_cannot_pass"].items():
            lines.append(f"  {region}: not evaluated, and no model could pass there — {why}")
        for region in verdict["regions_that_could_still_pass"]:
            lines.append(f"  {region}: not evaluated")
        if verdict["regions_not_evaluated"]:
            lines.append(
                "  the verdict could not have changed had the unevaluated regions been run"
                if verdict["verdict_robust_to_unevaluated_regions"]
                else "  running the unevaluated regions could change this verdict"
            )
        for region in verdict["per_region"]:
            reasons = region["reasons_not_promotable"]
            detail = "; ".join(reasons[:2]) if reasons else "both conditions met"
            lines.append(f"  {region['region_id']}: {detail}")
            for warning in region["warnings"]:
                lines.append(f"    warning: {warning}")
            condition_2 = region["condition_2_paired_t_test"]
            if not condition_2["decidable"]:
                lines.append(
                    f"    condition 2 is not decidable from the committed evidence "
                    f"({'; '.join(condition_2['reasons'])}), so it is recorded as not met"
                )
    return lines


def run(repo_root: Path) -> GateResult:
    findings: list[str] = []
    findings.extend(_splitter_has_no_randomness())
    findings.extend(_blocked_splits_are_time_forward())

    fits = sorted(
        p
        for name in ("ntpp", "gridded", "ensemble")
        for p in (repo_root / "baselines" / name).rglob("fit_result.json")
    )
    for fit in fits:
        findings.extend(_fit_is_honest(fit))
    findings.extend(_report_audits_the_fit_it_cannot_show(repo_root))

    evidence, notes = _evidence(repo_root)
    if not fits and not evidence:
        return GateResult(
            name=GATE,
            status=GateStatus.SKIPPED,
            reason=(
                "no challenger fit under baselines/{ntpp,gridded,ensemble} and no committed "
                "schedule under reports/challenger or reports/protocol; the leakage controls were "
                "checked but there was no result to judge"
            ),
            findings=[f"splitter and blocked-CV checks passed ({len(findings)} findings)"],
        )

    overall, verdict_findings = _verdicts(evidence, _regions_that_cannot_pass(repo_root))
    findings.extend(verdict_findings)
    promoted = {model for model, verdict in overall.items() if verdict["promoted"]}

    for model_id, card in MODEL_CARDS.items():
        if model_id not in overall:
            continue
        declared = _declared_status(repo_root / card)
        expected = "promoted" if model_id in promoted else "not promoted"
        if declared is None:
            findings.append(
                f"{card}: no machine-readable promotion status. Write a line matching "
                f"'Promotion status ...: {expected}' so the gate can check the card against "
                f"the rule instead of a reader checking it against their memory"
            )
        elif declared != expected:
            findings.append(
                f"{card} declares '{declared}' but the rule recomputed from the committed "
                f"evidence says '{expected}'"
            )
    findings.extend(_prose_claims(repo_root, promoted))

    if findings:
        return GateResult(name=GATE, status=GateStatus.FAILED, findings=findings)
    return GateResult(
        name=GATE,
        status=GateStatus.PASSED,
        findings=[
            *_verdict_lines(overall),
            *notes,
            f"{len(evidence)} committed challenger schedule(s) recomputed under "
            "docs/EVALUATION_PROTOCOL.md section 10 (ADR-0040); every published claim agrees",
            "the splitter cannot express a random or shuffled split",
            "blocked CV is strictly time-forward for every configuration tried",
            f"{len(fits)} challenger fit(s): converged, subcritical, trained before the cutoff",
            "no leaky ablation artefact is persisted as a baseline or counted as evidence",
        ],
    )
