"""OpenQuake engine driven through the pinned Docker image (ADR-0011, ADR-0030).

rupture never imports ``openquake.*``. Jobs are rendered to a work directory that is bind-mounted
into the container at ``/work``; the container runs ``oq engine --run`` and ``oq export`` and the
CSV exports are parsed back on the host. Everything Docker-related goes through the ``docker``
CLI via :mod:`subprocess`; the runner is injectable so the staging and parsing paths are unit
tested offline.

Image facts this module relies on (see ``docs/HAZARD.md`` for verified vs assumed):

- the image runs as user ``openquake`` (uid 1000) with ``HOME=/home/openquake``, and its
  ``ENTRYPOINT`` is the relative ``./oq-start.sh``, which starts the dbserver and then ``exec``s
  the command. Hence no ``-w`` flag (it would break the relative entrypoint) and absolute
  ``/work/...`` paths everywhere;
- the work directory is made world-writable and the container runs with ``umask 000`` so the
  files it writes can be read and removed by the host user;
- the demos are installed as setuptools ``data_files`` relative to the venv prefix, i.e.
  ``/opt/openquake/demos`` — assumed; the runner falls back to ``find`` inside the image.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from rupture import __version__
from rupture.adapters.hazard import job_builder, result_parser
from rupture.domain import HazardCurveSet, Provenance, sha256_hex, utc_now
from rupture.ports.hazard_engine import ClassicalPSHAJob, ScenarioGroundMotionJob

ENGINE_ID = "openquake.engine"
ENGINE_VERSION = "3.26.2"
DEFAULT_IMAGE = f"openquake/engine:{ENGINE_VERSION}"
IMAGE_ENV = "RUPTURE_OPENQUAKE_IMAGE"
DEMOS_DIR_ENV = "RUPTURE_OPENQUAKE_DEMOS_DIR"
ALLOW_EMULATION_ENV = "RUPTURE_OPENQUAKE_ALLOW_EMULATION"
"""Set to ``1`` to run even when the image architecture differs from the host's.

