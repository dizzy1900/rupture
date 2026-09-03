"""``rupture`` command-line interface.

rupture does not predict earthquakes. Sub-commands are added by phase; those not yet implemented
exit with status 2 and say which phase delivers them, rather than pretending to run.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from rupture import __version__
from rupture.validation import GateResult, GateStatus, language

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

REPO_ROOT = Path(__file__).resolve().parents[2]

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_NOT_IMPLEMENTED = 2


def _finish(result: GateResult) -> None:
    print(result.render())
    if result.status == GateStatus.NOT_IMPLEMENTED:
        raise typer.Exit(EXIT_NOT_IMPLEMENTED)
    raise typer.Exit(EXIT_OK if result.ok else EXIT_FAIL)


def _not_implemented(name: str, phase: str) -> GateResult:
    return GateResult(
        name=name,
        status=GateStatus.NOT_IMPLEMENTED,
        reason=f"not implemented yet: delivered in {phase}",
    )


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
@validate_app.command("language")
def validate_language(
    root: Annotated[Path, typer.Option(help="Tree to scan.")] = REPO_ROOT,
) -> None:
    """Banned-phrase scan over docs, code, contracts and configuration."""
    _finish(language.run(root))


@validate_app.command("catalog")
def validate_catalog() -> None:
    """Catalogue schema, provenance, Mc present, no duplicates, landslide events retained."""
    _finish(_not_implemented("validate-catalog", "Phase 2A (catalog-engineer)"))


@validate_app.command("etas")
def validate_etas() -> None:
    """ETAS fit diagnostics present; parameters plausible; forecast grid sums finite."""
    _finish(_not_implemented("validate-etas", "Phase 2B (forecast-engineer)"))


@validate_app.command("eval")
def validate_eval() -> None:
    """CSEP harness runs on fixtures; leakage assertion passes."""
    _finish(_not_implemented("validate-eval", "Phase 2B (forecast-engineer)"))


@validate_app.command("hazard")
def validate_hazard() -> None:
    """OpenQuake demo runs in the pinned Docker image; skips with a reason if Docker is absent."""
    _finish(_not_implemented("validate-hazard", "Phase 2C (hazard-engineer)"))


# ------------------------------------------------------------------ schema
@schema_app.command("export")
def schema_export(
    check: Annotated[bool, typer.Option("--check", help="Fail if files would change.")] = False,
) -> None:
    """Write JSON Schema for every domain contract into contracts/."""
    _finish(_not_implemented("schema export", "Phase 1 (architect)"))


# ------------------------------------------------------------------ release
@app.command()
def promote() -> None:
    """Print the promotion record. Reached by `make promote` only when the gates are green."""
    print(f"promote: rupture {__version__} — validate-rupture green; see RELEASE_STATUS.md")


@app.command("underwriting-check")
def underwriting_check() -> None:
    """Validate the AvoidedLossRequest round-trip; exits non-zero: not implemented (Prompt 2)."""
    _finish(_not_implemented("underwriting-check", "Prompt 2 (loss layer)"))


def main() -> None:
    """Console entry point."""
    sys.exit(app())


if __name__ == "__main__":
    main()
