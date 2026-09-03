"""The cascade gate itself: it must pass here, and it must fail when something drifts."""

from __future__ import annotations

import shutil
from pathlib import Path

from rupture.validation import cascade as gate
from rupture.validation.registry import GATES, run_gate
from rupture.validation.result import GateStatus


def test_the_gate_is_registered() -> None:
    assert "cascade" in GATES


def test_the_gate_passes_on_the_committed_tree(repo_root: Path) -> None:
    result = run_gate("cascade", repo_root)
    assert result.status is GateStatus.PASSED, "\n".join(result.findings)


def test_the_gate_reports_the_numbers_the_docs_quote(repo_root: Path) -> None:
    findings = " ".join(gate.run(repo_root).findings)
    assert "link round trip" in findings
    assert "UNCONDITIONED" in findings
    assert "us7000tbwb: excluded from tectonic fitting" in findings
    assert "cascade-exposure.v0.json" in findings
    assert "all finite and in [0, 1]" in findings


def test_the_gate_fails_when_a_fixture_is_tampered_with(repo_root: Path, tmp_path: Path) -> None:
    copy = tmp_path / "repo"
    for relative in ("tests/fixtures/cascade", "data/fixtures/comcat", "contracts"):
        shutil.copytree(repo_root / relative, copy / relative)
    target = copy / "tests/fixtures/cascade/gorkha-2015/usgs_zhu_2017_general_coverage_slice.csv"
    lines = target.read_text().splitlines()
    lines[1] = lines[1].rsplit(",", 1)[0] + ",0.9999"
    target.write_text("\n".join(lines) + "\n")
    result = gate.run(copy)
    assert result.status is GateStatus.FAILED
    assert any("sha256 mismatch" in f for f in result.findings)


def test_the_gate_fails_when_a_coefficient_drifts(repo_root: Path, tmp_path: Path) -> None:
    copy = tmp_path / "repo"
    shutil.copytree(repo_root / "tests/fixtures/cascade", copy / "tests/fixtures/cascade")
    findings: list[str] = []
    source = copy / "tests/fixtures/cascade/usgs_groundfailure/zhu_2017.py.txt"
    source.write_text(source.read_text().replace('"b1": 0.334', '"b1": 0.999'))
    assert not gate._check_coefficient_provenance(copy, findings)
    assert any("coefficient drift" in f for f in findings)


def test_the_gate_names_a_missing_fixture_tree(tmp_path: Path) -> None:
    result = gate.run(tmp_path)
    assert result.status is GateStatus.FAILED
    assert any("cascade fixtures missing" in f for f in result.findings)
