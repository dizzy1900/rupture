"""Catalogue / region / result file round trips (the names the catalogue merge must honour)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rupture.domain import Catalog, EvaluationResult, Region, TestName
from rupture.pipelines import io


def test_catalog_directory_round_trip(tmp_path: Path, fixture_catalog: Catalog) -> None:
    out = io.save_catalog(fixture_catalog, tmp_path / "cat")
    assert {p.name for p in out.iterdir()} == {
        io.EVENTS_FILE,
        io.META_FILE,
        io.LOG_FILE,
    }
    assert (io.EVENTS_FILE, io.META_FILE, io.LOG_FILE) == (
        "events.parquet",
        "catalog.meta.json",
        "homogenisation_log.jsonl",
    )
    loaded = io.load_catalog(out)
    assert loaded == fixture_catalog
    assert io.load_catalog(out / io.EVENTS_FILE) == fixture_catalog


def test_events_frame_has_the_agreed_columns(fixture_catalog: Catalog) -> None:
    df = io.events_to_frame(fixture_catalog.events[:3])
    assert list(df.columns) == list(io.EVENT_COLUMNS)
    assert str(df["origin_time"].dtype).startswith("datetime64[")
    assert "UTC" in str(df["origin_time"].dtype)
    assert json.loads(df["contributing_ids"].iloc[0]) == []


def test_missing_files_fail_loudly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"events\.parquet"):
        io.load_catalog(tmp_path)


def test_region_file_in_both_shapes(tmp_path: Path, region: Region) -> None:
    plain = tmp_path / "plain" / io.REGION_FILE
    plain.parent.mkdir()
    plain.write_text(region.model_dump_json(), encoding="utf-8")
    assert io.load_region(plain.parent) == region
    feature = tmp_path / "feature.json"
    feature.write_text(json.dumps(region.to_geojson()), encoding="utf-8")
    assert io.load_region(feature) == region
    with pytest.raises(FileNotFoundError):
        io.load_region(tmp_path / "nowhere")


def test_parse_utc() -> None:
    assert io.parse_utc("2022-01-01T00:00:00Z") == datetime(2022, 1, 1, tzinfo=UTC)
    assert io.parse_utc("2022-01-01") == datetime(2022, 1, 1, tzinfo=UTC)
    assert io.parse_utc("2022-01-01T02:00:00+02:00") == datetime(2022, 1, 1, tzinfo=UTC)


def test_results_round_trip(tmp_path: Path) -> None:
    now = datetime(2026, 9, 3, tzinfo=UTC)
    r = EvaluationResult(
        forecast_id="f",
        model_id="m",
        test_name=TestName.N,
        statistic=3.0,
        quantile_low=0.4,
        quantile_high=0.7,
        passed=True,
        n_target_events=3,
        target_window_start=now,
        target_window_end=now,
        target_catalog_hash="h",
        evaluated_at=now,
        evaluator_version="v",
    )
    path = io.save_results([r], tmp_path / "results.json")
    assert io.load_results(path) == [r]
