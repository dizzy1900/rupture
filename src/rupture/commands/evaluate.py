"""`rupture evaluate ...` — CSEP consistency tests and the pseudo-prospective schedule.

rupture does not predict earthquakes; these commands score the rate forecasts it issues.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from rupture.adapters.evaluation.pycsep import PyCSEPEvaluator
from rupture.adapters.forecasting.etas_mizrahi import MODEL_ID, MizrahiETAS
from rupture.adapters.storage.run_log import JsonlTracker
from rupture.adapters.storage.zarr_store import ZarrGridStore
from rupture.commands._stub import EXIT_NOT_IMPLEMENTED
from rupture.domain import Region, TestName, parse_horizon
from rupture.pipelines import io
from rupture.pipelines.evaluate import DEFAULT_TESTS, evaluate_forecast
from rupture.pipelines.schedule import run_schedule

app = typer.Typer(help="Evaluate forecasts with CSEP-style tests.", no_args_is_help=True)


def _tests(text: str) -> list[TestName]:
    names = [t.strip().upper() for t in text.split(",") if t.strip()]
    try:
        return [TestName(n) for n in names]
    except ValueError as exc:
        typer.echo(f"rupture evaluate: unknown test in {text!r} ({exc})", err=True)
        raise typer.Exit(1) from exc


def _region_if_present(data_dir: Path, region_id: str) -> Region | None:
    path = data_dir / "regions" / region_id / io.REGION_FILE
    if not path.exists():
        typer.echo(f"note: no region file at {path}; depth filter not applied", err=True)
        return None
    return io.load_region(path)


@app.command("run")
def run(  # noqa: PLR0917 - typer options
    forecast: Annotated[str, typer.Option("--forecast", help="Forecast id (zarr store).")],
    catalog: Annotated[Path | None, typer.Option("--catalog", help="Catalogue dir.")] = None,
    tests: Annotated[str, typer.Option("--tests", help="Comma list of N,M,S,L,CL.")] = "N,M,S,L,CL",
    out: Annotated[
        Path | None, typer.Option("--out", help="Report dir (default reports/eval/<id>/).")
    ] = None,
    n_simulations: Annotated[int, typer.Option("--n-simulations")] = 1000,
    alpha: Annotated[float, typer.Option("--alpha")] = 0.05,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("data"),
    no_plots: Annotated[bool, typer.Option("--no-plots", help="Skip the plot bundle.")] = False,
) -> None:
    """Run the consistency tests on one stored forecast; write results, target.parquet, plots."""
    store = ZarrGridStore(data_dir / "forecasts")
    grid = store.load(forecast)
    region = _region_if_present(data_dir, grid.region_id)
    cat = io.load_catalog(catalog or data_dir / "catalogs" / grid.region_id)
    out_dir = out or Path("reports") / "eval" / grid.id
    tracker = JsonlTracker(JsonlTracker.default_path(data_dir, grid.region_id))
    results = evaluate_forecast(
        grid,
        cat,
        PyCSEPEvaluator(),
        out_dir=out_dir,
        region=region,
        tests=_tests(tests),
        n_simulations=n_simulations,
        alpha=alpha,
        seed=seed,
        plots=not no_plots,
        tracker=tracker,
    )
    for r in results:
        q = (
            f"q_low={r.quantile_low:.4f} q_high={r.quantile_high:.4f}"
            if r.quantile_low is not None and r.quantile_high is not None
            else f"quantile={r.quantile}"
        )
        typer.echo(
            f"{r.test_name.value:>2}: statistic={r.statistic:.4f} {q} passed={r.passed} "
            f"n_target={r.n_target_events}"
        )
    typer.echo(f"wrote {out_dir}")


@app.command("schedule")
def schedule(  # noqa: PLR0917 - typer options
    region: Annotated[str, typer.Option("--region")],
    start: Annotated[str, typer.Option("--from", help="First issue time, ISO 8601 UTC.")],
    end: Annotated[str, typer.Option("--to", help="Schedule end, ISO 8601 UTC.")],
    model: Annotated[str, typer.Option("--model")] = "etas",
    step: Annotated[str, typer.Option("--step")] = "30d",
    horizon: Annotated[str, typer.Option("--horizon")] = "30d",
    refit: Annotated[str, typer.Option("--refit", help="yearly | none")] = "yearly",
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    mc: Annotated[float | None, typer.Option("--mc")] = None,
    n_simulations: Annotated[int, typer.Option("--n-simulations")] = 100,
    eval_simulations: Annotated[int, typer.Option("--eval-simulations")] = 1000,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
    tests: Annotated[str, typer.Option("--tests")] = "N,M,S,L,CL",
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("data"),
    baselines: Annotated[Path, typer.Option("--baselines")] = Path("baselines"),
    reports: Annotated[Path, typer.Option("--reports")] = Path("reports"),
    plots: Annotated[bool, typer.Option("--plots", help="Write plot bundles per window.")] = False,
    auxiliary_years: Annotated[float, typer.Option("--auxiliary-years")] = 2.0,
) -> None:
    """Rolling pseudo-prospective issue-and-evaluate; aggregates pass rates per test."""
    if model not in {"etas", MODEL_ID}:
        typer.echo(f"rupture evaluate schedule: model {model!r} not available", err=True)
        raise typer.Exit(EXIT_NOT_IMPLEMENTED)
    if refit not in {"yearly", "none"}:
        typer.echo("--refit must be 'yearly' or 'none'", err=True)
        raise typer.Exit(1)
    region_obj = io.load_region(data_dir / "regions" / region)
    cat = io.load_catalog(catalog or data_dir / "catalogs" / region)
    report = run_schedule(
        cat,
        region_obj,
        start=io.parse_utc(start),
        end=io.parse_utc(end),
        step=parse_horizon(step),
        horizon=parse_horizon(horizon),
        baselines_dir=baselines,
        forecasts_dir=data_dir / "forecasts",
        reports_dir=reports,
        refit="yearly" if refit == "yearly" else "none",
        model=MizrahiETAS(auxiliary_years=auxiliary_years),
        evaluator=PyCSEPEvaluator(),
        tracker=JsonlTracker(JsonlTracker.default_path(data_dir, region)),
        tests=_tests(tests) if tests else list(DEFAULT_TESTS),
        n_simulations=n_simulations,
        eval_simulations=eval_simulations,
        seed=seed,
        mc=mc,
        plots=plots,
    )
    typer.echo(
        f"schedule {region}: issued {report['n_issued']}, scored {report['n_scored']}, "
        f"refits {len(report['refits'])}"
    )
    for name, agg in report["pass_rates"].items():
        rate = "n/a" if agg["rate"] is None else f"{agg['rate']:.2f}"
        typer.echo(f"  {name:>2}: {agg['passed']}/{agg['scored']} passed (rate {rate})")
    typer.echo(f"wrote {report['report_path']}")
