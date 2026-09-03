"""``validate-risk`` itself: it runs offline, it passes here, and it fails when it should."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from rupture.validation.result import GateStatus
from rupture.validation.risk import run
from tests.unit.risk.conftest import REPO_ROOT


@pytest.fixture(scope="module")
def result() -> object:
    return run(REPO_ROOT)


def test_the_gate_passes_offline(result: object) -> None:
    assert result.status is GateStatus.PASSED, "\n".join(result.findings)  # type: ignore[attr-defined]
    assert result.ok  # type: ignore[attr-defined]


def test_the_gate_reports_what_it_checked(result: object) -> None:
    findings = "\n".join(result.findings)  # type: ignore[attr-defined]
    for expected in (
        "reference values",
        "ground-motion field",
        "expected loss",
        "avoided loss",
        "contract v1 round-trip OK",
    ):
        assert expected in findings, expected


def test_the_gate_uses_the_committed_fixture_not_a_sibling_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pointing SERAC_EXPORT_DIR somewhere else must not change the gate's answer."""
    monkeypatch.setenv("SERAC_EXPORT_DIR", str(tmp_path))
    assert run(REPO_ROOT).status is GateStatus.PASSED


def test_a_drifted_fixture_fails_the_gate(tmp_path: Path) -> None:
    """Copy the tree, corrupt one reference table, and check the gate notices."""
    root = tmp_path / "repo"
    for relative in (
        Path("tests/fixtures/risk"),
        Path("src/rupture/adapters/groundmotion/data"),
    ):
        shutil.copytree(REPO_ROOT / relative, root / relative)
    provenance = root / "tests/fixtures/risk/gsim/bssa14/provenance.json"
    record = json.loads(provenance.read_text(encoding="utf-8"))
    record["files"][0]["sha256"] = "0" * 64
    provenance.write_text(json.dumps(record, indent=2), encoding="utf-8")

    outcome = run(root)
    assert outcome.status is GateStatus.FAILED
    assert any("digest mismatch" in f for f in outcome.findings)
