"""Shared not-implemented exit for command stubs."""

from __future__ import annotations

import typer

EXIT_NOT_IMPLEMENTED = 2

PHASE_FOR_COMMAND: dict[str, str] = {
    "catalog": "Phase 2A (catalog-engineer)",
    "region": "Phase 2A (catalog-engineer)",
    "forecast": "Phase 2B (forecast-engineer)",
    "evaluate": "Phase 2B (forecast-engineer)",
    "hazard": "Phase 2C (hazard-engineer)",
}


def not_implemented(command: str) -> None:
    noun = command.split(maxsplit=1)[0]
    phase = PHASE_FOR_COMMAND.get(noun, "a later phase")
    typer.echo(f"rupture {command}: not implemented yet — delivered in {phase}", err=True)
    raise typer.Exit(EXIT_NOT_IMPLEMENTED)
