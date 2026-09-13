"""CLI and gate on committed fixtures (no network)."""

from __future__ import annotations

from typer.testing import CliRunner

from rupture.commands.observe import app
from rupture.validation import observe as gate
from rupture.validation.result import GateStatus
from tests.unit.observations.conftest import REPO_ROOT


def test_ngl_info_and_asof_and_feed_info_run_offline() -> None:
    runner = CliRunner()
    root = str(REPO_ROOT)
    info = runner.invoke(app, ["ngl-info", "--station", "P595", "--root", root])
    assert info.exit_code == 0, info.output
    assert "P595" in info.output
    assert "21" in info.output
    asof = runner.invoke(
        app,
        [
            "ngl-asof",
            "--station",
            "P595",
            "--as-of",
            "2019-07-04T00:00:00Z",
            "--offline-fixtures",
            "--root",
            root,
        ],
    )
    assert asof.exit_code == 0, asof.output
    assert "21 of 21" in asof.output
    feed = runner.invoke(app, ["feed-info", "--offline-fixtures", "--root", root])
    assert feed.exit_code == 0, feed.output
    assert "usgs-realtime-feed" in feed.output
    assert "all_hour" in feed.output
    assert "significant_month" in feed.output


def test_observe_gate_passes_on_committed_fixtures() -> None:
    result = gate.run(REPO_ROOT)
    assert result.status is GateStatus.PASSED
    assert any("boundary excluded" in line for line in result.findings)
