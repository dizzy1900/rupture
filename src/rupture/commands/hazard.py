"""`rupture hazard ...` — OpenQuake hazard runs."""

from __future__ import annotations

import typer

from rupture.commands._stub import not_implemented

app = typer.Typer(help="OpenQuake hazard runs.", no_args_is_help=True)


@app.command("demo")
def demo() -> None:
    """Not implemented yet — see the phase named in the message."""
    not_implemented("hazard demo")


@app.command("classical")
def classical() -> None:
    """Not implemented yet — see the phase named in the message."""
    not_implemented("hazard classical")
