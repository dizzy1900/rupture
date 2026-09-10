"""`rupture alarm ...` — the AlarmSet arm: build an alarm, score it, and see what it beat.

Three verbs. ``arms`` prints the hypothesis sum type and which of its five arms can actually be
scored, because the honest answer today is one of five and a table beats a paragraph. ``score``
scores a stored alarm against a stored forecast's spatial marginal. ``power`` answers the question
that should be asked before an experiment rather than after it: how many target events would this
alarm fraction need before a gain worth having could be seen at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from rupture.adapters.storage.zarr_store import ZarrGridStore
from rupture.domain.alarm import AlarmScore, AlarmSet
from rupture.pipelines import io
from rupture.scoring import power as power_mod
from rupture.scoring import reference as refmod
from rupture.scoring.alarm import DEFAULT_ALTERNATIVE_GAIN, score_alarm_set
from rupture.scoring.registry import registry_table

app = typer.Typer(
    help="Alarm-based hypotheses: Molchan, area skill, probability gain.", no_args_is_help=True
)


@app.command("arms")
def arms() -> None:
    """Print the hypothesis sum type and which arms have a registered scorer (ADR-0055)."""
    rows = registry_table()
    width = max(len(r["arm"]) for r in rows)
    for row in rows:
        state = row["scorer"] if row["scorer"] != "NOT_IMPLEMENTED" else "NOT_IMPLEMENTED"
        typer.echo(f"{row['arm']:<{width}}  {state}")
        typer.echo(f"{'':<{width}}    asserts:   {row['asserts']}")
        typer.echo(f"{'':<{width}}    reference: {row['reference']}")
        if row["reason"]:
            typer.echo(f"{'':<{width}}    why not:   {row['reason']}")


@app.command("score")
def score(  # noqa: PLR0917 - typer options
    alarm: Annotated[Path, typer.Option("--alarm", help="AlarmSet JSON.")],
    reference_forecast: Annotated[
        str, typer.Option("--reference-forecast", help="Forecast id supplying the reference.")
    ],
    catalog: Annotated[Path | None, typer.Option("--catalog", help="Catalogue dir.")] = None,
    out: Annotated[
        Path | None, typer.Option("--out", help="Where to write the score JSON.")
    ] = None,
    data_dir: Annotated[Path, typer.Option("--data-dir")] = Path("data"),
    alpha: Annotated[float, typer.Option("--alpha")] = 0.05,
    target_power: Annotated[float, typer.Option("--target-power")] = 0.8,
    alternative_gain: Annotated[
        float, typer.Option("--alternative-gain", help="The gain the power figure is against.")
    ] = DEFAULT_ALTERNATIVE_GAIN,
    n_simulations: Annotated[int, typer.Option("--n-simulations")] = 10_000,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
    uniform_contrast: Annotated[
        bool,
        typer.Option(
            "--uniform-contrast",
            help="Also score against an area-uniform reference, labelled as a contrast.",
        ),
    ] = False,
) -> None:
    """Score one alarm set against the spatial marginal of one fitted forecast."""
    alarm_set = AlarmSet.model_validate_json(alarm.read_text(encoding="utf-8"))
    grid = ZarrGridStore(data_dir / "forecasts").load(reference_forecast)
    cat = io.load_catalog(catalog or data_dir / "catalogs" / alarm_set.region_id)
    ref = refmod.from_forecast_grid(grid, min_magnitude=alarm_set.target_min_magnitude)
    result = score_alarm_set(
        alarm_set,
        cat,
        ref,
        alpha=alpha,
        target_power=target_power,
        alternative_gain=alternative_gain,
        n_simulations=n_simulations,
        seed=seed,
    )
    _echo(result)
    out_dir = out or Path("reports") / "alarm" / alarm_set.id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "score.json").write_text(
        json.dumps(json.loads(result.model_dump_json()), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if uniform_contrast:
        contrast = score_alarm_set(
            alarm_set,
            cat,
            refmod.uniform_like(ref),
            alpha=alpha,
            target_power=target_power,
            alternative_gain=alternative_gain,
            n_simulations=n_simulations,
            seed=seed,
            as_contrast=True,
        )
        typer.echo("\n-- uniform contrast (NOT the reference of record) --")
        _echo(contrast)
        (out_dir / "score-uniform-contrast.json").write_text(
            json.dumps(json.loads(contrast.model_dump_json()), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    typer.echo(f"wrote {out_dir}")


@app.command("power")
def power(
    n_targets: Annotated[int, typer.Option("--n-targets", help="Target events available.")],
    tau: Annotated[float, typer.Option("--tau", help="Alarm fraction in the reference measure.")],
    gain: Annotated[float, typer.Option("--gain", help="The probability gain of interest.")] = 2.0,
    alpha: Annotated[float, typer.Option("--alpha")] = 0.05,
    target_power: Annotated[float, typer.Option("--target-power")] = 0.8,
) -> None:
    """What this experiment could see, before it is run (ADR-0055 decisions 4 and 5)."""
    critical = power_mod.critical_hits(n_targets, tau, alpha)
    achieved = power_mod.power_at_gain(n_targets, tau, gain, alpha)
    mdg = power_mod.minimum_detectable_gain(n_targets, tau, alpha=alpha, target_power=target_power)
    typer.echo(f"targets={n_targets}  alarm fraction tau={tau}  alpha={alpha}")
    if critical is None:
        typer.echo(
            "  no outcome rejects the reference at this alpha: the test has no rejection region, "
            "so a pass from it would carry no information at all"
        )
    else:
        typer.echo(f"  rejects the reference at {critical} or more hits of {n_targets}")
    typer.echo(f"  power against G = {gain}: {achieved:.3f}")
    if mdg is None:
        typer.echo(
            f"  minimum detectable gain: none. Not even a perfect alarm inside this footprint "
            f"would reject the reference. The achieved upper bound is G < {1.0 / tau:.4g}"
        )
    else:
        typer.echo(f"  minimum detectable gain at {target_power:.0%} power: G = {mdg:.3f}")
    if gain > 1.0:
        needed = power_mod.events_needed_for_gain(tau, gain, alpha=alpha, target_power=target_power)
        text = "more than the search cap" if needed is None else str(needed)
        typer.echo(f"  targets needed to see G = {gain} at {target_power:.0%} power: {text}")


def _echo(result: AlarmScore) -> None:
    typer.echo(
        f"{result.alarm_set_id}: N={result.n_target_events} "
        f"reference={result.reference_model_id} ({result.reference_kind.value})"
    )
    if result.area_skill_score is not None:
        typer.echo(
            f"  area skill {result.area_skill_score:.4f} (p = {result.area_skill_p_value:.4g}, "
            f"{result.area_skill_simulations} simulations); 0.5 is the reference itself"
        )
    if result.declared_probability_gain is not None:
        typer.echo(
            f"  probability gain G = {result.declared_probability_gain:.3f} at alarm fraction "
            f"{result.declared_tau:.4f} ({result.declared_hits} hits, "
            f"p = {result.declared_p_value:.4g}, significant={result.significant})"
        )
        typer.echo(
            f"  power against G = {result.power_against_gain}: {result.power:.3f}; "
            f"minimum detectable gain "
            + (
                "none"
                if result.minimum_detectable_gain is None
                else f"G = {result.minimum_detectable_gain:.3f}"
            )
        )
    for note in result.notes:
        typer.echo(f"  note: {note}")
