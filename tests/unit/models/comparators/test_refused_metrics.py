"""The comparator package must not grow a path back to the refused metrics."""

from __future__ import annotations

from pathlib import Path

COMPARATORS = Path(__file__).resolve().parents[4] / "src" / "rupture" / "models" / "comparators"

BANNED = ("roc_auc", "accuracy_score")


def test_comparator_modules_do_not_contain_refused_metric_strings() -> None:
    files = sorted(COMPARATORS.rglob("*.py"))
    assert files, f"no comparator modules under {COMPARATORS}"
    offenders: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for needle in BANNED:
            if needle in text:
                offenders.append(f"{path.relative_to(COMPARATORS)}:{needle}")
    assert not offenders, f"refused metric strings in comparator sources: {offenders}"


def test_sklearn_metrics_is_not_imported() -> None:
    for path in COMPARATORS.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "sklearn.metrics" not in text
        assert "sklearn" not in text
