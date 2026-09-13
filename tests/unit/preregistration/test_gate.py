"""The prereg gate: empty tree passes; schema and ancestry failures block."""

from __future__ import annotations

import subprocess
from pathlib import Path

from tests.unit.preregistration.test_schema import SAMPLE_YAML

from rupture.preregistration.load import discover
from rupture.validation.prereg import run
from rupture.validation.result import GateStatus

REPO_ROOT = Path(__file__).resolve().parents[3]
MK_FILE = REPO_ROOT / "mk" / "prereg.mk"


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def _init_repo(root: Path) -> None:
    _run_git(root, "init", "-b", "main")


def _commit(root: Path, message: str) -> str:
    _run_git(
        root,
        "-c",
        "user.email=prereg@test",
        "-c",
        "user.name=prereg",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-m",
        message,
    )
    return _run_git(root, "rev-parse", "HEAD").stdout.strip()


def test_the_make_fragment_registers_the_target() -> None:
    text = MK_FILE.read_text(encoding="utf-8")
    assert "VALIDATE_GATES += validate-prereg" in text
    assert "rupture validate prereg" in text


def test_zero_experiments_passes_with_a_finding() -> None:
    result = run(REPO_ROOT)
    assert result.status is GateStatus.PASSED
    assert result.ok
    assert "no experiments registered" in result.findings


def test_discover_ignores_readme_and_underscore_names(tmp_path: Path) -> None:
    experiments = tmp_path / "experiments"
    experiments.mkdir()
    (experiments / "README.md").write_text("# no\n", encoding="utf-8")
    template = experiments / "_template"
    template.mkdir()
    (template / "preregistration.yaml").write_text(SAMPLE_YAML, encoding="utf-8")
    real = experiments / "real"
    real.mkdir()
    (real / "preregistration.yaml").write_text(SAMPLE_YAML, encoding="utf-8")
    found = discover(tmp_path)
    assert len(found) == 1
    assert found[0].parent.name == "real"


def test_invalid_yaml_fails(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    target = tmp_path / "experiments" / "broken"
    target.mkdir(parents=True)
    (target / "preregistration.yaml").write_text("hypothesis: only\n", encoding="utf-8")
    _run_git(tmp_path, "add", "--", "experiments/broken/preregistration.yaml")
    _commit(tmp_path, "broken registration")
    result = run(tmp_path)
    assert result.status is GateStatus.FAILED
    assert any("invalid preregistration" in line for line in result.findings)


def test_registration_before_data_is_strong(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    yaml_text = SAMPLE_YAML.replace(
        "experiment_id: template-not-an-experiment", "experiment_id: demo"
    ).replace(
        "  - data/fixtures/catalogs/california/provenance.json",
        "  - data/catalog.txt",
    )
    exp = tmp_path / "experiments" / "demo"
    exp.mkdir(parents=True)
    (exp / "preregistration.yaml").write_text(yaml_text, encoding="utf-8")
    _run_git(tmp_path, "add", "--", "experiments/demo/preregistration.yaml")
    _commit(tmp_path, "register")
    data = tmp_path / "data" / "catalog.txt"
    data.parent.mkdir()
    data.write_text("events\n", encoding="utf-8")
    _run_git(tmp_path, "add", "--", "data/catalog.txt")
    _commit(tmp_path, "data")
    result = run(tmp_path)
    assert result.status is GateStatus.PASSED
    assert any("strong" in line for line in result.findings)


def test_data_before_registration_is_labelled_weak(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    data = tmp_path / "data" / "catalog.txt"
    data.parent.mkdir(parents=True)
    data.write_text("events\n", encoding="utf-8")
    _run_git(tmp_path, "add", "--", "data/catalog.txt")
    _commit(tmp_path, "data")
    yaml_text = SAMPLE_YAML.replace(
        "experiment_id: template-not-an-experiment", "experiment_id: demo"
    ).replace(
        "  - data/fixtures/catalogs/california/provenance.json",
        "  - data/catalog.txt",
    )
    exp = tmp_path / "experiments" / "demo"
    exp.mkdir(parents=True)
    (exp / "preregistration.yaml").write_text(yaml_text, encoding="utf-8")
    _run_git(tmp_path, "add", "--", "experiments/demo/preregistration.yaml")
    _commit(tmp_path, "register")
    result = run(tmp_path)
    assert result.status is GateStatus.PASSED
    assert any("weak_data_predates" in line for line in result.findings)


def test_in_place_amendment_fails(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    yaml_text = (
        SAMPLE_YAML.replace("experiment_id: template-not-an-experiment", "experiment_id: demo")
        .replace("  - data/fixtures/catalogs/california/provenance.json", "")
        .replace("test_data_paths:", "test_data_paths: []")
    )
    exp = tmp_path / "experiments" / "demo"
    exp.mkdir(parents=True)
    path = exp / "preregistration.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    _run_git(tmp_path, "add", "--", "experiments/demo/preregistration.yaml")
    _commit(tmp_path, "register")
    path.write_text(yaml_text + "# touched\n", encoding="utf-8")
    _run_git(tmp_path, "add", "--", "experiments/demo/preregistration.yaml")
    _commit(tmp_path, "amend in place")
    result = run(tmp_path)
    assert result.status is GateStatus.FAILED
    assert any("amended after" in line for line in result.findings)