``openquake/engine`` publishes a single-platform ``linux/amd64`` image. On an arm64 host
(Apple Silicon) Docker runs it under emulation, where the bundled demo is far slower than the
run timeout allows. The engine is not at fault and neither is the adapter, so the gate reports
this as a skip with the reason printed rather than a failure; CI runs on amd64 and executes the
demo for real. Set this variable to attempt the emulated run anyway (expect hours).
"""
DEFAULT_DEMOS_DIR = "/opt/openquake/demos"
DEFAULT_DEMO = "hazard/AreaSourceClassicalPSHA"
CONTAINER_WORK = "/work"
LOG_NAME = "oq.log"
DEMO_SOURCE_MARKER = ".demo_source"
DEMO_FILES_MARKER = ".demo_files"
ADAPTER_VERSION = __version__
LICENCE = "AGPL-3.0 (engine); inputs per source model"

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class OpenQuakeError(RuntimeError):
    """A Docker or engine invocation failed. The message carries the tail of the log."""


class OpenQuakeDocker:
    """The ``HazardEngine`` port backed by ``openquake/engine`` in Docker."""

    engine_id = ENGINE_ID
    engine_version = ENGINE_VERSION

    def __init__(
        self,
        image: str | None = None,
        *,
        docker: str = "docker",
        run_timeout_s: float = 3600.0,
        pull_timeout_s: float = 1800.0,
        runner: Runner = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
    ) -> None:
        self.image = image or os.environ.get(IMAGE_ENV) or DEFAULT_IMAGE
        self.docker = docker
        self.run_timeout_s = run_timeout_s
        self.pull_timeout_s = pull_timeout_s
        self._run = runner
        self._which = which

    # ------------------------------------------------------------------ availability
    def available(self) -> tuple[bool, str]:
        """``(True, '')`` when the docker CLI exists and the daemon answers ``docker info``."""
        if self._which(self.docker) is None:
            return False, f"'{self.docker}' binary not found on PATH"
        try:
            proc = self._run(
                [self.docker, "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"'{self.docker} info' failed: {exc}"
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()
            reason = detail[0] if detail else f"exit {proc.returncode}"
            return False, f"docker daemon not reachable: {reason}"
        return self._platform_ok()

    def _docker_arch(self, args: list[str]) -> str | None:
        """Architecture reported by a docker format query, or None when it cannot be read."""
        try:
            proc = self._run(
                [self.docker, *args], capture_output=True, text=True, timeout=60, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        arch = (proc.stdout or "").strip()
        return arch or None

    def _platform_ok(self) -> tuple[bool, str]:
        """Refuse an emulated run: the image is amd64-only and the demo cannot finish under QEMU.

        Only decides when both architectures are known and the image is already present locally;
        an unknown architecture never blocks, so the run proceeds and reports its own outcome.
        """
        if os.environ.get(ALLOW_EMULATION_ENV, "").strip().lower() in {"1", "true", "yes"}:
            return True, ""
        host = self._docker_arch(["version", "--format", "{{.Server.Arch}}"])
        image = self._docker_arch(["image", "inspect", "--format", "{{.Architecture}}", self.image])
        if host is None or image is None or host == image:
            return True, ""
        return False, (
            f"image {self.image} is {image}-only and this host is {host}, so it would run under "
            f"emulation, where the demo exceeds the {self.run_timeout_s:.0f}s run timeout; "
            f"set {ALLOW_EMULATION_ENV}=1 to attempt it anyway"
        )

    def image_digest(self) -> str | None:
        """``repo@sha256:...`` of the local image, or ``None`` when not present locally."""
        try:
            proc = self._run(
                [
                    self.docker,
                    "image",
                    "inspect",
                    "--format",
                    "{{index .RepoDigests 0}}",
                    self.image,
                ],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if proc.returncode != 0:
            return None
        digest = proc.stdout.strip()
        return digest or None

    def ensure_image(self) -> None:
        """Pull the pinned image unless it is already present locally."""
        if self.image_digest() is not None:
            return
        try:
            proc = self._run(
                [self.docker, "pull", self.image],
                capture_output=True,
                text=True,
                timeout=self.pull_timeout_s,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            msg = f"docker pull {self.image} failed: {exc}"
            raise OpenQuakeError(msg) from exc
        if proc.returncode != 0:
            msg = f"docker pull {self.image} failed: {(proc.stderr or proc.stdout).strip()[-800:]}"
            raise OpenQuakeError(msg)

    # ------------------------------------------------------------------ port methods
    def run_classical(self, job: ClassicalPSHAJob, work_dir: Path) -> HazardCurveSet:
        """Render, copy inputs, run ``oq engine`` + ``oq export hcurves``, parse mean curves."""
        staged = self._stage(job, work_dir, job_builder.classical_job_ini(job))
        job_hash = hash_inputs(work_dir, staged)
        self._run_job_dir(work_dir, export_keys=("hcurves",))
        return self._collect_curves(
            work_dir,
            set_id=job.id,
            source_model_id=job.source_model_logic_tree.stem,
            gsim_logic_tree_id=job.gsim_logic_tree.stem,
            job_hash=job_hash,
            notes=f"classical PSHA job {job.id!r}",
        )

    def run_scenario(self, job: ScenarioGroundMotionJob, work_dir: Path) -> Path:
        """Render and run a scenario; returns the directory holding the ``gmf_data`` CSV export.

        Implemented against the manual; not exercised by any test or CI job yet (docs/HAZARD.md).
        """
        self._stage(job, work_dir, job_builder.scenario_job_ini(job))
        return self._run_job_dir(work_dir, export_keys=("gmf_data",))

    # ------------------------------------------------------------------ demo
    def run_bundled_demo(self, work_dir: Path, demo: str = DEFAULT_DEMO) -> HazardCurveSet:
        """Copy a demo shipped inside the image into ``work_dir``, run it, parse the curves."""
        if "/" not in demo or ".." in demo:
            msg = f"demo must look like 'hazard/<Name>', got {demo!r}"
            raise ValueError(msg)
        work_dir.mkdir(parents=True, exist_ok=True)
        _make_shared(work_dir, work_dir / "oq-copy-demo.log")
        self._copy_demo(work_dir, demo)
        job_ini = work_dir / job_builder.JOB_INI
        if not job_ini.is_file():
            msg = f"demo {demo!r} was not copied out of {self.image}; see {work_dir / LOG_NAME}"
            raise OpenQuakeError(msg)
        job_hash = hash_inputs(work_dir, _demo_files(work_dir))
        params = result_parser.parse_job_ini(job_ini.read_text(encoding="utf-8"))
        smlt = params.get("source_model_logic_tree_file", "source_model_logic_tree.xml")
        gslt = params.get("gsim_logic_tree_file") or params.get("gsim")
        self._run_job_dir(work_dir, export_keys=("hcurves",))
        return self._collect_curves(
            work_dir,
            set_id=f"openquake-demo-{demo.replace('/', '-')}",
            source_model_id=Path(smlt).stem,
            gsim_logic_tree_id=Path(gslt).stem if gslt else None,
            job_hash=job_hash,
            notes=f"OpenQuake bundled demo {demo!r} (labelled demo; not a rupture region)",
        )

    def _copy_demo(self, work_dir: Path, demo: str) -> None:
        demos_dir = os.environ.get(DEMOS_DIR_ENV) or DEFAULT_DEMOS_DIR
        expected = shlex.quote(f"{demos_dir.rstrip('/')}/{demo}")
        pattern = shlex.quote(f"*/demos/{demo}/job.ini")
        q_demo = shlex.quote(demo)
        script = (
            "set -e; umask 000; "
            f"d={expected}; "
            'if [ ! -f "$d/job.ini" ]; then '
            f'f=$(find / -path {pattern} -not -path "/proc/*" 2>/dev/null | head -n 1); '
            'd=$(dirname "${f:-/nonexistent/x}"); '
            "fi; "
            f'[ -f "$d/job.ini" ] || {{ echo "demo {q_demo} not found in image" >&2; exit 3; }}; '
            f'cp -R "$d"/. {CONTAINER_WORK}/; '
            f'echo "$d" > {CONTAINER_WORK}/{DEMO_SOURCE_MARKER}; '
            f'(cd "$d" && find . -type f | sed "s|^\\./||" | sort) '
            f"> {CONTAINER_WORK}/{DEMO_FILES_MARKER}"
        )
        self._docker_bash(work_dir, script, log_name="oq-copy-demo.log", timeout_s=600.0)

    # ------------------------------------------------------------------ internals
    def _stage(
        self, job: ClassicalPSHAJob | ScenarioGroundMotionJob, work_dir: Path, ini_text: str
    ) -> list[str]:
        """Write ``job.ini`` and copy the inputs; returns the staged file names (hash list)."""
        work_dir.mkdir(parents=True, exist_ok=True)
        inputs = job_builder.referenced_inputs(job)
        staged = [job_builder.JOB_INI]
        for name, src in inputs.items():
            if not src.is_file():
                msg = f"input file for {name!r} does not exist: {src}"
                raise FileNotFoundError(msg)
            shutil.copyfile(src, work_dir / name)
            staged.append(name)
        if isinstance(job, ClassicalPSHAJob):
            staged.extend(_copy_source_models(job.source_model_logic_tree, work_dir))
        (work_dir / job_builder.JOB_INI).write_text(ini_text, encoding="utf-8")
        _make_shared(work_dir, work_dir / LOG_NAME)
        return staged

    def _run_job_dir(self, work_dir: Path, *, export_keys: tuple[str, ...]) -> Path:
        out_dir = work_dir / job_builder.EXPORT_SUBDIR
        shutil.rmtree(out_dir, ignore_errors=True)  # never parse a previous run's exports
        exports = "; ".join(
            f"oq export {shlex.quote(key)} -e csv -d {CONTAINER_WORK}/{job_builder.EXPORT_SUBDIR}"
            for key in export_keys
        )
        script = (
            "set -e; umask 000; "
            f"mkdir -p {CONTAINER_WORK}/{job_builder.EXPORT_SUBDIR}; "
            f"oq engine --run {CONTAINER_WORK}/{job_builder.JOB_INI}; "
            f"{exports}"
        )
        self._docker_bash(work_dir, script, log_name=LOG_NAME, timeout_s=self.run_timeout_s)
        return out_dir

    def _docker_bash(
        self, work_dir: Path, script: str, *, log_name: str, timeout_s: float
    ) -> subprocess.CompletedProcess[str]:
        name = f"rupture-oq-{uuid.uuid4().hex[:12]}"
        argv = [
            self.docker,
            "run",
            "--rm",
            "--name",
            name,
            "-v",
            f"{work_dir.resolve()}:{CONTAINER_WORK}",
            self.image,
            "bash",
            "-c",
            script,
        ]
        log_path = work_dir / log_name
        try:
            proc = self._run(argv, capture_output=True, text=True, timeout=timeout_s, check=False)
        except subprocess.TimeoutExpired as exc:
            self._run(
                [self.docker, "kill", name], capture_output=True, text=True, timeout=60, check=False
            )
            _append_log(log_path, argv, exc.stdout, exc.stderr)
            msg = f"OpenQuake container {name} exceeded {timeout_s:.0f}s and was killed"
            raise OpenQuakeError(msg) from exc
        _append_log(log_path, argv, proc.stdout, proc.stderr)
        if proc.returncode != 0:
            tail = "\n".join(((proc.stderr or "") + "\n" + (proc.stdout or "")).splitlines()[-25:])
            msg = f"docker run {self.image} exited {proc.returncode}; log: {log_path}\n{tail}"
            raise OpenQuakeError(msg)
        return proc

    def _collect_curves(
        self,
        work_dir: Path,
        *,
        set_id: str,
        source_model_id: str,
        gsim_logic_tree_id: str | None,
        job_hash: str,
        notes: str,
    ) -> HazardCurveSet:
        out_dir = work_dir / job_builder.EXPORT_SUBDIR
        paths = sorted(out_dir.glob(result_parser.HAZARD_CURVE_GLOB))
        if not paths:
            msg = (
                f"no {result_parser.HAZARD_CURVE_GLOB} exported into {out_dir}; "
                f"see {work_dir / LOG_NAME}"
            )
            raise OpenQuakeError(msg)
        texts = {p.name: p.read_text(encoding="utf-8") for p in paths}
        payload_hash = hashlib.sha256()
        for name in sorted(texts):
            payload_hash.update(name.encode("utf-8") + b"\0" + texts[name].encode("utf-8") + b"\0")
        digest = self.image_digest()
        params = result_parser.parse_job_ini(
            (work_dir / job_builder.JOB_INI).read_text(encoding="utf-8")
        )
        expected_time = params.get("investigation_time")
        now = utc_now()
        provenance = Provenance(
            source=ENGINE_ID,
            source_url=f"docker://{digest or self.image}",
            retrieved_at=now,
            sha256=payload_hash.hexdigest(),
            licence=LICENCE,
            adapter_version=ADAPTER_VERSION,
            notes=f"image {self.image}; exports {[p.name for p in paths]}",
        )
        curve_set = result_parser.build_curve_set(
            texts,
            set_id=set_id,
            source_model_id=source_model_id,
            gsim_logic_tree_id=gsim_logic_tree_id,
            job_hash=job_hash,
            computed_at=now,
            provenance=provenance,
            engine_version_fallback=self.engine_version,
            notes=notes,
        )
        if expected_time is not None:
            try:
                expected = float(expected_time)
            except ValueError:
                expected = None
            if expected is not None and abs(curve_set.investigation_time_years - expected) > 1e-9:
                msg = (
                    f"exported investigation_time {curve_set.investigation_time_years} differs "
                    f"from job.ini {expected}"
                )
                raise OpenQuakeError(msg)
        return curve_set


# ---------------------------------------------------------------------- helpers
def hash_inputs(work_dir: Path, names: Iterable[str]) -> str:
    """sha256 over an explicit list of input files (relative name + bytes, sorted, de-duplicated).

    Only the files that define the calculation are hashed — ``job.ini``, the referenced inputs
    and the source models the logic tree names — never anything else that happens to sit in the
    work directory (exports, logs, a previous run's ``hazard-curve-set.json``), so re-running the
    same job in the same directory yields the same hash.
    """
    h = hashlib.sha256()
    for rel in sorted(set(names)):
        path = work_dir / rel
        if not path.is_file():
            msg = f"input to hash is missing: {path}"
            raise FileNotFoundError(msg)
        h.update(rel.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def _demo_files(work_dir: Path) -> list[str]:
    """The file list the demo copy step recorded (relative names, one per line)."""
    marker = work_dir / DEMO_FILES_MARKER
    if not marker.is_file():
        msg = f"demo copy step did not record its file list ({marker})"
        raise OpenQuakeError(msg)
    names = [ln.strip() for ln in marker.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if job_builder.JOB_INI not in names:
        msg = f"demo file list has no {job_builder.JOB_INI}: {names}"
        raise OpenQuakeError(msg)
    return names


def _copy_source_models(logic_tree: Path, work_dir: Path) -> list[str]:
    """Copy the source-model files a logic tree names, keeping their relative names."""
    names = job_builder.referenced_source_models(logic_tree.read_text(encoding="utf-8"))
    for name in names:
        src = logic_tree.parent / name
        if not src.is_file():
            msg = f"source model {name!r} named by {logic_tree.name} does not exist: {src}"
            raise FileNotFoundError(msg)
        dst = work_dir / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return names


def _make_shared(work_dir: Path, log_path: Path) -> None:
    """Let the container's uid 1000 write into a directory owned by the host user.

    A failing ``chmod`` is not fatal (the run may still work, e.g. under Docker Desktop's uid
    mapping) but it is recorded in the run log so a later permission error can be attributed.
    """
    failures: list[str] = []
    for p in (work_dir, *work_dir.rglob("*")):
        try:
            p.chmod(0o777 if p.is_dir() else 0o666)
        except OSError as exc:  # pragma: no cover - platform specific
            failures.append(f"{p}: {exc}")
    if failures:  # pragma: no cover - platform specific
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write("chmod for the container user failed (run may hit permission errors):\n")
            fh.writelines(f"  {f}\n" for f in failures)


def _append_log(path: Path, argv: list[str], stdout: Any, stderr: Any) -> None:
    def _text(v: Any) -> str:
        if v is None:
            return ""
        return v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)

    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"$ {shlex.join(argv)}\n")
        fh.write(_text(stdout))
        if not _text(stdout).endswith("\n"):
            fh.write("\n")
        fh.write("--- stderr ---\n")
        fh.write(_text(stderr))
        fh.write("\n")


def job_hash_of(job: ClassicalPSHAJob) -> str:
    """Hash of the job model alone (no files), for logs and manifests."""
    return sha256_hex(job.canonical_json())
