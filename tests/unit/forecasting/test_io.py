"""Catalogue / region / result file round trips (the names the catalogue merge must honour)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from rupture.adapters.storage.geoparquet import write_catalog
from rupture.domain import Catalog, EvaluationResult, EventType, Region, TestName
from rupture.pipelines import io
from rupture.pipelines.build_catalog import build_catalog

REPO_ROOT = Path(__file__).resolve().parents[3]


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


def test_events_parquet_uses_the_geoparquet_writer_layout(
    tmp_path: Path, fixture_catalog: Catalog
) -> None:
    path = io.write_events_parquet(fixture_catalog.events[:3], tmp_path / "target.parquet")
    columns = set(pd.read_parquet(path).columns)
    assert {
        "geometry",
        "provenance_json",
        "other_magnitudes_json",
        "contributing_ids_json",
    } <= columns
    assert io.read_events_parquet(path) == list(fixture_catalog.events[:3])


def test_nepal_fixture_build_loads_through_io(tmp_path: Path) -> None:
    """`catalog build --offline-fixtures` output (geoparquet writer) read by `io.load_catalog`."""
    nepal = io.load_region(REPO_ROOT / "data" / "regions" / "nepal-himalaya")
    built = build_catalog(
        nepal,
        datetime(2015, 4, 1, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
        ["comcat", "isc", "gcmt"],
        offline_fixtures=REPO_ROOT / "data" / "fixtures",
        etas_cross_check=False,
    )
    write_catalog(built, tmp_path / "nepal")
    loaded = io.load_catalog(tmp_path / "nepal")
    assert loaded == built
    assert len(loaded) == len(built) > 100
    landslide = [e for e in loaded.events if e.source_event_id == "us7000tbwb"]
    assert len(landslide) == 1
    assert landslide[0].event_type is EventType.LANDSLIDE
    assert landslide[0].mw is None
    assert loaded.completeness, "Mc estimates survive the round trip"
    assert loaded.preferred_mc() == built.preferred_mc()
    assert loaded.homogenisation_log == built.homogenisation_log


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
