"""`rupture evaluate ...` — Evaluate forecasts with CSEP-style tests."""

from __future__ import annotations

import typer

from rupture.commands._stub import not_implemented

app = typer.Typer(help="Evaluate forecasts with CSEP-style tests.", no_args_is_help=True)


@app.command("run")
def run() -> None:
    """Not implemented yet — see the phase named in the message."""
    not_implemented("evaluate run")


@app.command("schedule")
def schedule() -> None:
    """Not implemented yet — see the phase named in the message."""
    not_implemented("evaluate schedule")
