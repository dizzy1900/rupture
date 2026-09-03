"""Adapter behaviour that can be checked without Docker: availability, staging, argv, parsing."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rupture.adapters.hazard import DEFAULT_IMAGE, OpenQuakeDocker, OpenQuakeError
from rupture.adapters.hazard import openquake_docker as oqd
from rupture.cli import app
from rupture.pipelines import hazard as pipeline
from rupture.ports.hazard_engine import ClassicalPSHAJob
from rupture.validation import GateStatus
from rupture.validation import hazard as gate
from tests.unit.hazard.conftest import QA_CASE_01, REPO_ROOT, FakeDocker


# ------------------------------------------------------------------ availability
def test_available_is_false_without_docker_binary(no_docker_on_path: Path) -> None:
    ok, reason = OpenQuakeDocker().available()
    assert ok is False
    assert "docker" in reason
    assert "not found on PATH" in reason


def test_available_is_false_when_daemon_does_not_answer() -> None:
    def runner(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv, 1, "", "Cannot connect to the Docker daemon at unix:///var/run/docker.sock\n"
        )

    engine = OpenQuakeDocker(runner=runner, which=lambda _: "/usr/bin/docker")
    ok, reason = engine.available()
    assert ok is False
    assert reason.startswith("docker daemon not reachable: Cannot connect")


def test_available_is_true_when_info_answers(fake_docker: FakeDocker) -> None:
    engine = OpenQuakeDocker(runner=fake_docker, which=lambda _: "/usr/bin/docker")
    assert engine.available() == (True, "")
    assert engine.image == DEFAULT_IMAGE
    assert engine.image_digest() is not None


def test_image_override_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(oqd.IMAGE_ENV, "openquake/engine:nightly")
    assert OpenQuakeDocker().image == "openquake/engine:nightly"
    assert OpenQuakeDocker(image="x/y:1").image == "x/y:1"


# ------------------------------------------------------------------ gate + CLI skip semantics
def test_gate_skips_with_reason_without_docker(no_docker_on_path: Path) -> None:
    result = gate.run(REPO_ROOT)
    assert result.status == GateStatus.SKIPPED
    assert result.reason is not None
    assert result.reason.startswith("Docker not available:")
    assert "hazard-integration" in result.reason
    assert result.ok, "skipped-with-reason does not block promotion"
    assert "SKIPPED" in result.render()


def test_cli_demo_and_check_report_skip_without_docker(no_docker_on_path: Path) -> None:
    runner = CliRunner()
    res = runner.invoke(app, ["hazard", "check"])
    assert res.exit_code == 3
    assert "not available" in res.output
    res = runner.invoke(app, ["hazard", "demo"])
    assert res.exit_code == 3
    assert "SKIPPED: Docker not available" in res.output


# ------------------------------------------------------------------ staging + fake container
def _job(tmp_path: Path) -> ClassicalPSHAJob:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in ("source_model_logic_tree.xml", "gsim_logic_tree.xml", "source_model.xml"):
        shutil.copyfile(QA_CASE_01 / name, inputs / name)
    return ClassicalPSHAJob(
        id="qa-like",
        description="staging test",
        source_model_logic_tree=inputs / "source_model_logic_tree.xml",
        gsim_logic_tree=inputs / "gsim_logic_tree.xml",
        region_wkt="POLYGON((0 0, 0.3 0, 0.3 0.1, 0 0.1, 0 0))",
        region_grid_spacing_km=10.0,
        investigation_time_years=1.0,
        imts={"PGA": (0.1, 0.4, 0.6), "SA(0.1)": (0.1, 0.4, 0.6)},
    )


def test_run_classical_stages_inputs_builds_docker_argv_and_parses(
    tmp_path: Path, fake_docker: FakeDocker
) -> None:
    engine = OpenQuakeDocker(runner=fake_docker, which=lambda _: "/usr/bin/docker")
    work = tmp_path / "work"
    curve_set = engine.run_classical(_job(tmp_path), work)

    # staged files: job.ini, both logic trees and the source model the tree names
    for name in (
        "job.ini",
        "source_model_logic_tree.xml",
        "gsim_logic_tree.xml",
        "source_model.xml",
    ):
        assert (work / name).is_file(), name
    run_calls = [c for c in fake_docker.calls if c[1] == "run"]
    assert len(run_calls) == 1
    argv = run_calls[0]
    assert argv[:3] == ["docker", "run", "--rm"]
    assert "-w" not in argv, "the image's relative ENTRYPOINT breaks under -w"
    assert f"{work.resolve()}:/work" in argv
    assert DEFAULT_IMAGE in argv
    script = argv[-1]
    assert argv[-3:-1] == ["bash", "-c"]
    assert "oq engine --run /work/job.ini" in script
    assert "oq export hcurves -e csv -d /work/out" in script
    assert "umask 000" in script

    assert (work / "oq.log").is_file()
    assert curve_set.id == "qa-like"
    assert curve_set.source_model_id == "source_model_logic_tree"
    assert curve_set.gsim_logic_tree_id == "gsim_logic_tree"
    assert curve_set.realisation == "mean"
    assert len(curve_set.curves) == 8
    assert curve_set.job_hash == oqd.hash_inputs(work), "hash covers job.ini + inputs, not outputs"
    assert curve_set.provenance.source == "openquake.engine"
    assert curve_set.provenance.source_url is not None
    assert curve_set.provenance.source_url.startswith("docker://openquake/engine@sha256:")
    assert curve_set.provenance.licence is not None
    assert curve_set.provenance.licence.startswith("AGPL-3.0")


def test_run_classical_fails_loudly_when_container_exits_nonzero(tmp_path: Path) -> None:
    fake = FakeDocker(run_exit=7)
    engine = OpenQuakeDocker(runner=fake, which=lambda _: "/usr/bin/docker")
    with pytest.raises(OpenQuakeError, match="exited 7"):
        engine.run_classical(_job(tmp_path), tmp_path / "work")
    assert "boom" in (tmp_path / "work" / "oq.log").read_text()


def test_run_classical_refuses_missing_inputs(tmp_path: Path, fake_docker: FakeDocker) -> None:
    job = _job(tmp_path).model_copy(update={"gsim_logic_tree": tmp_path / "missing.xml"})
    engine = OpenQuakeDocker(runner=fake_docker, which=lambda _: "/usr/bin/docker")
    with pytest.raises(FileNotFoundError, match=r"missing\.xml"):
        engine.run_classical(job, tmp_path / "work")


def test_investigation_time_mismatch_between_job_and_export_is_an_error(
    tmp_path: Path, fake_docker: FakeDocker
) -> None:
    job = _job(tmp_path).model_copy(update={"investigation_time_years": 50.0})
    fake_docker.echo_job_time = False  # the fake export keeps the fixture's 1.0
    engine = OpenQuakeDocker(runner=fake_docker, which=lambda _: "/usr/bin/docker")
    with pytest.raises(
        OpenQuakeError, match=r"investigation_time 1\.0 differs from job\.ini 50\.0"
    ):
        engine.run_classical(job, tmp_path / "work")


def test_bundled_demo_copies_runs_and_parses(tmp_path: Path, fake_docker: FakeDocker) -> None:
    engine = OpenQuakeDocker(runner=fake_docker, which=lambda _: "/usr/bin/docker")
    work = tmp_path / "demo"
    curve_set = pipeline.run_demo(engine, work, oqd.DEFAULT_DEMO)
    run_calls = [c for c in fake_docker.calls if c[1] == "run"]
    assert len(run_calls) == 2, "one container to copy the demo out, one to run it"
    copy_script = run_calls[0][-1]
    assert "/opt/openquake/demos/hazard/AreaSourceClassicalPSHA" in copy_script
    assert "find /" in copy_script, "falls back to searching the image"
    assert (work / "job.ini").is_file()
    assert (work / "source_model.xml").is_file()
    assert curve_set.id == "openquake-demo-hazard-AreaSourceClassicalPSHA"
    assert curve_set.source_model_id == "source_model_logic_tree"
    assert curve_set.gsim_logic_tree_id == "gmpe_logic_tree"
    written = json.loads((work / pipeline.CURVE_SET_FILE).read_text())
    assert written["id"] == curve_set.id


def test_gate_runs_demo_through_fake_docker_and_fails_on_time_mismatch(
    tmp_path: Path, fake_docker: FakeDocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The fake export keeps investigation_time=1.0 while the demo job.ini says 50.0."""
    monkeypatch.setenv(gate.WORK_DIR_ENV, str(tmp_path / "gate-work"))
    fake_docker.echo_job_time = False
    engine = OpenQuakeDocker(runner=fake_docker, which=lambda _: "/usr/bin/docker")
    result = gate.run(REPO_ROOT, engine=engine)
    assert result.status == GateStatus.FAILED
    assert any("differs from job.ini 50.0" in f for f in result.findings)
    assert (tmp_path / "gate-work" / "job.ini").is_file(), "work dir kept for artifact upload"


def test_hash_inputs_ignores_outputs_and_logs(tmp_path: Path) -> None:
    (tmp_path / "job.ini").write_text("[general]\n")
    before = oqd.hash_inputs(tmp_path)
    (tmp_path / "out").mkdir()
    (tmp_path / "out" / "hazard_curve-mean-PGA_1.csv").write_text("x")
    (tmp_path / "oq.log").write_text("y")
    assert oqd.hash_inputs(tmp_path) == before
    (tmp_path / "source_model.xml").write_text("<nrml/>")
    assert oqd.hash_inputs(tmp_path) != before


def test_load_classical_job_resolves_relative_paths(tmp_path: Path) -> None:
    job_file = tmp_path / "job.json"
    job_file.write_text(
        json.dumps(
            {
                "id": "j",
                "description": "d",
                "source_model_logic_tree": "in/smlt.xml",
                "gsim_logic_tree": "/abs/gslt.xml",
                "sites_csv": "in/sites.csv",
            }
        )
    )
    job = pipeline.load_classical_job(job_file)
    assert job.source_model_logic_tree == tmp_path / "in" / "smlt.xml"
    assert job.gsim_logic_tree == Path("/abs/gslt.xml")
    assert job.sites_csv == tmp_path / "in" / "sites.csv"
