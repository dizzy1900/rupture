"""``rupture risk`` — price a portfolio against a scenario and report what an intervention avoids.

**Registration.** ``src/rupture/cli.py`` belongs to the architect and this sub-application is not
wired into it yet, so until one line (``app.add_typer(risk.app, name="risk")``) is added, the same
commands are reachable as ``uv run python -m rupture.commands.risk <command>``. ``mk/risk.mk``
uses that form, so the gate runs today; the risk report asks the architect for the one-line change.

Every figure printed here carries its interval, its provenance tier and the assumptions it rests
on. A run that could not model part of the portfolio says which part and why.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer

from rupture.adapters.exposure import GeoParquetExposureSource, SeracExposureSource
from rupture.adapters.groundmotion import registry as gsim_registry
from rupture.domain.avoided_loss_v1 import (
    AvoidedLossRequestV1,
    Intervention,
    InterventionKind,
)
from rupture.domain.common import utc_now
from rupture.domain.loss import ExposurePortfolio, TriggerKind
from rupture.risk import avoided_loss as avoided
from rupture.risk import loss as loss_module
from rupture.risk import scenarios as scenario_module

REPO_ROOT = Path(__file__).resolve().parents[3]
EXIT_OK = 0
EXIT_FAIL = 1
SERAC = "serac"

app = typer.Typer(
    help="Ground motion to loss to avoided loss (F2). rupture does not predict earthquakes.",
    no_args_is_help=True,
)


def _portfolio(spec: str, *, portfolio_id: str) -> tuple[ExposurePortfolio, list[str]]:
    """Load the portfolio named by ``--portfolio``: ``serac`` or a path to an import file."""
    if spec == SERAC:
        source = SeracExposureSource(repo_root=REPO_ROOT)
        portfolio = source.load(portfolio_id=portfolio_id)
        return portfolio, source.last_report.lines()
    path = Path(spec).expanduser()
    imported = GeoParquetExposureSource().load(path, portfolio_id=portfolio_id)
    return imported, [f"exposure source: {path}"]


def _interventions(spec: str | None) -> tuple[Intervention, ...]:
    """Interventions from a JSON file, or the documented default set when none is given."""
    if spec is None:
        return (
            Intervention(
                id="retrofit-all",
                kind=InterventionKind.STRUCTURAL_RETROFIT,
                description="anchor the vulnerable components at every plant",
            ),
            Intervention(
                id="automated-shutdown",
                kind=InterventionKind.AUTOMATED_SHUTDOWN,
                description="trip the units and close the intake on a strong-motion trigger",
            ),
        )
    payload = json.loads(Path(spec).expanduser().read_text(encoding="utf-8"))
    return tuple(Intervention.model_validate(item) for item in payload)


@app.command("scenarios")
def list_scenarios() -> None:
    """List the scenarios ``--scenario`` accepts."""
    for name, rupture in scenario_module.builtin(REPO_ROOT).items():
        tag = "HYPOTHETICAL" if rupture.hypothetical else "published rupture model"
        typer.echo(f"{name}  M{rupture.magnitude:.2f}  {tag}")
        typer.echo(f"    {rupture.notes}")
        for ref in rupture.source_refs:
            typer.echo(f"    source: {ref}")


@app.command("gsims")
def list_gsims() -> None:
    """List the GSIMs the native engine has verified against OpenQuake's expected values."""
    for entry in gsim_registry.ENTRIES:
        typer.echo(
            f"{entry.name}  tolerance: mean {entry.mean_tolerance_percent} %, "
            f"stddev {entry.stddev_tolerance_percent} %  ({entry.notes})"
        )


