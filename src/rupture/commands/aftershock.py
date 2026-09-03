"""``rupture aftershock`` — issue and validate operational aftershock forecasts.

    rupture aftershock forecast --mainshock us20002926 --horizon 7d --issue 2015-04-26T06:11:26Z
    rupture aftershock validate --sequence gorkha
    rupture aftershock serve --host 127.0.0.1 --port 8000

``forecast`` conditions on the committed sequence catalogue (or one given with
``--catalog``/``--region``), refits on the schedule if no persisted fit covers the issue time,
and prints the :class:`~rupture.domain.AftershockForecast`. ``validate`` runs the
pseudo-prospective validation of a whole sequence and writes its report under
``reports/aftershock/``.

rupture does not predict earthquakes: the output is a rate and a probability for a sequence.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from rupture.domain import parse_horizon
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
from rupture.services.aftershock.sequences import (
    ISSUE_OFFSETS,
    SEQUENCES,
    Mainshock,
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
        "rupture does not predict earthquakes."
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


@app.command("serve")
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    root: Annotated[Path, typer.Option("--root", help="Repository root.")] = REPO_ROOT,
) -> None:
    """Serve the forecast API. Needs RUPTURE_AFTERSHOCK_API_KEY set, or it refuses the route."""
    import uvicorn  # noqa: PLC0415 - only needed when actually serving

    from rupture.services.aftershock.service import create_app  # noqa: PLC0415

    uvicorn.run(create_app(repo_root=root), host=host, port=port)


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
