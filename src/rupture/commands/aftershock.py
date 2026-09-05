"""``rupture aftershock`` — issue, refit, validate and serve operational aftershock forecasts.

    rupture aftershock forecast --mainshock us20002926 --horizon 7d --issue 2015-04-26T06:11:26Z
    rupture aftershock refit --sequence gorkha --through 30d
    rupture aftershock validate --sequence gorkha
    rupture aftershock serve --host 127.0.0.1 --port 8000

``forecast`` conditions on the committed sequence catalogue (or one given with
``--catalog``/``--region``), refits on the schedule if no persisted fit covers the issue time,
and prints the :class:`~rupture.domain.AftershockForecast`. ``refit`` is the executor of the
refit schedule (ADR-0028 item 3): it walks +0, 1, 3, 6, 12 h then daily to +30 d and fits every
cutoff that is due and not already on disk, which is what a cron entry or a scheduled job runs.
``validate`` runs the pseudo-prospective validation of a whole sequence and writes its report
under ``reports/aftershock/``. ``serve`` runs the HTTP service — by default the combined
application (``rupture.services.app``), which carries the avoided-loss surface too.

the output is a rate and a probability for a sequence.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer

from rupture.domain import Catalog, Region, parse_horizon
from rupture.pipelines.io import load_catalog, load_region, parse_utc
from rupture.services.aftershock.evaluation import (
    SequenceOutcome,
    render_markdown,
    validate_sequence,
    write_report,
)
from rupture.services.aftershock.forecaster import (
    DEFAULT_HORIZONS,
    AftershockForecaster,
    scheduled_fit_cutoff,
)
from rupture.services.aftershock.refit import run_refits
from rupture.services.aftershock.sequences import (
    ISSUE_OFFSETS,
    SEQUENCES,
    Mainshock,
    fits_dir,
    fixture_coverage_end,
    load_committed_fits,
    load_parent_region,
    load_sequence_catalog,
    mainshock_from_catalog,
    sequence_spec,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
EXIT_FAIL = 1

app = typer.Typer(
    help=(
        "Operational aftershock forecasts for a mainshock sequence. "
        "Rupture research output, not an operational alert."
    ),
    no_args_is_help=True,
)


@app.command("forecast")
def forecast(  # noqa: PLR0917 - typer options are keyword-only in practice
    mainshock: Annotated[
        str, typer.Option("--mainshock", help="ComCat event id of the mainshock.")
    ],
    horizon: Annotated[str, typer.Option("--horizon", help="1d | 7d | 30d (any <n>[h|d|w|y]).")],
    issue: Annotated[str, typer.Option("--issue", help="Issue time, UTC ISO 8601.")],
    sequence: Annotated[
        str | None,
        typer.Option("--sequence", help=f"Committed catalogue: {', '.join(sorted(SEQUENCES))}."),
    ] = None,
    catalog_dir: Annotated[
        Path | None, typer.Option("--catalog", help="A built catalogue directory instead.")
    ] = None,
    region_path: Annotated[
        Path | None, typer.Option("--region", help="Parent region file (with --catalog).")
    ] = None,
    n_simulations: Annotated[int, typer.Option("--simulations", min=1)] = 100,
    root: Annotated[Path, typer.Option("--root", help="Repository root.")] = REPO_ROOT,
    grid_out: Annotated[
        Path | None, typer.Option("--grid-out", help="Write the ForecastGrid JSON here.")
    ] = None,
) -> None:
    """Issue one aftershock forecast and print it as JSON."""
    issue_time = parse_utc(issue)
    horizon_delta = parse_horizon(horizon)
    engine = AftershockForecaster(n_simulations=n_simulations)

    if catalog_dir is not None:
        if region_path is None:
            typer.echo("--catalog needs --region (the parent region file)", err=True)
            raise typer.Exit(EXIT_FAIL)
        catalog = load_catalog(catalog_dir)
        parent = load_region(region_path)
        fits: dict[str, object] = {}
    else:
        name = sequence or _sequence_for_mainshock(mainshock)
        spec = sequence_spec(name)
        catalog = load_sequence_catalog(spec, root)
        parent = load_parent_region(spec, root)
        fits = dict(load_committed_fits(spec, root))

    try:
        shock: Mainshock = mainshock_from_catalog(catalog, mainshock)
    except (KeyError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAIL) from exc

    cutoff = scheduled_fit_cutoff(shock.origin_time, issue_time)
    persisted = fits.get(cutoff.isoformat())
    issuance = engine.forecast(
        catalog=catalog,
        parent_region=parent,
        mainshock=shock,
        issue_time=issue_time,
        horizon=horizon_delta,
        fit=persisted,  # type: ignore[arg-type]
    )
    typer.echo(json.dumps(issuance.forecast.model_dump(mode="json"), indent=2, sort_keys=True))
    if grid_out is not None:
        grid_out.parent.mkdir(parents=True, exist_ok=True)
        grid_out.write_text(
            json.dumps(issuance.grid.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        typer.echo(f"wrote {grid_out}", err=True)


@app.command("validate")
def validate(  # noqa: PLR0917 - typer options are keyword-only in practice
    sequence: Annotated[
        str, typer.Option("--sequence", help=f"One of: {', '.join(sorted(SEQUENCES))}.")
    ],
    root: Annotated[Path, typer.Option("--root", help="Repository root.")] = REPO_ROOT,
    out: Annotated[
        Path | None, typer.Option("--out", help="Report directory (default reports/aftershock).")
    ] = None,
    refit: Annotated[
        bool,
        typer.Option("--refit", help="Refit from the catalogue, not the committed fits."),
    ] = False,
    n_simulations: Annotated[int, typer.Option("--simulations", min=1)] = 100,
    csep_simulations: Annotated[int, typer.Option("--csep-simulations", min=1)] = 1000,
) -> None:
    """Run the pseudo-prospective validation of one sequence and write its report."""
    outcome: SequenceOutcome = validate_sequence(
        sequence,
        root,
        forecaster=AftershockForecaster(n_simulations=n_simulations),
        use_committed_fits=not refit,
        issue_offsets=ISSUE_OFFSETS,
        horizons=DEFAULT_HORIZONS,
        csep_simulations=csep_simulations,
    )
    json_path, md_path = write_report(outcome, out or (root / "reports" / "aftershock"))
    typer.echo(render_markdown(outcome))
    typer.echo(f"wrote {json_path}", err=True)
    typer.echo(f"wrote {md_path}", err=True)


@app.command("refit")
def refit(  # noqa: PLR0917 - typer options are keyword-only in practice
    sequence: Annotated[
        str | None,
        typer.Option("--sequence", help=f"Committed catalogue: {', '.join(sorted(SEQUENCES))}."),
    ] = None,
    catalog_dir: Annotated[
        Path | None, typer.Option("--catalog", help="A built catalogue directory instead.")
    ] = None,
    region_path: Annotated[
        Path | None, typer.Option("--region", help="Parent region file (with --catalog).")
    ] = None,
    mainshock: Annotated[
        str | None, typer.Option("--mainshock", help="Mainshock event id (with --catalog).")
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(
            "--out",
            help="Fits directory. Required with --catalog; overrides the committed one otherwise.",
        ),
    ] = None,
    through: Annotated[
        str, typer.Option("--through", help="Refit out to this elapsed time (e.g. 7d, 30d).")
    ] = "30d",
    now: Annotated[
        str | None,
        typer.Option("--now", help="Treat this UTC time as now; default the catalogue's end."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Refit cutoffs that already have a fit on disk.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="List what would be fitted and fit nothing.")
    ] = False,
    root: Annotated[Path, typer.Option("--root", help="Repository root.")] = REPO_ROOT,
) -> None:
    """Execute the refit schedule for a sequence, writing each fit as it completes.

    This is the thing a scheduler runs. The service does not refit inside a request (an EM fit
    takes tens of seconds and grows with the sequence); it re-reads the fits directory, so a fit
    written here is servable without a restart.
    """
    through_delta = parse_horizon(through)
    if catalog_dir is not None:
        catalog, parent, shock, fits_directory, coverage_end = _refit_inputs_from_catalog(
            catalog_dir, region_path, mainshock, out
        )
    else:
        catalog, parent, shock, fits_directory, coverage_end = _refit_inputs_from_sequence(
            sequence, root
        )
        if out is not None:
            fits_directory = out
    fits_directory.mkdir(parents=True, exist_ok=True)
    as_of = parse_utc(now) if now is not None else coverage_end
    typer.echo(
        f"refit: {shock.event_id} M{shock.magnitude:.1f} at {shock.origin_time.isoformat()}; "
        f"schedule to +{through}, now={as_of.isoformat()}, fits in {fits_directory}"
    )
    outcomes = run_refits(
        catalog=catalog,
        parent_region=parent,
        mainshock=shock,
        fits_dir=fits_directory,
        now=as_of,
        through=through_delta,
        coverage_end=coverage_end,
        force=force,
        dry_run=dry_run,
        on_outcome=lambda outcome: typer.echo(outcome.render()),
    )
    written = sum(1 for o in outcomes if o.status == "written")
    planned = sum(1 for o in outcomes if o.status == "planned")
    if dry_run:
        typer.echo(f"refit: dry run — {planned} of {len(outcomes)} scheduled cutoffs are due")
        return
    typer.echo(f"refit: wrote {written} of {len(outcomes)} scheduled cutoffs into {fits_directory}")


def _refit_inputs_from_sequence(
    name: str | None, root: Path
) -> tuple[Catalog, Region, Mainshock, Path, datetime]:
    if name is None:
        typer.echo("give --sequence, or --catalog with --region and --mainshock", err=True)
        raise typer.Exit(EXIT_FAIL)
    spec = sequence_spec(name)
    catalog = load_sequence_catalog(spec, root)
    parent = load_parent_region(spec, root)
    return (
        catalog,
        parent,
        mainshock_from_catalog(catalog, spec.mainshock.event_id),
        fits_dir(spec, root),
        fixture_coverage_end(spec, root),
    )


def _refit_inputs_from_catalog(
    catalog_dir: Path, region_path: Path | None, mainshock: str | None, out: Path | None
) -> tuple[Catalog, Region, Mainshock, Path, datetime]:
    if region_path is None or mainshock is None or out is None:
        typer.echo("--catalog needs --region, --mainshock and --out", err=True)
        raise typer.Exit(EXIT_FAIL)
    catalog = load_catalog(catalog_dir)
    try:
        shock = mainshock_from_catalog(catalog, mainshock)
    except (KeyError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAIL) from exc
    latest = max((event.origin_time for event in catalog.events), default=shock.origin_time)
    return catalog, load_region(region_path), shock, out, latest


@app.command("serve")
def serve(  # noqa: PLR0917 - typer options are keyword-only in practice
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    root: Annotated[Path, typer.Option("--root", help="Repository root.")] = REPO_ROOT,
    surface: Annotated[
        str,
        typer.Option(
            "--surface",
            help="'all' (avoided loss + aftershock, the deployment target) or 'aftershock'.",
        ),
    ] = "all",
    catalog_dir: Annotated[
        Path | None, typer.Option("--catalog", help="Serve this built catalogue as well.")
    ] = None,
    region_path: Annotated[
        Path | None, typer.Option("--region", help="Parent region file (with --catalog).")
    ] = None,
    name: Annotated[
        str | None, typer.Option("--name", help="Sequence name for --catalog (default its dir).")
    ] = None,
    fits: Annotated[
        Path | None, typer.Option("--fits", help="Fits directory for --catalog.")
    ] = None,
    allow_refit: Annotated[
        bool,
        typer.Option("--allow-refit", help="Let a request refit when no persisted fit covers it."),
    ] = False,
) -> None:
    """Serve the HTTP API. Needs an API key configured, or the routes answer 503.

    Keys come from ``RUPTURE_API_KEYS`` (both surfaces) or the per-surface variables. With
    ``--surface all`` this is exactly what the container image serves.
    """
    import uvicorn  # noqa: PLC0415 - only needed when actually serving

    from rupture.services.aftershock.service import SequenceSource  # noqa: PLC0415
    from rupture.services.aftershock.service import create_app as aftershock_app  # noqa: PLC0415
    from rupture.services.app import create_app as combined_app  # noqa: PLC0415

    sources: tuple[SequenceSource, ...] = ()
    if catalog_dir is not None:
        if region_path is None:
            typer.echo("--catalog needs --region (the parent region file)", err=True)
            raise typer.Exit(EXIT_FAIL)
        sources = (
            SequenceSource(
                id=name or catalog_dir.name,
                catalog_dir=catalog_dir,
                region_path=region_path,
                fits_dir=fits,
            ),
        )
    if surface not in {"all", "aftershock"}:
        typer.echo(f"unknown --surface {surface!r}; give 'all' or 'aftershock'", err=True)
        raise typer.Exit(EXIT_FAIL)
    if surface == "all":
        if sources or allow_refit:
            typer.echo(
                "--catalog/--allow-refit apply to --surface aftershock; for the combined app set "
                "RUPTURE_AFTERSHOCK_CATALOGS / RUPTURE_AFTERSHOCK_ALLOW_REFIT",
                err=True,
            )
            raise typer.Exit(EXIT_FAIL)
        uvicorn.run(combined_app(root=root), host=host, port=port)
        return
    uvicorn.run(
        aftershock_app(repo_root=root, sources=sources, allow_refit=allow_refit),
        host=host,
        port=port,
    )


def _sequence_for_mainshock(event_id: str) -> str:
    for name, spec in SEQUENCES.items():
        if spec.mainshock.event_id == event_id:
            return name
    known = ", ".join(f"{s.mainshock.event_id} ({n})" for n, s in sorted(SEQUENCES.items()))
    typer.echo(
        f"no committed catalogue for mainshock {event_id!r}; give --sequence or "
        f"--catalog/--region. Known: {known}",
        err=True,
    )
    raise typer.Exit(EXIT_FAIL)


HORIZON_CHOICES: tuple[timedelta, ...] = DEFAULT_HORIZONS


if __name__ == "__main__":  # pragma: no cover - `python -m rupture.commands.aftershock`
    app()