@app.command("run")
def run(  # noqa: PLR0917 - typer needs each option as a parameter
    portfolio: Annotated[
        str, typer.Option(help="'serac' for the sibling's corridor export, or a path to an import.")
    ] = SERAC,
    scenario: Annotated[str | None, typer.Option(help="Scenario id (see `scenarios`).")] = None,
    forecast: Annotated[
        str | None, typer.Option(help="ForecastGrid id. Not implemented; exits 1 saying why.")
    ] = None,
    gsim: Annotated[str, typer.Option(help="GSIM name.")] = loss_module.DEFAULT_GSIM,
    imt: Annotated[str, typer.Option(help="Intensity measure type.")] = loss_module.DEFAULT_IMT,
    realisations: Annotated[int, typer.Option(help="Ground-motion realisations.")] = 1000,
    seed: Annotated[int, typer.Option(help="Random seed.")] = 20260903,
    interval: Annotated[float, typer.Option(help="Interval coverage, e.g. 0.9.")] = 0.9,
    interventions: Annotated[
        str | None, typer.Option(help="JSON file of Intervention objects.")
    ] = None,
    allow_tectonic_mismatch: Annotated[
        bool,
        typer.Option(help="Permit a GSIM outside its tectonic region (recorded on the field)."),
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Emit the response as JSON.")] = False,
) -> None:
    """Print the loss and the avoided loss, both with intervals."""
    if (scenario is None) == (forecast is None):
        typer.echo("give exactly one of --scenario or --forecast", err=True)
        raise typer.Exit(EXIT_FAIL)
    exposure, notes = _portfolio(portfolio, portfolio_id="trishuli-corridor")
    config = loss_module.RunConfig(
        gsim=gsim,
        imt=imt,
        n_realisations=realisations,
        seed=seed,
        interval_level=interval,
        allow_tectonic_mismatch=allow_tectonic_mismatch,
    )
    request = AvoidedLossRequestV1(
        request_id=f"cli-{utc_now():%Y%m%dt%H%M%S}",
        requested_at=utc_now(),
        portfolio=exposure,
        trigger_kind=TriggerKind.SCENARIO if scenario else TriggerKind.FORECAST,
        trigger_id=scenario or forecast or "",
        interventions=_interventions(interventions),
        interval_level=interval,
        consumer="rupture-cli",
    )
    response = avoided.respond(request, repo_root=REPO_ROOT, config=config)
    if as_json:
        typer.echo(json.dumps(response.model_dump(mode="json"), indent=2))
        raise typer.Exit(EXIT_OK if response.status.value == "ok" else EXIT_FAIL)

    for line in notes:
        typer.echo(line)
    if response.status.value != "ok":
        typer.echo(f"status: {response.status.value}")
        typer.echo(f"reason: {response.message}")
        raise typer.Exit(EXIT_FAIL)

    total = response.baseline_total
    assert total is not None
    typer.echo("")
    typer.echo(f"scenario: {request.trigger_id}   realisations: {response.n_realisations}")
    typer.echo(
        f"expected loss: {total.best:,.0f} {total.currency} "
        f"[{total.low:,.0f}, {total.high:,.0f}] at {interval:.0%} "
        f"({total.provenance.value}, confidence {total.confidence.value})"
    )
    typer.echo("")
    typer.echo("avoided loss by intervention:")
    for outcome in response.interventions:
        a = outcome.avoided_vs_baseline
        typer.echo(
            f"  {outcome.intervention_id:24s} {a.best:>15,.0f} {a.currency} "
            f"[{a.low:,.0f}, {a.high:,.0f}]"
        )
    typer.echo("")
    typer.echo("largest losses by asset:")
    ranked = sorted(response.baseline, key=lambda al: al.expected_loss.best or 0.0, reverse=True)
    for asset_loss in ranked[:5]:
        money = asset_loss.expected_loss
        typer.echo(
            f"  {asset_loss.asset_id:24s} {money.best:>15,.0f} {money.currency} "
            f"[{money.low:,.0f}, {money.high:,.0f}]"
        )
    typer.echo("")
    for assumption in response.assumptions:
        typer.echo(f"assumption: {assumption}")
    if response.message:
        typer.echo(f"note: {response.message}")
    raise typer.Exit(EXIT_OK)


@app.command("validate")
def validate(
    root: Annotated[Path, typer.Option(help="Repository root.")] = REPO_ROOT,
) -> None:
    """Run the ``risk`` gate (what ``make validate-risk`` calls until the gate is registered)."""
    from rupture.validation import risk as gate  # noqa: PLC0415 - avoids a CLI import cycle

    result = gate.run(root)
    typer.echo(result.render())
    raise typer.Exit(EXIT_OK if result.ok else EXIT_FAIL)


def main() -> None:
    """Entry point for ``python -m rupture.commands.risk``."""
    sys.exit(app())


if __name__ == "__main__":
    main()
