"""``rupture cascade`` end to end, offline: both input routes reachable, refusals honest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from rupture.adapters.cascade import chamoli, gorkha
from rupture.adapters.cascade.geoparquet import read_cascade_exposure
from rupture.cli import app as root_app
from rupture.commands import cascade as cascade_cli

runner = CliRunner()


def test_the_cascade_app_is_mounted_on_the_root_cli() -> None:
    """docs/CASCADE.md used to carry a caveat saying it was not; it is."""
    result = runner.invoke(root_app, ["cascade", "--help"])
    assert result.exit_code == 0
    assert "susceptibility" in result.stdout


def test_cases_lists_both_routes() -> None:
    result = runner.invoke(cascade_cli.app, ["cases"])
    assert result.exit_code == 0
    assert gorkha.EVENT_ID in result.stdout
    assert chamoli.SCENARIO_ID in result.stdout
    assert "scenario-gsim" in result.stdout
    assert "committed-shakemap" in result.stdout


def test_run_on_the_committed_shakemap_case(repo_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "gorkha.json"
    result = runner.invoke(
        cascade_cli.app,
        [
            "run",
            "--scenario",
            gorkha.EVENT_ID,
            "--model",
            "landslide",
            "--root",
            str(repo_root),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "committed-shakemap" in result.stdout
    payload = json.loads(out.read_text())
    assert payload["model_id"] == "nowicki_jessee_2018"
    assert "susceptibility" in payload["notes"]


def test_run_on_the_scenario_case(repo_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "chamoli.json"
    result = runner.invoke(
        cascade_cli.app,
        [
            "run",
            "--scenario",
            chamoli.SCENARIO_ID,
            "--root",
            str(repo_root),
            "--out",
            str(out),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "scenario-gsim" in result.stdout
    payload = json.loads(out.read_text())
    assert payload["scenario_id"] == chamoli.SCENARIO_ID
    assert payload["shaking_source"].startswith(chamoli.SCENARIO_ID)


def test_run_on_a_supplied_ground_motion_field(repo_root: Path, tmp_path: Path) -> None:
    """The route that lets any other part of rupture, or OpenQuake, drive this layer."""
    pgv, pga = chamoli.ground_motion_fields(repo_root)
    pgv_path = tmp_path / "pgv.json"
    pga_path = tmp_path / "pga.json"
    pgv_path.write_text(pgv.model_dump_json(), encoding="utf-8")
    pga_path.write_text(pga.model_dump_json(), encoding="utf-8")
    result = runner.invoke(
        cascade_cli.app,
        [
            "run",
            "--pgv-field",
            str(pgv_path),
            "--pga-field",
            str(pga_path),
            "--model",
            "landslide",
            "--root",
            str(repo_root),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "supplied-field" in result.stdout


def test_a_pga_field_handed_in_as_the_pgv_field_is_refused(repo_root: Path, tmp_path: Path) -> None:
    _, pga = chamoli.ground_motion_fields(repo_root)
    path = tmp_path / "pga.json"
    path.write_text(pga.model_dump_json(), encoding="utf-8")
    result = runner.invoke(
        cascade_cli.app, ["run", "--pgv-field", str(path), "--root", str(repo_root)]
    )
    assert result.exit_code == 1
    assert "need a PGV field" in result.stderr or "need a PGV field" in result.stdout


def test_an_unknown_scenario_says_what_would_satisfy_it(repo_root: Path) -> None:
    result = runner.invoke(
        cascade_cli.app, ["run", "--scenario", "no-such-event", "--root", str(repo_root)]
    )
    assert result.exit_code == 1
    message = result.stderr + result.stdout
    assert "--grid-xml" in message
    assert "--pgv-field" in message
    assert "does not invent a field" in message


def test_the_liquefaction_model_refuses_a_field_with_no_magnitude(
    repo_root: Path, tmp_path: Path
) -> None:
    pgv, _ = chamoli.ground_motion_fields(repo_root)
    path = tmp_path / "pgv.json"
    path.write_text(pgv.model_dump_json(), encoding="utf-8")
    result = runner.invoke(
        cascade_cli.app,
        ["run", "--pgv-field", str(path), "--model", "liquefaction", "--root", str(repo_root)],
    )
    assert result.exit_code == 1
    assert "magnitude" in (result.stderr + result.stdout)


def test_exposure_writes_geoparquet_with_provenance(repo_root: Path, tmp_path: Path) -> None:
    parquet = tmp_path / "exposure.parquet"
    result = runner.invoke(
        cascade_cli.app,
        [
            "exposure",
            "--aoi",
            "lhende-khola-trishuli",
            "--root",
            str(repo_root),
            "--out-parquet",
            str(parquet),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert "GeoParquet" in result.stdout
    restored = read_cascade_exposure(parquet)
    assert restored.aoi_id == "lhende-khola-trishuli"
    assert restored.shaking_source is not None
    assert "susceptibility" in restored.label


def test_exposure_on_the_scenario_route_reaches_chamoli(repo_root: Path) -> None:
    """The AOI that the ShakeMap route cannot serve at all: it is outside the Gorkha grid."""
    outside = runner.invoke(
        cascade_cli.app,
        ["exposure", "--aoi", chamoli.AOI_ID, "--root", str(repo_root)],
    )
    assert outside.exit_code == 1
    assert "does not " in (outside.stderr + outside.stdout)

    inside = runner.invoke(
        cascade_cli.app,
        [
            "exposure",
            "--aoi",
            chamoli.AOI_ID,
            "--scenario",
            chamoli.SCENARIO_ID,
            "--root",
            str(repo_root),
        ],
    )
    assert inside.exit_code == 0, inside.stdout
    assert "scenario-gsim" in inside.stdout
    assert "hydropower" in inside.stdout


def test_the_scenario_summary_prints_its_assumptions(repo_root: Path) -> None:
    result = runner.invoke(cascade_cli.app, ["scenario", "--root", str(repo_root)])
    assert result.exit_code == 0, result.stdout
    assert "HYPOTHETICAL" in result.stdout
    assert "assumed:" in result.stdout


def test_reproduce_still_runs(repo_root: Path) -> None:
    result = runner.invoke(
        cascade_cli.app, ["reproduce", "--model", "landslide", "--root", str(repo_root)]
    )
    assert result.exit_code == 0, result.stdout
    assert "nowicki_jessee_2018" in result.stdout


@pytest.mark.parametrize("verb", ["run", "exposure", "cases", "reproduce", "scenario"])
def test_every_verb_has_help(verb: str) -> None:
    assert runner.invoke(cascade_cli.app, [verb, "--help"]).exit_code == 0
