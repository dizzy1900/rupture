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


def test_an_allowlisted_fragment_exempts_itself_not_the_line() -> None:
    """A claim must not ride along beside a permitted phrase.

    Found by review: the scanner used to skip the whole line when any allowlisted fragment
    appeared on it. Published paper titles live in citation tables, and a markdown table row is a
    single line, so a claim placed in the next cell went unseen. Each case below is one the
    reviewer constructed.
    """
    allow = language.load_allowlist()
    title = "BC Hydro Ground Motion Prediction Equations for Subduction Earthquakes"
    smuggled = [
        f"| {title} | an M7.2 will strike Istanbul and is imminent |",  # lang-gate: allow
        "rupture does not predict earthquakes, but an M7 will occur.",  # lang-gate: allow
    ]
    for line in smuggled:
        assert language.scan_text(line, allowlist=allow, label="x"), (
            f"a claim rode along beside an allowlisted fragment: {line}"
        )

    # ...and the legitimate uses still pass
    assert (
        language.scan_text(f"| {title} | subduction interface |", allowlist=allow, label="x") == []
    )
    assert (
        language.scan_text("rupture does not predict earthquakes.", allowlist=allow, label="x")
        == []
    )
