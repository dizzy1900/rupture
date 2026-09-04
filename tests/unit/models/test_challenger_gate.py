"""``validate-challengers`` as the promotion gate: does it catch a claim the evidence denies?

The gate is the only thing standing between "the rule says not promoted" and a document that says
otherwise, so what is tested here is the disagreement, not the happy path: a card claiming a
promotion the evidence refuses, prose drifting into a claim, a verdict that depends on which ETAS
run was used as the baseline, and a region that was never evaluated.

Every repository here is synthetic and built in a tmp_path. The numbers are invented and mean
nothing about any region; what is under test is the gate's arithmetic and its refusals.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from rupture.validation.challengers import run
from rupture.validation.result import GateStatus

STEP = timedelta(days=30)
START = datetime(2022, 1, 1, tzinfo=UTC)
MODEL = "ensemble-loglinear"
CARD = "reports/MODEL_CARD_ensemble.md"


def _windows(count: int, *, advantage: float | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(count):
        row: dict[str, Any] = {"issue_time": (START + i * STEP).isoformat()}
        if advantage is not None:
            offsets = [0.01 * (j - 2) for j in range(5)]
            row["pooling"] = {
                "log_rates": [advantage + o for o in offsets],
                "benchmark_log_rates": [0.0 for _ in offsets],
                "n_forecast": 1.0,
                "benchmark_n_forecast": 1.0,
            }
        rows.append(row)
    return rows


def _rates(value: float) -> dict[str, Any]:
    return {t: {"rate": value, "scored": 20, "passed": 1} for t in ("N", "M", "S", "L", "CL")}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _repo(
    root: Path,
    *,
    regions: dict[str, tuple[float, float | None]],
    baseline_windows: int = 20,
    declared: str = "not promoted",
    prose: str = "",
) -> Path:
    """A synthetic tree: an ETAS schedule and a challenger schedule per region, plus a model card.

    ``regions`` maps a region id to (challenger pass rate, per-event advantage over the baseline);
    an advantage of ``None`` records no pooling terms, so condition 2 is undecidable.
    """
    for region_id, (rate, advantage) in regions.items():
        _write(
            root
            / "reports/protocol"
            / region_id
            / "eval"
            / f"schedule-{region_id}-etas-mizrahi.json",
            {
                "model_id": "etas-mizrahi",
                "region_id": region_id,
                "pass_rates": _rates(0.5),
                "windows": _windows(baseline_windows, advantage=None),
            },
        )
        _write(
            root / "reports/challenger" / region_id / f"schedule-{region_id}-challengers.json",
            {
                "region_id": region_id,
                "protocol": {"test_cutoff": START.isoformat()},
                "etas_baseline": {"pass_rates": _rates(0.5)},
                "hyperparameters": {"config_hash": "abc", "search": [{"config_hash": "abc"}]},
                "gridded_fit": {"parameter_snapshot_hash": "deadbeef"},
                "ensemble_fit": {"diagnostics": {}},
                "models": {
                    MODEL: {
                        "pass_rates": _rates(rate),
                        "pooled_paired_test": None,
                        "windows": _windows(20, advantage=advantage),
                    }
                },
            },
        )
    card = root / CARD
    card.parent.mkdir(parents=True, exist_ok=True)
    card.write_text(f"# card\n\n**Promotion status: {declared}.**\n{prose}\n", encoding="utf-8")
    return root


def _pooled_into(root: Path, region_id: str) -> None:
    """Compute the pooled test from the windows, the way a schedule runner does."""
    from rupture.models.promotion import pooled_paired_test  # noqa: PLC0415 - test-local

    path = root / "reports/challenger" / region_id / f"schedule-{region_id}-challengers.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    block = report["models"][MODEL]
    block["pooled_paired_test"] = pooled_paired_test(block["windows"])
    _write(path, report)


def test_a_model_that_meets_the_rule_in_one_region_is_not_promoted(tmp_path: Path) -> None:
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.9, 1.0), "nepal-himalaya": (0.1, -1.0)})
    for region in ("turkiye-eaf", "nepal-himalaya"):
        _pooled_into(root, region)
    result = run(root)
    assert result.status is GateStatus.PASSED
    assert any("NOT PROMOTED" in f and MODEL in f for f in result.findings)
    assert any("california" in f and "not evaluated" in f for f in result.findings)


def test_a_card_claiming_a_promotion_the_evidence_refuses_fails_the_gate(tmp_path: Path) -> None:
    """The failure this gate exists for: the document and the rule disagreeing."""
    root = _repo(
        tmp_path,
        regions={"turkiye-eaf": (0.9, 1.0), "nepal-himalaya": (0.1, -1.0)},
        declared="promoted",
    )
    for region in ("turkiye-eaf", "nepal-himalaya"):
        _pooled_into(root, region)
    result = run(root)
    assert result.status is GateStatus.FAILED
    assert any("declares 'promoted'" in f for f in result.findings)


def test_a_card_denying_a_promotion_the_rule_admits_also_fails(tmp_path: Path) -> None:
    """Drift is a failure in both directions: the card must say what the evidence says."""
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.9, 1.0), "nepal-himalaya": (0.9, 1.0)})
    for region in ("turkiye-eaf", "nepal-himalaya"):
        _pooled_into(root, region)
    result = run(root)
    assert result.status is GateStatus.FAILED
    assert any("says 'promoted'" in f for f in result.findings)


def test_a_card_with_no_machine_readable_status_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.1, -1.0)})
    _pooled_into(root, "turkiye-eaf")
    (root / CARD).write_text("# card\n\nIt did fine.\n", encoding="utf-8")
    result = run(root)
    assert result.status is GateStatus.FAILED
    assert any("no machine-readable promotion status" in f for f in result.findings)


def test_prose_drifting_into_a_promotion_claim_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.1, -1.0)})
    _pooled_into(root, "turkiye-eaf")
    evaluation = root / "reports/CHALLENGER_EVALUATION.md"
    evaluation.write_text(
        "# Challenger evaluation\n\nThe ensemble was promoted after review.\n", encoding="utf-8"
    )
    result = run(root)
    assert result.status is GateStatus.FAILED
    assert any("reads as a promotion claim" in f for f in result.findings)


def test_a_negated_or_region_scoped_sentence_is_not_a_claim(tmp_path: Path) -> None:
    """The scan must not fire on the honest reporting it sits beside."""
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.1, -1.0)})
    _pooled_into(root, "turkiye-eaf")
    (root / "reports/CHALLENGER_EVALUATION.md").write_text(
        "# Challenger evaluation\n\n"
        "None is promoted. A challenger is promotable only if it beats ETAS.\n"
        "It meets both conditions in this region. Promotable in this region.\n",
        encoding="utf-8",
    )
    assert run(root).status is GateStatus.PASSED


def test_a_verdict_that_depends_on_which_etas_run_was_the_baseline_fails(tmp_path: Path) -> None:
    """ADR-0040 decision 6: a verdict that survives only under a re-run is not a verdict."""
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.6, 1.0)})
    _pooled_into(root, "turkiye-eaf")
    path = root / "reports/challenger/turkiye-eaf/schedule-turkiye-eaf-challengers.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["etas_baseline"]["pass_rates"] = _rates(0.9)  # a stricter baseline, embedded in the run
    _write(path, report)
    result = run(root)
    assert result.status is GateStatus.FAILED
    assert any("depends on which ETAS run" in f for f in result.findings)


def test_condition_two_without_pooling_terms_is_recorded_as_undecidable(tmp_path: Path) -> None:
    """The committed NTPP case: per-window comparisons only, so the pooled test cannot be run."""
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.9, None)})
    result = run(root)
    assert result.status is GateStatus.PASSED
    assert any("not decidable from the committed evidence" in f for f in result.findings)


def test_no_evidence_at_all_skips_with_a_reason(tmp_path: Path) -> None:
    result = run(tmp_path)
    assert result.status is GateStatus.SKIPPED
    assert result.reason is not None
    assert "no challenger fit" in result.reason


def test_an_ensemble_weight_window_reaching_the_test_cutoff_fails(tmp_path: Path) -> None:
    """The freezing claim for the fits that are not committed, checked through the report."""
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.1, -1.0)})
    _pooled_into(root, "turkiye-eaf")
    path = root / "reports/challenger/turkiye-eaf/schedule-turkiye-eaf-challengers.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["ensemble_fit"]["diagnostics"] = {
        "validation_issue_times": [(START - timedelta(days=5)).isoformat()]
    }
    _write(path, report)
    result = run(root)
    assert result.status is GateStatus.FAILED
    assert any("after the test cutoff" in f for f in result.findings)


def test_a_frozen_config_that_was_never_searched_fails(tmp_path: Path) -> None:
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.1, -1.0)})
    _pooled_into(root, "turkiye-eaf")
    path = root / "reports/challenger/turkiye-eaf/schedule-turkiye-eaf-challengers.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["hyperparameters"] = {"config_hash": "zzz", "search": [{"config_hash": "abc"}]}
    _write(path, report)
    result = run(root)
    assert result.status is GateStatus.FAILED
    assert any("not one of the" in f and "searched candidates" in f for f in result.findings)


def _ntpp_fit(root: Path, *, trials: list[dict[str, Any]], grid: dict[str, Any] | None) -> None:
    fit_dir = root / "baselines/ntpp/turkiye-eaf"
    _write(
        fit_dir / "fit_result.json",
        {
            "model_id": "ntpp-neural-hawkes",
            "converged": True,
            "fit_cutoff": START.isoformat(),
            "parameter_snapshot_hash": "abc123",
            "diagnostics": {"training_max_origin_time": (START - STEP).isoformat()},
        },
    )
    record: dict[str, Any] = {
        "validation_end": START.isoformat(),
        "chosen_config_hash": "abc",
        "trials": trials,
    }
    if grid is not None:
        record["grid"] = grid
    _write(fit_dir / "hyperparameters.json", record)


def test_a_frozen_record_the_search_code_cannot_reproduce_fails(tmp_path: Path) -> None:
    """ "Frozen before scoring" is only evidence if the search that produced it can be re-run."""
    root = _repo(tmp_path, regions={"turkiye-eaf": (0.1, -1.0)})
    _pooled_into(root, "turkiye-eaf")
    _ntpp_fit(root, trials=[{"config_hash": "not-a-real-candidate"}], grid=None)
    result = run(root)
    assert result.status is GateStatus.FAILED
    assert any("would search a different space" in f for f in result.findings)


def test_the_committed_default_grid_reproduces_a_frozen_record(tmp_path: Path) -> None:
    from rupture.models.challengers.ntpp.train import (  # noqa: PLC0415 - heavy, and test-local
        candidate_configs,
    )

    root = _repo(tmp_path, regions={"turkiye-eaf": (0.1, -1.0)})
    _pooled_into(root, "turkiye-eaf")
    _ntpp_fit(
        root,
        trials=[{"config_hash": c.config_hash()} for c in candidate_configs()],
        grid=None,
    )
    assert run(root).status is GateStatus.PASSED
