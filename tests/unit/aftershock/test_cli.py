"""The `rupture aftershock` verbs are wired and validate their arguments.

No EM fit and no server is started here: ``refit --dry-run`` walks the schedule and prints it, and
``serve`` is only exercised for the argument checks that happen before ``uvicorn.run``.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from rupture.cli import app as root_app
from rupture.commands import aftershock as cli

runner = CliRunner()


def test_the_verbs_are_mounted_on_the_root_application() -> None:
    result = runner.invoke(root_app, ["aftershock", "--help"])
    assert result.exit_code == 0
    for verb in ("forecast", "refit", "validate", "serve"):
        assert verb in result.output


def test_refit_dry_run_lists_the_schedule_without_fitting(repo_root: Path) -> None:
    result = runner.invoke(
        cli.app, ["refit", "--sequence", "gorkha", "--dry-run", "--root", str(repo_root)]
    )
    assert result.exit_code == 0, result.output
    assert "+0h" in result.output
    assert "already-fitted" in result.output  # the committed early-hours fits
    assert "dry run" in result.output


def test_refit_dry_run_is_bounded_by_through(repo_root: Path) -> None:
    result = runner.invoke(
        cli.app,
        ["refit", "--sequence", "gorkha", "--through", "6h", "--dry-run", "--root", str(repo_root)],
    )
    assert result.exit_code == 0, result.output
    assert "+12h" not in result.output
    assert "of 4 scheduled cutoffs" in result.output


def test_refit_without_a_sequence_or_a_catalogue_is_refused() -> None:
    result = runner.invoke(cli.app, ["refit"])
    assert result.exit_code == 1
    assert "give --sequence" in result.output


def test_refit_with_a_catalogue_needs_the_region_the_mainshock_and_an_output(
    tmp_path: Path,
) -> None:
    result = runner.invoke(cli.app, ["refit", "--catalog", str(tmp_path)])
    assert result.exit_code == 1
    assert "--catalog needs --region, --mainshock and --out" in result.output


def test_serve_refuses_an_unknown_surface() -> None:
    result = runner.invoke(cli.app, ["serve", "--surface", "everything"])
    assert result.exit_code == 1
    assert "unknown --surface" in result.output


def test_serve_refuses_a_catalogue_without_a_region() -> None:
    result = runner.invoke(cli.app, ["serve", "--surface", "aftershock", "--catalog", "/nowhere"])
    assert result.exit_code == 1
    assert "--catalog needs --region" in result.output


def test_the_combined_surface_does_not_take_per_request_refit_flags() -> None:
    """`--allow-refit` is aftershock-only; the combined app reads the environment instead."""
    result = runner.invoke(cli.app, ["serve", "--allow-refit"])
    assert result.exit_code == 1
    assert "RUPTURE_AFTERSHOCK_ALLOW_REFIT" in result.output
