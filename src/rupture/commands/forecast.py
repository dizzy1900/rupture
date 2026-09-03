"""`rupture forecast ...` — Fit models and issue forecasts."""

from __future__ import annotations

import typer

from rupture.commands._stub import not_implemented

app = typer.Typer(help="Fit models and issue forecasts.", no_args_is_help=True)


@app.command("fit")
def fit() -> None:
    """Not implemented yet — see the phase named in the message."""
    not_implemented("forecast fit")


@app.command("issue")
def issue() -> None:
    """Not implemented yet — see the phase named in the message."""
    not_implemented("forecast issue")
