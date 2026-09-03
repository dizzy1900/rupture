"""``validate-hazard``: the OpenQuake bundled demo runs in the pinned image and parses cleanly.

When the container cannot run here — Docker absent, or the amd64-only image on an arm64 host,
where the demo cannot finish under emulation — the gate is SKIPPED with the printed reason (never
a silent pass, never a failure blamed on the adapter). Otherwise it
runs ``demos/hazard/AreaSourceClassicalPSHA`` through :class:`OpenQuakeDocker`, parses the mean
hazard curves and checks: at least one site, PoE in [0, 1], PoE non-increasing with IML,
``investigation_time`` equal to the job's.

Set ``RUPTURE_HAZARD_WORK_DIR`` to keep the work directory (CI uploads it on failure); otherwise
a temporary directory is used and removed. Set ``RUPTURE_HAZARD_REQUIRE=1`` where a container run
is mandatory (the CI job, which runs on amd64): any such skip then becomes FAILED.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from rupture.adapters.hazard import DEFAULT_DEMO, OpenQuakeDocker, OpenQuakeError
from rupture.adapters.hazard.result_parser import check_curve_set, parse_job_ini
from rupture.pipelines import hazard as pipeline
from rupture.validation.result import GateResult, GateStatus

GATE = "validate-hazard"
WORK_DIR_ENV = "RUPTURE_HAZARD_WORK_DIR"
REQUIRE_ENV = "RUPTURE_HAZARD_REQUIRE"
"""Set to ``1`` (CI job hazard-integration) to turn a Docker-unavailable skip into a failure."""
CI_HINT = "CI job hazard-integration runs this demo"


def run(repo_root: Path, *, engine: OpenQuakeDocker | None = None) -> GateResult:
    eng = engine or OpenQuakeDocker()
    ok, reason = eng.available()
    if not ok:
        findings = [f"image pinned: {eng.image}", f"demo: {DEFAULT_DEMO}"]
        if required():
            findings.insert(0, f"cannot run the container here: {reason}")
            findings.append(f"{REQUIRE_ENV} is set: a skip is not acceptable here")
            return GateResult(name=GATE, status=GateStatus.FAILED, findings=findings)
        return GateResult(
            name=GATE,
            status=GateStatus.SKIPPED,
            reason=f"cannot run the container here: {reason}; {CI_HINT}",
            findings=findings,
        )

    keep = os.environ.get(WORK_DIR_ENV)
    if keep:
        work_dir = Path(keep).expanduser().resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        return _run_in(eng, work_dir)
    with tempfile.TemporaryDirectory(prefix="rupture-hazard-") as tmp:
        return _run_in(eng, Path(tmp))


def required() -> bool:
    """True when the environment demands a real container run (``RUPTURE_HAZARD_REQUIRE=1``)."""
    return os.environ.get(REQUIRE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _run_in(eng: OpenQuakeDocker, work_dir: Path) -> GateResult:
    findings = [f"image: {eng.image}", f"demo: {DEFAULT_DEMO}", f"work_dir: {work_dir}"]
    t0 = time.monotonic()
    try:
        eng.ensure_image()
        digest = eng.image_digest()
        findings.append(f"image digest: {digest or 'unknown'}")
        curve_set = pipeline.run_demo(eng, work_dir, DEFAULT_DEMO)
    except (OpenQuakeError, FileNotFoundError, ValueError) as exc:
        findings.append(f"error: {exc}")
        findings.extend(_log_tail(work_dir))
        return GateResult(name=GATE, status=GateStatus.FAILED, findings=findings)
    elapsed = time.monotonic() - t0
    findings.append(f"elapsed: {elapsed:.0f}s")
    findings.extend(pipeline.summary_lines(curve_set))

    expected = None
    job_ini = work_dir / "job.ini"
    if job_ini.is_file():
        raw = parse_job_ini(job_ini.read_text(encoding="utf-8")).get("investigation_time")
        try:
            expected = float(raw) if raw is not None else None
        except ValueError:
            findings.append(f"job.ini investigation_time not numeric: {raw!r}")
    problems = check_curve_set(curve_set, expected_investigation_time=expected)
    if problems:
        findings.extend(problems[:50])
        if len(problems) > 50:
            findings.append(f"... {len(problems) - 50} more")
        return GateResult(name=GATE, status=GateStatus.FAILED, findings=findings)
    findings.append("checks: >=1 site, PoE in [0,1], PoE non-increasing in IML, investigation_time")
    return GateResult(name=GATE, status=GateStatus.PASSED, findings=findings)


def _log_tail(work_dir: Path, n: int = 15) -> list[str]:
    out: list[str] = []
    for name in ("oq-copy-demo.log", "oq.log"):
        p = work_dir / name
        if p.is_file():
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            out.append(f"{name} (last {min(n, len(lines))} lines):")
            out.extend(f"  {ln}" for ln in lines[-n:])
    return out
