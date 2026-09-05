"""`rupture forecast ...` — fit the ETAS baseline and issue forecast grids.

``fit`` uses only events with ``origin_time < cutoff``;
``issue`` uses only events with ``origin_time < issue_time`` and a fit whose cutoff is not after
the issue time. Any other input raises ``LeakageError`` and exits non-zero.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from rupture.adapters.forecasting.etas_mizrahi import MODEL_ID, MizrahiETAS, load_fit
from rupture.adapters.storage.run_log import JsonlTracker
from rupture.adapters.storage.zarr_store import ZarrGridStore
from rupture.commands._stub import EXIT_NOT_IMPLEMENTED
from rupture.domain import parse_horizon
from rupture.pipelines import io
from rupture.pipelines.fit_etas import fit_etas
from rupture.pipelines.run_forecast import issue_forecast

app = typer.Typer(help="Fit models and issue forecasts.", no_args_is_help=True)

MODELS = {"etas": MODEL_ID, MODEL_ID: MODEL_ID}


def _model(
    name: str, *, auxiliary_years: float, max_iterations: int = 200, max_seconds: float = 1800.0
) -> MizrahiETAS:
    if name not in MODELS:
        typer.echo(
            f"rupture forecast: model {name!r} is not available; Prompt 1 ships {MODEL_ID} only",
            err=True,
        )
        raise typer.Exit(EXIT_NOT_IMPLEMENTED)
    return MizrahiETAS(
        auxiliary_years=auxiliary_years,
        max_iterations=max_iterations,
        max_seconds=max_seconds,
    )


def _catalog_path(catalog: Path | None, data_dir: Path, region_id: str) -> Path:
    return catalog if catalog is not None else data_dir / "catalogs" / region_id


@app.command("fit")
def fit(  # noqa: PLR0917 - typer options
    region: Annotated[str, typer.Option("--region", help="Region id (data/regions/<id>).")],
    cutoff: Annotated[
        str, typer.Option("--cutoff", help="Hard cutoff, ISO 8601 UTC; only earlier events.")
    ],
    model: Annotated[str, typer.Option("--model", help="Model: etas.")] = "etas",
    catalog: Annotated[
        Path | None,
        typer.Option("--catalog", help="Catalogue dir (events.parquet + catalog.meta.json)."),
    ] = None,
    mc: Annotated[
        float | None,
        typer.Option("--mc", help="Explicit Mc when neither region nor catalogue carries one."),
    ] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir", help="Data root.")] = Path("data"),
    baselines: Annotated[
        Path, typer.Option("--baselines", help="Where baselines/etas/<region>/ is written.")
    ] = Path("baselines"),
    auxiliary_years: Annotated[
        float, typer.Option("--auxiliary-years", help="Auxiliary window length in years.")
    ] = 2.0,
    max_iterations: Annotated[
        int,
        typer.Option(
            "--max-iterations",
            help="EM iteration cap; the fit stops and is "
            "persisted with converged=false when it is hit.",
        ),
    ] = 200,
    max_seconds: Annotated[
        float,
        typer.Option(
            "--max-seconds",
            help="EM wall-clock cap in seconds; large "
            "catalogues (California at its Mc) need hours, not the 1800 s default.",
        ),
    ] = 1800.0,
) -> None:
    """Fit on events with origin_time < cutoff; persist FitResult + diagnostics under baselines/."""
    m = _model(
        model,
        auxiliary_years=auxiliary_years,
        max_iterations=max_iterations,
        max_seconds=max_seconds,
    )
    cut = io.parse_utc(cutoff)
    region_obj = io.load_region(data_dir / "regions" / region)
    cat = io.load_catalog(_catalog_path(catalog, data_dir, region))
    tracker = JsonlTracker(JsonlTracker.default_path(data_dir, region))
    result = fit_etas(
        cat, region_obj, cut, baselines_dir=baselines, mc=mc, model=m, tracker=tracker
    )
    typer.echo(
        f"fit {result.model_id} {result.region_id} cutoff={result.fit_cutoff.isoformat()} "
        f"n_events={result.n_events} mc={result.mc} converged={result.converged} "
        f"iterations={result.diagnostics.get('iterations')} "
        f"branching_ratio={result.diagnostics.get('branching_ratio')} "
        f"snapshot={result.parameter_snapshot_hash[:12]}"
    )
    for k, v in result.parameters.items():
        typer.echo(f"  {k} = {v:.6f}")
    if not result.converged:
        typer.echo("fit did not converge; it must not be used", err=True)
        raise typer.Exit(1)


@app.command("issue")
def issue(  # noqa: PLR0917 - typer options
    region: Annotated[str, typer.Option("--region", help="Region id.")],
    issue: Annotated[str, typer.Option("--issue", help="Issue time, ISO 8601 UTC.")],
    horizon: Annotated[str, typer.Option("--horizon", help="Horizon, e.g. 30d, 7d, 1d.")] = "30d",
    model: Annotated[str, typer.Option("--model", help="Model: etas.")] = "etas",
    catalog: Annotated[Path | None, typer.Option("--catalog", help="Catalogue dir.")] = None,
    n_simulations: Annotated[
        int, typer.Option("--n-simulations", help="Stochastic continuations to average.")
    ] = 100,
    seed: Annotated[int | None, typer.Option("--seed", help="numpy global seed.")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir", help="Data root.")] = Path("data"),
    baselines: Annotated[Path, typer.Option("--baselines", help="Baselines root.")] = Path(
        "baselines"
    ),
) -> None:
    """Issue a ForecastGrid at --issue from the persisted fit; store it as zarr + STAC."""
    issue_time = io.parse_utc(issue)
    region_obj = io.load_region(data_dir / "regions" / region)
    cat = io.load_catalog(_catalog_path(catalog, data_dir, region))
    m = _model(model, auxiliary_years=2.0)
    m.load_fit(load_fit(baselines, region), region_obj)
    store = ZarrGridStore(data_dir / "forecasts")
    tracker = JsonlTracker(JsonlTracker.default_path(data_dir, region))
    grid = issue_forecast(
        m,
        cat,
        issue_time,
        parse_horizon(horizon),
        n_simulations=n_simulations,
        seed=seed,
        store=store,
        tracker=tracker,
    )
    typer.echo(
        f"issued {grid.id}: {len(grid.cell_origins)} cells x {len(grid.magnitude_bin_edges)} "
        f"bins, total expected {grid.total_expected():.4f} events "
        f"(M >= {grid.magnitude_bin_edges[0]}), stored under {store.path_for(grid)}"
    )
