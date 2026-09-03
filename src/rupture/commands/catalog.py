"""`rupture catalog ...` — Build and inspect homogenised catalogues."""

from __future__ import annotations

import typer

from rupture.commands._stub import not_implemented

app = typer.Typer(help="Build and inspect homogenised catalogues.", no_args_is_help=True)


@app.command("build")
def build() -> None:
    """Not implemented yet — see the phase named in the message."""
    not_implemented("catalog build")
