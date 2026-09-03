"""``rupture`` command-line interface.

rupture does not predict earthquakes. Sub-commands live in :mod:`rupture.commands`; validation
gates in :mod:`rupture.validation` (resolved by name through the registry). Anything not yet
implemented exits with status 2 and names the phase that delivers it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from rupture import __version__
from rupture.adapters.exposure import SeracExposureSource
from rupture.commands import (
    aftershock,
    cascade,
    catalog,
    evaluate,
    forecast,
    hazard,
    region,
    risk,
)
from rupture.domain import contracts, utc_now
from rupture.domain.avoided_loss_v1 import (
    AvoidedLossRequestV1,
    HazardKind,
    Intervention,
    InterventionKind,
    ResponseStatus,
)
from rupture.domain.loss import TriggerKind
from rupture.domain.money import ModelProvenance, MoneyRange
from rupture.risk.avoided_loss import respond
from rupture.validation import GateResult, GateStatus
from rupture.validation.registry import GATES, run_gate

REPO_ROOT = Path(__file__).resolve().parents[2]

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_NOT_IMPLEMENTED = 2

app = typer.Typer(
    name="rupture",
    help=(
        "Probabilistic seismic forecasting and cascade-loss model. "
        "rupture does not predict earthquakes."
    ),
    no_args_is_help=True,
    add_completion=False,
)
validate_app = typer.Typer(help="Validation gates behind `make validate-*`.", no_args_is_help=True)
schema_app = typer.Typer(help="JSON Schema export for contracts/.", no_args_is_help=True)
app.add_typer(validate_app, name="validate")
app.add_typer(schema_app, name="schema")
app.add_typer(catalog.app, name="catalog")
app.add_typer(region.app, name="region")
app.add_typer(forecast.app, name="forecast")
app.add_typer(evaluate.app, name="evaluate")
app.add_typer(hazard.app, name="hazard")
app.add_typer(cascade.app, name="cascade")
app.add_typer(risk.app, name="risk")
app.add_typer(aftershock.app, name="aftershock")


def _finish(result: GateResult) -> None:
    print(result.render())
    if result.status == GateStatus.NOT_IMPLEMENTED:
        raise typer.Exit(EXIT_NOT_IMPLEMENTED)
    raise typer.Exit(EXIT_OK if result.ok else EXIT_FAIL)


def _version_callback(value: bool) -> None:
    if value:
        print(f"rupture {__version__}")
        raise typer.Exit(EXIT_OK)


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option(
            "--version", help="Print version and exit.", callback=_version_callback, is_eager=True
        ),
    ] = False,
) -> None:
    """rupture does not predict earthquakes."""


# ------------------------------------------------------------------ validate
@validate_app.command("gate")
def validate_gate(
    name: Annotated[str, typer.Argument(help=f"One of: {', '.join(GATES)}")],
    root: Annotated[Path, typer.Option(help="Repository root.")] = REPO_ROOT,
) -> None:
    """Run one gate by name."""
    _finish(run_gate(name, root))


def _make_gate_command(gate: str) -> None:
    def _cmd(root: Annotated[Path, typer.Option(help="Repository root.")] = REPO_ROOT) -> None:
        _finish(run_gate(gate, root))

    _cmd.__doc__ = f"Run the {gate} gate (`make validate-{gate}`)."
    validate_app.command(gate)(_cmd)


for _gate in GATES:
    _make_gate_command(_gate)


# ------------------------------------------------------------------ schema
@schema_app.command("export")
def schema_export(
    out: Annotated[Path, typer.Option(help="Target directory.")] = REPO_ROOT / "contracts",
    check: Annotated[bool, typer.Option("--check", help="Fail if files would change.")] = False,
) -> None:
    """Write JSON Schema for every domain contract into contracts/ (or check for drift)."""
    if check:
        drifted = contracts.drift(out)
        if drifted:
            for name in drifted:
                print(f"drift: {name}")
            raise typer.Exit(EXIT_FAIL)
        print(f"contracts up to date ({len(contracts.CONTRACTS)} files)")
        raise typer.Exit(EXIT_OK)
    for path in contracts.export_all(out):
        print(f"wrote {path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path}")


# ------------------------------------------------------------------ release
@app.command()
def promote(
    root: Annotated[Path, typer.Option(help="Repository root.")] = REPO_ROOT,
    approved_by: Annotated[
        str | None,
        typer.Option("--approved-by", help="The person accepting this release. Required."),
    ] = None,
) -> None:
    """Re-run every gate and print the promotion record, naming each skip and its reason.

    `make promote` already refuses unless `validate-rupture` is green, but this command does not
    take that on trust: it runs the gates itself, so the record it prints reports the state it
    actually observed rather than asserting one. A gate that is SKIPPED does not block promotion
    (that is the rule in CLAUDE.md) but its reason is always printed, so a promotion record can
    never hide that, say, the OpenQuake container never ran.
    """
    if not approved_by or not approved_by.strip():
        print("promote: REFUSED — no approver named (--approved-by / PROMOTE_APPROVED_BY)")
        print("promote: a release nobody is willing to sign is not a release")
        raise typer.Exit(EXIT_FAIL)
    results = [run_gate(name, root) for name in GATES]
    for result in results:
        print(result.render())
    blocking = [r for r in results if not r.ok]
    skipped = [r for r in results if r.status == GateStatus.SKIPPED]
    if blocking:
        names = ", ".join(r.name for r in blocking)
        print(f"promote: REFUSED — not green: {names}")
        raise typer.Exit(EXIT_FAIL)
    passed = sum(1 for r in results if r.status == GateStatus.PASSED)
    summary = f"{passed}/{len(results)} gates passed"
    if skipped:
        summary += f", {len(skipped)} skipped ({', '.join(r.name for r in skipped)})"
    print(f"promote: rupture {__version__} — {summary}; see RELEASE_STATUS.md")
    print(f"promote: approved by {approved_by.strip()} at {utc_now().isoformat()}")


@app.command("underwriting-check")
def underwriting_check(
    portfolio: Annotated[
        str, typer.Option("--portfolio", help="Portfolio to price; the serac Nepal corridor.")
    ] = "trishuli-corridor",
    scenario: Annotated[
        str, typer.Option("--scenario", help="Scenario id from `rupture risk scenarios`.")
    ] = "mht-m8-hypothetical",
) -> None:
    """Run the Nepal corridor portfolio through the MHT scenario and print the numbers.

    This is the underwriter-facing end of rupture: a portfolio, a scenario, expected loss and what
    an intervention avoids, each as an interval with a stated basis. It exits non-zero if any
    figure is missing or the response is not a real answer, so a green run means numbers were
    actually produced — not that the code path executed.
    """
    source = SeracExposureSource()
    portfolio_obj = source.load(portfolio_id=portfolio)
    request = AvoidedLossRequestV1(
        request_id="underwriting-check",
        hazard_kind=HazardKind.SEISMIC,
        requested_at=utc_now(),
        portfolio=portfolio_obj,
        trigger_kind=TriggerKind.SCENARIO,
        trigger_id=scenario,
        interventions=(
            Intervention(
                id="retrofit-all",
                kind=InterventionKind.STRUCTURAL_RETROFIT,
                description="Seismic retrofit of every priced asset.",
            ),
        ),
    )
    response = respond(request, repo_root=REPO_ROOT)
    print(f"underwriting-check: portfolio {portfolio_obj.id} ({len(portfolio_obj.assets)} assets)")
    print(f"underwriting-check: scenario {scenario}")
    if response.status is not ResponseStatus.OK:
        print(f"underwriting-check: {response.status.value}: {response.message}")
        raise typer.Exit(EXIT_FAIL)
    total = response.baseline_total
    if total is None:
        print("underwriting-check: no baseline total was produced")
        raise typer.Exit(EXIT_FAIL)
    print(
        f"underwriting-check: expected loss {_money(total)}"
        f"  [{total.confidence.value} confidence, {total.provenance.value}]"
    )
    for outcome in response.interventions:
        avoided = outcome.avoided_vs_baseline
        print(f"underwriting-check: {outcome.intervention_id} avoids {_money(avoided)}")
    if response.provenance_kind is ModelProvenance.STUB:
        print("underwriting-check: the response is a stub; no figure above is usable")
        raise typer.Exit(EXIT_FAIL)
    print("underwriting-check: OK — every figure carries an interval and a basis")


def _money(m: MoneyRange) -> str:
    """Render a MoneyRange as a reader would want it: a central figure and its interval."""
    mid = m.best if m.best is not None else (m.low + m.high) / 2.0
    return f"{m.currency} {mid / 1e6:.1f}M [{m.low / 1e6:.1f}-{m.high / 1e6:.1f}M]"


def main() -> None:
    """Console entry point."""
    sys.exit(app())


if __name__ == "__main__":
    main()
