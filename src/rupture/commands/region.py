"""`rupture region ...` — Test regions."""

from __future__ import annotations

import typer

from rupture.commands._stub import not_implemented

app = typer.Typer(help="Test regions.", no_args_is_help=True)


@app.command("list")
def list_() -> None:
    """Not implemented yet — see the phase named in the message."""
    not_implemented("region list")


@app.command("show")
def show() -> None:
    """Not implemented yet — see the phase named in the message."""
    not_implemented("region show")
