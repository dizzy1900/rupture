"""Shared paths and a fake ``docker`` runner for the offline hazard tests."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "hazard"
QA_CASE_01 = FIXTURES / "qa_classical_case_01"
QA_CASE_02 = FIXTURES / "qa_classical_case_02"
DEMO = FIXTURES / "demo_AreaSourceClassicalPSHA"


@pytest.fixture
def no_docker_on_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An empty PATH directory so ``shutil.which('docker')`` is None."""
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.delenv("RUPTURE_OPENQUAKE_IMAGE", raising=False)
    monkeypatch.delenv("RUPTURE_HAZARD_WORK_DIR", raising=False)
    return empty


@dataclass
class FakeDocker:
    """Records ``docker`` invocations; simulates the container by writing exports on the host.

    ``docker info`` succeeds; ``docker image inspect`` reports a digest; ``docker run`` copies
    the QA case_01 expected CSVs into ``<work>/out`` so the parser sees real engine output.
    Like the engine, it writes the job's ``investigation_time`` into the export header
    (``echo_job_time``); set it to False to simulate a mismatch.
    """

    calls: list[list[str]] = field(default_factory=list)
    run_exit: int = 0
    export_from: Path = QA_CASE_01 / "expected"
    echo_job_time: bool = True

    def __call__(self, argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(argv))
        sub = argv[1] if len(argv) > 1 else ""
        if sub == "info":
            return subprocess.CompletedProcess(argv, 0, "28.0.0\n", "")
        if sub == "image":
            return subprocess.CompletedProcess(
                argv, 0, "openquake/engine@sha256:" + "0" * 64 + "\n", ""
            )
        if sub == "run":
            host_dir = Path(argv[argv.index("-v") + 1].split(":", 1)[0])
            script = argv[-1]
            if self.run_exit != 0:
                return subprocess.CompletedProcess(argv, self.run_exit, "", "boom\n")
            if "cp -R" in script:  # demo copy step
                for p in DEMO.iterdir():
                    if p.name != "provenance.json":
                        shutil.copyfile(p, host_dir / p.name)
                (host_dir / ".demo_source").write_text("/opt/openquake/demos/hazard/X\n")
            else:
                out = host_dir / "out"
                out.mkdir(exist_ok=True)
                job_time = _investigation_time(host_dir / "job.ini")
                for p in self.export_from.glob("hazard_curve-*.csv"):
                    # the engine names exports hazard_curve-<kind>-<IMT>_<calc_id>.csv
                    imt = p.stem.split("hazard_curve-", 1)[1]
                    text = p.read_text()
                    if self.echo_job_time and job_time is not None:
                        text = re.sub(
                            r"investigation_time=[0-9.eE+-]+",
                            f"investigation_time={job_time}",
                            text,
                            count=1,
                        )
                    (out / f"hazard_curve-mean-{imt}_1.csv").write_text(text)
            return subprocess.CompletedProcess(argv, 0, "Calculation 1 finished correctly\n", "")
        return subprocess.CompletedProcess(argv, 0, "", "")


@pytest.fixture
def fake_docker() -> FakeDocker:
    return FakeDocker()


def _investigation_time(job_ini: Path) -> str | None:
    if not job_ini.is_file():
        return None
    for line in job_ini.read_text().splitlines():
        if line.strip().startswith("investigation_time"):
            return line.split("=", 1)[1].strip()
    return None
