"""One application, both surfaces: the brief's "the same FastAPI service".

The two surfaces used to be two applications. These tests drive
:func:`rupture.services.app.create_app` in process and assert that a single app, holding a single
API key, answers the avoided-loss contract *and* the aftershock forecast, and that a deployment
which cannot load the aftershock catalogues still serves the risk surface and says so.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rupture.adapters.exposure import SeracExposureSource
from rupture.adapters.exposure.serac_export import FALLBACK_REL
from rupture.domain.avoided_loss_v1 import AvoidedLossRequestV1
from rupture.domain.loss import ExposurePortfolio, TriggerKind
from rupture.risk import service as risk_service
from rupture.services.aftershock.forecaster import AftershockForecaster
from rupture.services.aftershock.sequences import SequenceSpec
from rupture.services.aftershock.service import LoadedSequence, build_state
from rupture.services.app import create_app
from rupture.services.auth import SHARED_KEYS_ENV

KEY = "combined-test-key"
AOI = "lhende-khola-trishuli"


@pytest.fixture
def combined(
    repo_root: Path,
    loaded_sequences: dict[str, LoadedSequence],
    fast_forecaster: AftershockForecaster,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """The combined app with one key for both surfaces and a deliberately crude forecaster."""
    monkeypatch.setenv(SHARED_KEYS_ENV, KEY)
    monkeypatch.setenv(risk_service.REPO_ROOT_ENV, str(repo_root))
    state = build_state(sequences=loaded_sequences, forecaster=fast_forecaster)
    return TestClient(create_app(root=repo_root, aftershock=state))


def test_health_reports_both_surfaces_and_needs_no_key(combined: TestClient) -> None:
    body = combined.get("/health").json()
    assert body["status"] == "ok"
    assert body["surfaces"]["risk"]["contract_version"]
    assert body["surfaces"]["aftershock"]["sequences"] == ["gorkha", "kahramanmaras"]
    assert combined.get("/healthz").json() == body


def test_one_openapi_document_carries_every_route(combined: TestClient) -> None:
    paths = set(combined.get("/openapi.json").json()["paths"])
    assert {
        "/health",
        "/v1/scenarios",
        "/v1/avoided-loss",
        "/aftershock/forecast",
        "/aftershock/grid/{grid_id}",
    } <= paths


def test_one_key_opens_both_surfaces(combined: TestClient, gorkha: SequenceSpec) -> None:
    """The point of the merge: the same X-API-Key on the loss route and the forecast route."""
    scenarios = combined.get("/v1/scenarios", headers={"X-API-Key": KEY})
    assert scenarios.status_code == 200
    forecast = combined.post(
        "/aftershock/forecast", json=_forecast_body(gorkha), headers={"X-API-Key": KEY}
    )
    assert forecast.status_code == 200, forecast.text


def test_both_surfaces_refuse_the_same_wrong_key(combined: TestClient) -> None:
    assert combined.get("/v1/scenarios", headers={"X-API-Key": "nope"}).status_code == 401
    assert (
        combined.post(
            "/aftershock/forecast", json={"mainshock_id": "x"}, headers={"X-API-Key": "nope"}
        ).status_code
        == 401
    )


def test_the_loss_endpoint_and_the_forecast_endpoint_answer_on_the_same_app(
    combined: TestClient, repo_root: Path, gorkha: SequenceSpec
) -> None:
    """The whole gap in one test: one process answers the avoided-loss contract and a forecast."""
    portfolio = SeracExposureSource(repo_root=repo_root).load(
        repo_root / FALLBACK_REL / AOI / "exposed_assets.geojson", portfolio_id="trishuli-corridor"
    )
    loss = combined.post("/v1/avoided-loss", json=_loss_body(portfolio), headers={"X-API-Key": KEY})
    assert loss.status_code == 200, loss.text
    assert loss.json()["baseline_total"]["best"] > 0.0

    forecast = combined.post(
        "/aftershock/forecast", json=_forecast_body(gorkha), headers={"X-API-Key": KEY}
    )
    assert forecast.status_code == 200, forecast.text
    body = forecast.json()
    assert body["mainshock_event_id"] == gorkha.mainshock.event_id

    grid = combined.get(f"/aftershock/grid/{body['forecast_grid_id']}", headers={"X-API-Key": KEY})
    assert grid.status_code == 200, grid.text
    assert grid.json()["id"] == body["forecast_grid_id"]


def test_a_deployment_without_the_catalogues_still_serves_risk_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No sequence fixtures under the root: the aftershock surface is unavailable, not fatal."""
    monkeypatch.setenv(SHARED_KEYS_ENV, KEY)
    monkeypatch.setenv(risk_service.REPO_ROOT_ENV, str(tmp_path))
    client = TestClient(create_app(root=tmp_path))

    health = client.get("/health").json()
    assert health["surfaces"]["aftershock"]["status"] == "unavailable"
    assert health["surfaces"]["aftershock"]["reason"]
    assert health["surfaces"]["risk"]["status"] == "ok"

    refused = client.post("/aftershock/forecast", json={}, headers={"X-API-Key": KEY})
    assert refused.status_code == 503
    assert "not available in this deployment" in refused.json()["detail"]
    # the risk surface is untouched: it answers its own 503 only when no key is configured
    assert client.get("/v1/scenarios", headers={"X-API-Key": "nope"}).status_code == 401


def _forecast_body(spec: SequenceSpec) -> dict[str, object]:
    return {
        "mainshock_id": spec.mainshock.event_id,
        "issue_time": (spec.mainshock.origin_time + timedelta(days=1)).isoformat(),
        "horizon": "1d",
        "n_simulations": 1,
    }


def _loss_body(portfolio: ExposurePortfolio) -> dict[str, object]:
    request = AvoidedLossRequestV1(
        request_id="combined-0001",
        requested_at=datetime(2026, 9, 3, tzinfo=UTC),
        portfolio=portfolio,
        trigger_kind=TriggerKind.SCENARIO,
        trigger_id="gorkha-2015-repeat",
        consumer="tests",
    )
    return dict(request.model_dump(mode="json"))
