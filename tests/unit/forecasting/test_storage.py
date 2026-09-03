"""zarr + STAC grid store and the JSONL run log."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rupture.adapters.storage import stac
from rupture.adapters.storage.run_log import JsonlTracker
from rupture.adapters.storage.zarr_store import ZarrGridStore
from rupture.domain import ForecastGrid
from rupture.ports import GridStore, RunRecord, Tracker


def small_grid(issue: datetime, model_id: str = "m") -> ForecastGrid:
    """A minimal grid as a *validator input* for the store; not data."""
    return ForecastGrid(
        id=ForecastGrid.make_id(model_id, "r", issue, timedelta(days=30)),
        region_id="r",
        model_id=model_id,
        model_version="0",
        parameter_snapshot_hash="a" * 64,
        fit_cutoff=issue,
        training_catalog_hash="b" * 64,
        issue_time=issue,
        horizon=timedelta(days=30),
        cell_size_deg=0.1,
        cell_origins=((0.0, 0.0), (0.1, 0.0), (0.0, 0.1)),
        magnitude_bin_edges=(4.95, 5.05),
        magnitude_bin_width=0.1,
        expected_counts=((0.1, 0.01), (0.0, 0.0), (1.5e-7, 2.0)),
        n_simulations=3,
        created_at=issue,
        notes="test",
    )


def test_zarr_round_trip_and_listing(tmp_path: Path) -> None:
    store = ZarrGridStore(tmp_path)
    assert isinstance(store, GridStore)
    t0 = datetime(2022, 1, 1, tzinfo=UTC)
    g1 = small_grid(t0)
    g2 = small_grid(t0 + timedelta(days=30))
    loc = store.save(g1)
    store.save(g2)
    assert loc.endswith(f"r/m/{g1.id}.zarr")
    assert store.load(g1.id) == g1
    assert list(store.list_ids()) == sorted([g1.id, g2.id])
    assert list(store.list_ids(region_id="r", model_id="m")) == sorted([g1.id, g2.id])
    assert list(store.list_ids(model_id="other")) == []
    with pytest.raises(FileNotFoundError):
        store.load("missing")


def test_real_grid_round_trips_exactly(tmp_path: Path, ridgecrest_grid: ForecastGrid) -> None:
    store = ZarrGridStore(tmp_path)
    store.save(ridgecrest_grid)
    assert store.load(ridgecrest_grid.id) == ridgecrest_grid


def test_stac_item_and_collection(tmp_path: Path) -> None:
    store = ZarrGridStore(tmp_path)
    g = small_grid(datetime(2022, 1, 1, tzinfo=UTC))
    zarr_path = Path(store.save(g))
    item_path = stac.item_path(zarr_path)
    item = json.loads(item_path.read_text(encoding="utf-8"))
    assert item["type"] == "Feature"
    assert item["id"] == g.id
    assert item["bbox"] == [0.0, 0.0, 0.2, 0.2]
    assert item["properties"]["rupture:parameter_snapshot_hash"] == "a" * 64
    assert item["properties"]["start_datetime"].startswith("2022-01-01")
    assert item["assets"]["grid"]["href"] == zarr_path.name
    collection = json.loads((zarr_path.parent / "collection.json").read_text(encoding="utf-8"))
    assert collection["type"] == "Collection"
    assert collection["rupture:item_count"] == 1
    assert collection["extent"]["spatial"]["bbox"] == [[0.0, 0.0, 0.2, 0.2]]
    assert any(link["rel"] == "item" for link in collection["links"])


def test_jsonl_tracker_appends_and_filters(tmp_path: Path) -> None:
    tracker = JsonlTracker(tmp_path / "runs.jsonl")
    assert isinstance(tracker, Tracker)
    assert list(tracker.records()) == []
    now = datetime(2026, 9, 3, tzinfo=UTC)
    tracker.log(RunRecord(run_id="1", kind="fit", at=now, region_id="r"))
    tracker.log(RunRecord(run_id="2", kind="issue", at=now, region_id="r"))
    tracker.log(RunRecord(run_id="3", kind="issue", at=now, region_id="q"))
    assert [r.run_id for r in tracker.records()] == ["1", "2", "3"]
    assert [r.run_id for r in tracker.records(kind="issue")] == ["2", "3"]
    assert [r.run_id for r in tracker.records(kind="issue", region_id="r")] == ["2"]
    assert JsonlTracker.default_path(Path("data"), "r") == Path("data/forecasts/r/runs.jsonl")
