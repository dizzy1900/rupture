"""`rupture hazard ...` — OpenQuake hazard runs in the pinned Docker image.

Exit codes: 0 ran; 1 failed; 3 skipped because Docker is not available (the reason is printed).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Annotated

import typer

from rupture.adapters.hazard import DEFAULT_DEMO, OpenQuakeDocker, OpenQuakeError
from rupture.pipelines import hazard as pipeline

EXIT_FAILED = 1
EXIT_SKIPPED = 3

app = typer.Typer(help="OpenQuake hazard runs (pinned Docker image).", no_args_is_help=True)

WorkDirOpt = Annotated[
    Path | None,
    typer.Option("--work-dir", help="Directory for job.ini, inputs, exports and oq.log."),
]


def _engine_or_skip() -> OpenQuakeDocker:
    engine = OpenQuakeDocker()
    ok, reason = engine.available()
    if not ok:
        typer.echo(f"SKIPPED: Docker not available: {reason}", err=True)
        typer.echo(
            "CI job hazard-integration runs the OpenQuake demo; see docs/HAZARD.md", err=True
        )
        raise typer.Exit(EXIT_SKIPPED)
    return engine


def _work_dir(given: Path | None, prefix: str) -> Path:
    if given is not None:
        given.mkdir(parents=True, exist_ok=True)
        return given
    return Path(tempfile.mkdtemp(prefix=prefix))


@app.command("check")
def check() -> None:
    """Report whether the OpenQuake image can run here (docker CLI + daemon), and which image."""
    engine = OpenQuakeDocker()
    ok, reason = engine.available()
    typer.echo(f"image: {engine.image}")
    if ok:
        digest = engine.image_digest()
        typer.echo(
            f"docker: available; image {'present: ' + digest if digest else 'not pulled yet'}"
        )
        return
    typer.echo(f"docker: not available: {reason}")
    raise typer.Exit(EXIT_SKIPPED)


@app.command("demo")
def demo(
    work_dir: WorkDirOpt = None,
    demo: Annotated[
        str, typer.Option(help="Demo path inside the image's demos/ tree.")
    ] = DEFAULT_DEMO,
) -> None:
    """Run an OpenQuake bundled demo in the pinned image and parse its mean hazard curves."""
    engine = _engine_or_skip()
    target = _work_dir(work_dir, "rupture-oq-demo-")
    typer.echo(f"work_dir: {target}")
    try:
        engine.ensure_image()
        curve_set = pipeline.run_demo(engine, target, demo)
    except (OpenQuakeError, FileNotFoundError, ValueError) as exc:
        typer.echo(f"FAILED: {exc}", err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    for line in pipeline.summary_lines(curve_set):
        typer.echo(line)
    typer.echo(f"wrote {target / pipeline.CURVE_SET_FILE}")


@app.command("classical")
def classical(
    job: Annotated[Path, typer.Option("--job", help="ClassicalPSHAJob as JSON.")],
    work_dir: WorkDirOpt = None,
) -> None:
    """Run a classical PSHA job (ClassicalPSHAJob JSON) in the pinned image."""
    engine = _engine_or_skip()
    try:
        job_model = pipeline.load_classical_job(job)
    except (OSError, ValueError) as exc:
        typer.echo(f"cannot load job {job}: {exc}", err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    target = _work_dir(work_dir, "rupture-oq-classical-")
    typer.echo(f"work_dir: {target}")
    try:
        engine.ensure_image()
        curve_set = pipeline.run_classical(engine, job_model, target)
    except (OpenQuakeError, FileNotFoundError, ValueError) as exc:
        typer.echo(f"FAILED: {exc}", err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    for line in pipeline.summary_lines(curve_set):
        typer.echo(line)
    typer.echo(f"wrote {target / pipeline.CURVE_SET_FILE}")
