"""The banned-language gate must catch claims and honour the allowlist."""

from __future__ import annotations

from pathlib import Path

from rupture.validation import GateStatus, language

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_banned_word_is_caught() -> None:
    text = "This model can predict the next event."  # lang-gate: allow
    findings = language.scan_text(text, allowlist=[], label="x")
    assert findings, "a bare claim of that kind must be flagged"
    assert "predict*" in findings[0]  # lang-gate: allow


def test_deterministic_phrasing_is_caught() -> None:
    text = (
        "A magnitude 7 will occur in the corridor.\n"  # lang-gate: allow
        "An imminent rupture is expected."  # lang-gate: allow
    )
    findings = language.scan_text(text, allowlist=[], label="x")
    assert len(findings) == 2


def test_forecast_vocabulary_is_fine() -> None:
    text = "Expected count of M>=4.5 events per cell over the next 30 days: 0.07."
    assert language.scan_text(text, allowlist=[], label="x") == []


def test_allowlisted_sentence_passes() -> None:
    allow = language.load_allowlist()
    assert "rupture does not predict earthquakes" in allow
    sentence = "rupture does not predict earthquakes."
    assert language.scan_text(sentence, allowlist=allow, label="x") == []


def test_repository_tree_is_clean() -> None:
    result = language.run(REPO_ROOT)
    assert result.status == GateStatus.PASSED, "\n".join(result.findings)


def test_seeded_violation_fails(tmp_path: Path) -> None:
    bad = "Our predictor says a quake will hit tomorrow.\n"  # lang-gate: allow
    (tmp_path / "bad.md").write_text(bad)
    result = language.run(tmp_path)
    assert result.status == GateStatus.FAILED
    assert len(result.findings) == 1
