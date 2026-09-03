"""``rupture`` command-line interface.

rupture does not predict earthquakes. Sub-commands live in :mod:`rupture.commands`; validation
gates in :mod:`rupture.validation` (resolved by name through the registry). Anything not yet
implemented exits with status 2 and names the phase that delivers it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import jsonschema
import typer

from rupture import __version__
from rupture.commands import cascade, catalog, evaluate, forecast, hazard, region
from rupture.domain import contracts, loss, utc_now
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
) -> None:
    """Re-run every gate and print the promotion record, naming each skip and its reason.

    `make promote` already refuses unless `validate-rupture` is green, but this command does not
    take that on trust: it runs the gates itself, so the record it prints reports the state it
    actually observed rather than asserting one. A gate that is SKIPPED does not block promotion
    (that is the rule in CLAUDE.md) but its reason is always printed, so a promotion record can
    never hide that, say, the OpenQuake container never ran.
    """
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


@app.command("underwriting-check")
def underwriting_check() -> None:
    """Round-trip an AvoidedLossRequest through its schema; exit 2: not implemented (Prompt 2)."""
    example_path = (
        REPO_ROOT / "tests" / "contract" / "fixtures" / "avoided-loss.request.example.json"
    )
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    request = loss.AvoidedLossRequest.model_validate(payload)
    schema = contracts.schema_for("avoided-loss.v0.json")
    jsonschema.validate(
        {
            "request": request.model_dump(mode="json"),
            "response": _not_implemented_response(request),
        },
        schema,
    )
    print("underwriting-check: AvoidedLossRequest round-trip OK")
    print("underwriting-check: not implemented: Prompt 2 (loss layer)")
    raise typer.Exit(EXIT_NOT_IMPLEMENTED)


def _not_implemented_response(request: loss.AvoidedLossRequest) -> dict[str, object]:
    resp = loss.AvoidedLossResponse(
        request_id=request.request_id,
        status=loss.ResponseStatus.NOT_IMPLEMENTED,
        responded_at=utc_now(),
        message="not implemented: Prompt 2 (loss layer)",
    )
    return resp.model_dump(mode="json")


def main() -> None:
    """Console entry point."""
    sys.exit(app())


if __name__ == "__main__":
    main()
