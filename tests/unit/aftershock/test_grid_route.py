"""The gridded forecast over HTTP.

``docs/AFTERSHOCK.md`` § 6 tells an operator to use the gridded ``ForecastGrid``, not the
zone-wide ladder, for anything that depends on location. Until ``GET /aftershock/grid/{id}``
existed the grid was computed inside the request and dropped, so an HTTP client could not follow
that instruction: the ``forecast_grid_id`` in the response referred to nothing it could fetch.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from rupture.domain import ForecastGrid
from rupture.pipelines.io import parse_utc
from rupture.services.aftershock.forecaster import AftershockForecaster
from rupture.services.aftershock.grids import (
    DirectoryGridStore,
    InMemoryGridStore,
    grid_store_from_env,
    is_safe_grid_id,
)
from rupture.services.aftershock.sequences import SequenceSpec
from rupture.services.aftershock.service import LoadedSequence, create_app

KEY = "grid-test-key"
HEADERS = {"X-API-Key": KEY}


@pytest.fixture
def client(
    loaded_sequences: dict[str, LoadedSequence], fast_forecaster: AftershockForecaster
) -> TestClient:
    return TestClient(
        create_app(api_key=KEY, forecaster=fast_forecaster, sequences=loaded_sequences)
    )


def _issue(client: TestClient, spec: SequenceSpec) -> dict[str, object]:
    body = {
        "mainshock_id": spec.mainshock.event_id,
        "issue_time": (spec.mainshock.origin_time + timedelta(days=1)).isoformat(),
        "horizon": "1d",
        "n_simulations": 1,
    }
    response = client.post("/aftershock/forecast", json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_the_grid_behind_a_forecast_can_be_fetched_by_its_id(
    client: TestClient, gorkha: SequenceSpec
) -> None:
    forecast = _issue(client, gorkha)
    grid_id = str(forecast["forecast_grid_id"])
    response = client.get(f"/aftershock/grid/{grid_id}", headers=HEADERS)
    assert response.status_code == 200, response.text
    grid = ForecastGrid.model_validate(response.json())
    assert grid.id == grid_id
    assert grid.region_id == forecast["region_id"]
    assert grid.issue_time == parse_utc(str(forecast["issue_time"]))


def test_the_served_grid_is_spatial_not_a_single_lumped_cell(
    client: TestClient, gorkha: SequenceSpec
) -> None:
    """Many cells, and the rate is concentrated: this is what the ladder cannot tell a client."""
    forecast = _issue(client, gorkha)
    grid = ForecastGrid.model_validate(
        client.get(f"/aftershock/grid/{forecast['forecast_grid_id']}", headers=HEADERS).json()
    )
    per_cell = grid.counts().sum(axis=1)
    assert len(grid.cell_origins) > 1
    assert per_cell.max() > per_cell.min()
    assert grid.total_expected() > 0.0


def test_the_grid_validates_against_the_published_contract(
    client: TestClient, gorkha: SequenceSpec, repo_root: Path
) -> None:
    schema = json.loads(
        (repo_root / "contracts" / "forecast-grid.v0.json").read_text(encoding="utf-8")
    )
    forecast = _issue(client, gorkha)
    body = client.get(f"/aftershock/grid/{forecast['forecast_grid_id']}", headers=HEADERS).json()
    jsonschema.Draft202012Validator(schema).validate(body)


def test_the_grid_route_needs_the_key(client: TestClient, gorkha: SequenceSpec) -> None:
    forecast = _issue(client, gorkha)
    assert client.get(f"/aftershock/grid/{forecast['forecast_grid_id']}").status_code == 401


def test_an_unknown_grid_id_is_a_404_that_says_what_to_do(client: TestClient) -> None:
    response = client.get("/aftershock/grid/no-such-grid", headers=HEADERS)
    assert response.status_code == 404
    assert "POST /aftershock/forecast first" in response.json()["detail"]


def test_a_directory_store_survives_a_restart(
    tmp_path: Path,
    loaded_sequences: dict[str, LoadedSequence],
    fast_forecaster: AftershockForecaster,
    gorkha: SequenceSpec,
) -> None:
    """With RUPTURE_AFTERSHOCK_GRID_DIR the grid outlives the process that issued it."""
    store = DirectoryGridStore(tmp_path / "grids")
    issuing = TestClient(
        create_app(
            api_key=KEY,
            forecaster=fast_forecaster,
            sequences=loaded_sequences,
            grids=store,
        )
    )
    forecast = _issue(issuing, gorkha)

    restarted = TestClient(
        create_app(
            api_key=KEY,
            forecaster=fast_forecaster,
            sequences=loaded_sequences,
            grids=DirectoryGridStore(tmp_path / "grids"),
        )
    )
    response = restarted.get(f"/aftershock/grid/{forecast['forecast_grid_id']}", headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["id"] == forecast["forecast_grid_id"]


def test_the_in_memory_store_is_bounded(client: TestClient, gorkha: SequenceSpec) -> None:
    store = InMemoryGridStore(capacity=1)
    grid = ForecastGrid.model_validate(
        client.get(
            f"/aftershock/grid/{_issue(client, gorkha)['forecast_grid_id']}", headers=HEADERS
        ).json()
    )
    other = grid.model_copy(update={"id": f"{grid.id}-second"})
    store.put(grid)
    store.put(other)
    assert store.get(grid.id) is None
    assert store.get(other.id) is not None


def test_a_grid_id_that_is_not_a_path_segment_is_refused_not_sanitised(tmp_path: Path) -> None:
    store = DirectoryGridStore(tmp_path)
    assert not is_safe_grid_id("../escape")
    assert not is_safe_grid_id("a/b")
    assert store.get("../escape") is None


def test_the_store_is_chosen_by_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("RUPTURE_AFTERSHOCK_GRID_DIR", raising=False)
    assert isinstance(grid_store_from_env(), InMemoryGridStore)
    monkeypatch.setenv("RUPTURE_AFTERSHOCK_GRID_DIR", str(tmp_path))
    chosen = grid_store_from_env()
    assert isinstance(chosen, DirectoryGridStore)
    assert chosen.root == tmp_path
