"""`rupture challenger ...` — fit, issue and score the challenger models.

Every verb here produces expected counts per cell and
magnitude bin, on the same grid and bins as the ETAS baseline, scored under
``docs/EVALUATION_PROTOCOL.md``.

This module is **append-only across agents**: each challenger owns its own ``typer`` sub-app and
registers it below. ``ntpp`` (this file's owner) is registered first; a second challenger adds its
own ``app.add_typer(...)`` line and its own module, and touches nothing else here.

Wiring note for the architect: ``src/rupture/cli.py`` is not this agent's file, so the line

    from rupture.commands import challenger
    app.add_typer(challenger.app, name="challenger")

still has to be added there. Until it is, the sub-app runs as
``uv run python -m rupture.commands.challenger ntpp ...``.

The order of the verbs is the order they must be run in, and each refuses to skip a step:

1. ``select`` chooses hyperparameters on a validation window ending at or before the cutoff and
   writes the frozen record. Nothing later will run without it.
2. ``fit`` trains on ``origin_time < cutoff`` with the frozen configuration.
3. ``issue`` produces one forecast; ``schedule`` produces the whole pseudo-prospective run and the
   paired comparison against ETAS.
4. ``ablate`` runs the deliberately leaky variants, which are never results.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.adapters.forecasting.etas_mizrahi import load_fit as load_etas_fit
from rupture.adapters.storage.run_log import JsonlTracker
from rupture.commands._stub import EXIT_NOT_IMPLEMENTED
from rupture.domain import Catalog, FitResult, Region, parse_horizon, utc_now
from rupture.models.challengers.ntpp import NeuralTPPForecaster, NTPPConfig, save_fit
from rupture.models.challengers.ntpp.adapter import MODEL_ID, load_saved_fit
from rupture.models.challengers.ntpp.schedule import promotion_verdict, run_ntpp_schedule
from rupture.models.challengers.ntpp.train import (
    HYPERPARAMETERS_FILE,
    candidate_configs,
    freeze,
    load_frozen,
    select_config,
)
from rupture.pipelines import io
from rupture.pipelines.run_forecast import history_for
from rupture.ports import RunRecord

app = typer.Typer(
    help="Challenger models measured against the ETAS baseline.", no_args_is_help=True
)
ntpp_app = typer.Typer(
    help="Neural temporal point process (C1a).",
    no_args_is_help=True,
)
app.add_typer(ntpp_app, name="ntpp")
protocol_app = typer.Typer(
    help=(
        "The gridded challenger (C1b) and the log-linear ensemble, run over the protocol schedule."
    ),
    no_args_is_help=True,
)
app.add_typer(protocol_app, name="protocol")
# A second challenger registers its own sub-app on the line below; do not edit anything above.

MODELS = {"ntpp": MODEL_ID, MODEL_ID: MODEL_ID}


def _catalog_path(catalog: Path | None, data_dir: Path, region_id: str) -> Path:
    return catalog if catalog is not None else data_dir / "catalogs" / region_id


def _load(region: str, catalog: Path | None, data_dir: Path) -> tuple[Catalog, Region]:
    region_record = io.load_region(data_dir / "regions" / region)
    catalogue = io.load_catalog(_catalog_path(catalog, data_dir, region))
    return catalogue, region_record


def _frozen_config(baselines_dir: Path, region_id: str) -> NTPPConfig:
    path = baselines_dir / "ntpp" / region_id / HYPERPARAMETERS_FILE
    if not path.exists():
        typer.echo(
            f"rupture challenger ntpp: no frozen configuration at {path}; run "
            "`rupture challenger ntpp select` first — a fit with an unfrozen configuration is "
            "not admissible under ADR-0022 decision 4",
            err=True,
        )
        raise typer.Exit(EXIT_NOT_IMPLEMENTED)
    config, _ = load_frozen(path)
    return config


@ntpp_app.command("select")
def select(  # noqa: PLR0917 - typer options
    region: Annotated[str, typer.Option("--region", help="Region id (data/regions/<id>).")],
    train_start: Annotated[str, typer.Option("--from", help="Start of the training span, UTC.")],
    validation_end: Annotated[
        str, typer.Option("--validation-end", help="End of the validation span, UTC.")
    ],
    cutoff: Annotated[
        str, typer.Option("--cutoff", help="Hard training cutoff (the protocol's first issue).")
    ],
    catalog: Annotated[Path | None, typer.Option("--catalog", help="Catalogue directory.")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("data"),
    baselines_dir: Annotated[Path, typer.Option("--baselines-dir")] = Path("baselines"),
    mc: Annotated[float | None, typer.Option("--mc", help="Completeness magnitude.")] = None,
    folds: Annotated[int, typer.Option("--folds", help="Blocked time-forward folds.")] = 2,
    gap_days: Annotated[float, typer.Option("--gap-days")] = 0.0,
    auxiliary_years: Annotated[float, typer.Option("--auxiliary-years")] = 0.25,
) -> None:
    """Choose hyperparameters on blocked folds ending at or before the cutoff, and freeze them.

    Refuses if ``--validation-end`` is after ``--cutoff``: that would choose a configuration with
    knowledge of the test period.
    """
    catalogue, region_record = _load(region, catalog, data_dir)
    resolved, source = NeuralTPPForecaster.resolve_mc(catalogue, region_record, mc)
    selection = select_config(
        catalogue,
        region_record,
        mc=resolved,
        train_start=io.parse_utc(train_start),
        validation_end=io.parse_utc(validation_end),
        hard_cutoff=io.parse_utc(cutoff),
        candidates=candidate_configs(),
        n_folds=folds,
        gap=timedelta(days=gap_days),
        auxiliary_years=auxiliary_years,
    )
    path = freeze(selection, baselines_dir / "ntpp" / region)
    typer.echo(f"mc {resolved} ({source})")
    typer.echo(
        f"chosen config {selection.chosen_hash[:12]} over {len(selection.trials)} candidates"
    )
    typer.echo(f"frozen -> {path}")


@ntpp_app.command("fit")
def fit(  # noqa: PLR0917 - typer options
    region: Annotated[str, typer.Option("--region", help="Region id (data/regions/<id>).")],
    cutoff: Annotated[str, typer.Option("--cutoff", help="Hard cutoff; only earlier events.")],
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("data"),
    baselines_dir: Annotated[Path, typer.Option("--baselines-dir")] = Path("baselines"),
    mc: Annotated[float | None, typer.Option("--mc")] = None,
    auxiliary_years: Annotated[float, typer.Option("--auxiliary-years")] = 0.25,
) -> None:
    """Fit on ``origin_time < cutoff`` with the frozen configuration; persist and archive it."""
    catalogue, region_record = _load(region, catalog, data_dir)
    config = _frozen_config(baselines_dir, region)
    model = NeuralTPPForecaster(config, auxiliary_years=auxiliary_years)
    result = model.fit(catalogue, region_record, io.parse_utc(cutoff), mc=mc)
    out = save_fit(result, model.state_dict_json(), baselines_dir)
    JsonlTracker(JsonlTracker.default_path(data_dir, region)).log(_record("fit", region, result))
    typer.echo(
        f"fitted {result.n_events} events, converged={result.converged} "
        f"({result.diagnostics['converged_reason']}), "
        f"log-likelihood {result.log_likelihood:.2f}"
    )
    typer.echo(f"snapshot {result.parameter_snapshot_hash[:12]} -> {out}")
    if not result.converged:
        raise typer.Exit(1)


@ntpp_app.command("issue")
def issue(  # noqa: PLR0917 - typer options
    region: Annotated[str, typer.Option("--region")],
    issue_time: Annotated[str, typer.Option("--issue", help="Issue time, UTC.")],
    horizon: Annotated[str, typer.Option("--horizon", help="e.g. 30d.")] = "30d",
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("data"),
    baselines_dir: Annotated[Path, typer.Option("--baselines-dir")] = Path("baselines"),
    simulations: Annotated[int, typer.Option("--simulations")] = 200,
    seed: Annotated[int, typer.Option("--seed")] = 20220101,
    out: Annotated[Path | None, typer.Option("--out", help="Write the grid as JSON here.")] = None,
) -> None:
    """Issue one forecast grid from the persisted fit, using only events before the issue time."""
    catalogue, region_record = _load(region, catalog, data_dir)
    persisted, weights = load_saved_fit(baselines_dir, region)
    model = NeuralTPPForecaster(NTPPConfig.from_dict(persisted.diagnostics["config"]))
    model.load_fit(persisted, region_record, weights)
    when = io.parse_utc(issue_time)
    history = history_for(catalogue, when, persisted.mc)
    grid = model.forecast(
        history, when, parse_horizon(horizon), n_simulations=simulations, seed=seed
    )
    typer.echo(f"{grid.id}: {grid.total_expected():.4f} expected events over {horizon}")
    typer.echo(grid.notes or "")
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(grid.model_dump(mode="json"), indent=2, sort_keys=True), "utf-8")
        typer.echo(f"-> {out}")


@ntpp_app.command("schedule")
def schedule(  # noqa: PLR0917 - typer options
    region: Annotated[str, typer.Option("--region")],
    start: Annotated[str, typer.Option("--from", help="First issue time, UTC.")],
    end: Annotated[str, typer.Option("--to", help="Schedule end, UTC.")],
    step: Annotated[str, typer.Option("--step")] = "30d",
    horizon: Annotated[str, typer.Option("--horizon")] = "30d",
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("data"),
    baselines_dir: Annotated[Path, typer.Option("--baselines-dir")] = Path("baselines"),
    reports_dir: Annotated[Path, typer.Option("--reports-dir")] = Path("reports"),
    simulations: Annotated[int, typer.Option("--simulations")] = 200,
    eval_simulations: Annotated[int, typer.Option("--eval-simulations")] = 1000,
    seed: Annotated[int, typer.Option("--seed")] = 20220101,
    refit: Annotated[str, typer.Option("--refit", help="yearly or none.")] = "none",
    benchmark_simulations: Annotated[
        int | None,
        typer.Option(
            "--benchmark-simulations",
            help="Continuations for the ETAS benchmark; defaults to --simulations, "
            "which is what makes the paired comparison symmetric.",
        ),
    ] = None,
    compare_etas: Annotated[
        bool, typer.Option("--compare-etas/--no-compare-etas", help="Run the paired T/W tests.")
    ] = True,
    evaluate_benchmark: Annotated[
        bool,
        typer.Option(
            "--evaluate-benchmark/--no-evaluate-benchmark",
            help="Also score the benchmark's own consistency tests on the same target slices, "
            "so both pass-rate columns come from one run. Condition 1 of the promotion rule "
            "needs them; off, the verdict cannot be computed.",
        ),
    ] = True,
) -> None:
    """Run the pseudo-prospective schedule; by default compare with ETAS window by window.

    The benchmark is scored in the same run by default. That is what produced the committed
    ``benchmark_pass_rates`` in ``reports/protocol/<region>/eval/schedule-<region>-ntpp.json``,
    and it is the only way the two pass-rate columns are known to come from the same grids, the
    same target slices and the same simulation budget.
    """
    if refit not in {"yearly", "none"}:
        typer.echo("rupture challenger ntpp schedule: --refit must be 'yearly' or 'none'", err=True)
        raise typer.Exit(1)
    catalogue, region_record = _load(region, catalog, data_dir)
    persisted, weights = load_saved_fit(baselines_dir, region)
    model = NeuralTPPForecaster(NTPPConfig.from_dict(persisted.diagnostics["config"]))
    model.load_fit(persisted, region_record, weights)
    benchmark: MizrahiETAS | None = None
    if compare_etas:
        etas_fit = load_etas_fit(baselines_dir, region)
        benchmark = MizrahiETAS(auxiliary_years=etas_fit.diagnostics.get("auxiliary_years", 2.0))
        benchmark.load_fit(etas_fit, region_record)
    report = run_ntpp_schedule(
        catalogue,
        region_record,
        model,
        start=io.parse_utc(start),
        end=io.parse_utc(end),
        step=parse_horizon(step),
        horizon=parse_horizon(horizon),
        baselines_dir=baselines_dir,
        forecasts_dir=data_dir / "forecasts",
        reports_dir=reports_dir,
        benchmark=benchmark,
        evaluate_benchmark=evaluate_benchmark and benchmark is not None,
        refit="yearly" if refit == "yearly" else "none",
        n_simulations=simulations,
        benchmark_simulations=benchmark_simulations or simulations,
        eval_simulations=eval_simulations,
        seed=seed,
        mc=persisted.mc,
    )
    typer.echo(f"issued {report['n_issued']}, scored {report['n_scored']}")
    for name, detail in report["pass_rates"].items():
        typer.echo(f"  {name}: {detail['passed']}/{detail['scored']}")
    if compare_etas:
        typer.echo(f"  vs etas: {json.dumps(report['comparison_summary'], sort_keys=True)}")
    # The verdict is only meaningful against the benchmark's own pass rates from this same run;
    # passing None would fail condition 1 for want of a comparison, not for want of skill.
    verdict = promotion_verdict(report, report.get("benchmark_pass_rates"))
    typer.echo(json.dumps(verdict, indent=2, sort_keys=True))
    typer.echo(f"-> {report['report_path']}")


@ntpp_app.command("ablate")
def ablate(  # noqa: PLR0917 - typer options
    region: Annotated[str, typer.Option("--region")],
    start: Annotated[str, typer.Option("--from")],
    end: Annotated[str, typer.Option("--to")],
    honest_report: Annotated[
        Path, typer.Option("--honest-report", help="The disciplined run's schedule JSON.")
    ],
    step: Annotated[str, typer.Option("--step")] = "30d",
    horizon: Annotated[str, typer.Option("--horizon")] = "30d",
    catalog: Annotated[Path | None, typer.Option("--catalog")] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("data"),
    baselines_dir: Annotated[Path, typer.Option("--baselines-dir")] = Path("baselines"),
    reports_dir: Annotated[Path, typer.Option("--reports-dir")] = Path("reports"),
    simulations: Annotated[int, typer.Option("--simulations")] = 200,
    eval_simulations: Annotated[int, typer.Option("--eval-simulations")] = 1000,
    seed: Annotated[int, typer.Option("--seed")] = 20220101,
) -> None:
    """Run the deliberately leaky variants and print what the leaks bought. Never a result.

    The ETAS benchmark is loaded and scored here too, and the two leaky runs share one benchmark
    cache: the ablation's whole content is *differences* from the honest run's comparison against
    ETAS, so a run without the benchmark produces no ``information_gain_vs_etas`` at all, and two
    runs against separately simulated benchmark grids would carry the benchmark's Monte Carlo
    noise into the difference alongside the leak.
    """
    from rupture.models.challengers.ntpp.ablation import (  # noqa: PLC0415 - heavy, and rarely run
        LEAKY_BANNER,
        run_ablations,
        write_ablation_report,
    )

    catalogue, region_record = _load(region, catalog, data_dir)
    persisted, _ = load_saved_fit(baselines_dir, region)
    etas_fit = load_etas_fit(baselines_dir, region)
    benchmark = MizrahiETAS(auxiliary_years=etas_fit.diagnostics.get("auxiliary_years", 2.0))
    benchmark.load_fit(etas_fit, region_record)
    typer.echo(LEAKY_BANNER, err=True)
    result = run_ablations(
        catalogue,
        region_record,
        honest_report=json.loads(honest_report.read_text(encoding="utf-8")),
        frozen_config=_frozen_config(baselines_dir, region),
        mc=persisted.mc,
        cutoff=persisted.fit_cutoff,
        start=io.parse_utc(start),
        end=io.parse_utc(end),
        step=parse_horizon(step),
        horizon=parse_horizon(horizon),
        baselines_dir=baselines_dir,
        forecasts_dir=data_dir / "forecasts",
        reports_dir=reports_dir,
        benchmark=benchmark,
        benchmark_cache={},
        n_simulations=simulations,
        eval_simulations=eval_simulations,
        seed=seed,
    )
    for name in ("tuning_leak", "fit_leak"):
        typer.echo(f"{name}: {json.dumps(result[name]['delta'], indent=2, sort_keys=True)}")
    typer.echo(f"-> {write_ablation_report(result, reports_dir, region)}")


def _record(kind: str, region: str, result: FitResult) -> RunRecord:
    return RunRecord(
        run_id=f"{kind}-{region}-{result.fit_cutoff:%Y%m%dT%H%M%SZ}",
        kind=kind,
        at=utc_now(),
        region_id=region,
        model_id=result.model_id,
        parameter_snapshot_hash=result.parameter_snapshot_hash,
        inputs={"cutoff": result.fit_cutoff.isoformat(), "mc": result.mc},
        outputs={
            "n_events": result.n_events,
            "converged": result.converged,
            "log_likelihood": result.log_likelihood,
            "config_hash": result.diagnostics.get("config_hash"),
        },
    )


@protocol_app.command("run")
def protocol_run(
    region: Annotated[str, typer.Option("--region", help="Region id (data/regions/<id>).")],
    repo: Annotated[Path, typer.Option("--repo", help="Repository root.")] = Path("."),
    skip_ablation: Annotated[
        bool,
        typer.Option(
            "--skip-ablation/--with-ablation",
            help="Skip the deliberately leaky gridded fit. It is never a result, but it is what "
            "the discipline's value is measured with, so it is on by default.",
        ),
    ] = False,
) -> None:
    """Reproduce `reports/challenger/<region>/schedule-<region>-challengers.json`, end to end.

    Hyperparameter search, the weight-fitting block, the test fit, the 55-window schedule for both
    the gridded challenger and the ensemble, and the leaky ablation — the stages of
    ``rupture.models.ensemble.protocol_runner``, which every committed C1b and ensemble number
    came from. Each stage caches to disk, so a run is resumable; a full region is hours, not
    minutes.

    This exists because the committed evidence behind a promotion verdict must be regenerable
    through the repository's own entry points. It was previously reachable only as
    ``python -m rupture.models.ensemble.protocol_runner``, a module path that appears in no
    Makefile and no command table.
    """
    from rupture.models.ensemble.protocol_runner import (  # noqa: PLC0415 - torch, and hours long
        Paths,
        run_region,
    )

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    report = run_region(region, Paths(repo.resolve()), skip_ablation=skip_ablation)
    for model_id, block in sorted((report.get("models") or {}).items()):
        promotion = block.get("promotion") or {}
        met = promotion.get("promotable_in_this_region")
        typer.echo(f"{model_id}: both conditions met in {region} = {met}")
    typer.echo(
        "A region verdict is not a promotion: the rule needs two of three regions, and "
        "`make validate-challengers` recomputes it over every committed region."
    )


if __name__ == "__main__":  # pragma: no cover - until cli.py registers the sub-app
    app()
