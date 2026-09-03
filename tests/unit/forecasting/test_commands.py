"""CLI verbs run end to end on the fixture (fit itself is exercised in the integration suite)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from rupture.cli import app
from rupture.domain import Catalog, Region
from rupture.pipelines import io

runner = CliRunner()


def _data_dir(tmp_path: Path, catalog: Catalog, region: Region) -> Path:
    data = tmp_path / "data"
    (data / "regions" / region.id).mkdir(parents=True)
    (data / "regions" / region.id / io.REGION_FILE).write_text(
        json.dumps(region.to_geojson()), encoding="utf-8"
    )
    io.save_catalog(catalog, data / "catalogs" / region.id)
    return data


def test_issue_then_evaluate(
    tmp_path: Path, fixture_catalog: Catalog, region: Region, baselines_with_committed_fit: Path
) -> None:
    data = _data_dir(tmp_path, fixture_catalog, region)
    common = ["--data-dir", str(data)]
    res = runner.invoke(
        app,
        [
            "forecast",
            "issue",
            "--region",
            region.id,
            "--issue",
            "2019-07-01T00:00:00Z",
            "--horizon",
            "30d",
            "--n-simulations",
            "5",
            "--seed",
            "1",
            "--baselines",
            str(baselines_with_committed_fit),
            *common,
        ],
    )
    assert res.exit_code == 0, res.output
    forecast_id = "etas-mizrahi-california-fixture-20190701T000000Z-30d"
    assert forecast_id in res.output
    assert (data / "forecasts" / region.id / "etas-mizrahi" / f"{forecast_id}.zarr").is_dir()

    out = tmp_path / "report"
    res = runner.invoke(
        app,
        [
            "evaluate",
            "run",
            "--forecast",
            forecast_id,
            "--tests",
            "N,M",
            "--n-simulations",
            "20",
            "--seed",
            "1",
            "--out",
            str(out),
            "--no-plots",
            *common,
        ],
    )
    assert res.exit_code == 0, res.output
    assert " N: statistic=" in res.output
    assert "passed=False" in res.output
    results = io.load_results(out / "results.json")
    assert [r.test_name.value for r in results] == ["N", "M"]
    assert (out / "target.parquet").exists()
    runs = (data / "forecasts" / region.id / "runs.jsonl").read_text(encoding="utf-8")
    assert '"kind":"issue"' in runs
    assert '"kind":"evaluate"' in runs


def test_issue_before_cutoff_exits_nonzero(
    tmp_path: Path, fixture_catalog: Catalog, region: Region, baselines_with_committed_fit: Path
) -> None:
    data = _data_dir(tmp_path, fixture_catalog, region)
    res = runner.invoke(
        app,
        [
            "forecast",
            "issue",
            "--region",
            region.id,
            "--issue",
            "2019-06-01T00:00:00Z",
            "--n-simulations",
            "1",
            "--baselines",
            str(baselines_with_committed_fit),
            "--data-dir",
            str(data),
        ],
    )
    assert res.exit_code != 0
    assert isinstance(res.exception, Exception)
    assert "leakage" in str(res.exception)


def test_unknown_model_is_refused(tmp_path: Path) -> None:
    res = runner.invoke(
        app,
        ["forecast", "fit", "--region", "x", "--cutoff", "2022-01-01", "--model", "nope"],
    )
    assert res.exit_code == 2
    assert "not available" in res.output


def test_stubs_are_gone() -> None:
    for verb in (
        ["forecast", "fit"],
        ["forecast", "issue"],
        ["evaluate", "run"],
        ["evaluate", "schedule"],
    ):
        res = runner.invoke(app, [*verb, "--help"])
        assert res.exit_code == 0
        assert "not implemented" not in res.output
