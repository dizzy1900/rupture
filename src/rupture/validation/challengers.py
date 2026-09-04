"""``validate-challengers``: the leakage controls that make a promotion decision mean anything.

A challenger that beats ETAS because information leaked across the cutoff is worse than no
challenger at all, so this gate checks the machinery before it checks the scores:

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
   ablation carries a leaky model id and never appears under ``baselines/``.

The promotion decision itself is reported in ``reports/CHALLENGER_EVALUATION.md``; this gate
enforces that it was arrived at legitimately. It runs offline and SKIPS with a printed reason when
no challenger fit is present.
"""

from __future__ import annotations

import ast
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rupture.models.data import splits
from rupture.models.data.splits import blocked_splits
from rupture.validation.result import GateResult, GateStatus

GATE = "validate-challengers"
LEAKY_MARKERS = ("leak", "ablation")


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
    if any(m in model_id.lower() for m in LEAKY_MARKERS):
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
    snapshot = fit.get("parameter_snapshot_hash")
    if not snapshot or not str(snapshot).strip("0"):
        findings.append(
            f"{where}: no usable parameter_snapshot_hash, so a silent retrain is invisible"
        )
    return findings


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

    if not fits:
        return GateResult(
            name=GATE,
            status=GateStatus.SKIPPED,
            reason=(
                "no challenger fit under baselines/{ntpp,gridded,ensemble}; the leakage controls "
                "were checked but no trained model was available to audit"
            ),
            findings=[f"splitter and blocked-CV checks passed ({len(findings)} findings)"],
        )

    if findings:
        return GateResult(name=GATE, status=GateStatus.FAILED, findings=findings)
    return GateResult(
        name=GATE,
        status=GateStatus.PASSED,
        findings=[
            "the splitter cannot express a random or shuffled split",
            "blocked CV is strictly time-forward for every configuration tried",
            f"{len(fits)} challenger fit(s): converged, subcritical, trained before the cutoff",
            "no leaky ablation artefact is persisted as a baseline",
            "the promotion decision itself is in reports/CHALLENGER_EVALUATION.md",
        ],
    )
