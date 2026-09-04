"""The HTTP surface: health, the API key, request validation, and one real forecast.

Everything runs through ``TestClient``, which drives the ASGI application in-process, so no
socket is opened and the offline suite's ``--disable-socket`` is satisfied.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import jsonschema
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rupture.domain import AftershockForecast
from rupture.services.aftershock.forecaster import AftershockForecaster
from rupture.services.aftershock.sequences import SequenceSpec
from rupture.services.aftershock.service import (
    API_KEY_ENV,
    API_KEY_HEADER,
    LoadedSequence,
    create_app,
    load_default_sequences,
)

KEY = "test-key"


@pytest.fixture(scope="module")
def loaded(repo_root: Path) -> dict[str, LoadedSequence]:
    return load_default_sequences(repo_root)


@pytest.fixture
def app(loaded: dict[str, LoadedSequence], fast_forecaster: AftershockForecaster) -> FastAPI:
    return create_app(api_key=KEY, forecaster=fast_forecaster, sequences=loaded)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_healthz_needs_no_key_and_reports_what_is_loaded(client: TestClient) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "aftershock"
    assert body["model_id"] == "etas-mizrahi"
    assert body["sequences"] == ["gorkha", "kahramanmaras"]
    assert body["api_key_configured"] is True
    assert body["allow_refit"] is False
    assert len(body["fits_loaded"]["gorkha"]) == 7  # +0, 1, 3, 6, 12 h, +1 d, +7 d
    assert "Poisson" in body["poisson_assumption"]
    assert body["grid_store"]


def test_forecast_without_a_key_is_unauthorised(client: TestClient, gorkha: SequenceSpec) -> None:
    response = client.post("/aftershock/forecast", json=_body(gorkha))
    assert response.status_code == 401
    assert API_KEY_HEADER in response.json()["detail"]


def test_forecast_with_the_wrong_key_is_unauthorised(
    client: TestClient, gorkha: SequenceSpec
) -> None:
    response = client.post(
        "/aftershock/forecast", json=_body(gorkha), headers={API_KEY_HEADER: "nope"}
    )
    assert response.status_code == 401


def test_no_key_configured_refuses_rather_than_serving_open(
    loaded: dict[str, LoadedSequence],
    fast_forecaster: AftershockForecaster,
    gorkha: SequenceSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    open_app = create_app(forecaster=fast_forecaster, sequences=loaded)
    response = TestClient(open_app).post("/aftershock/forecast", json=_body(gorkha))
    assert response.status_code == 503
    assert API_KEY_ENV in response.json()["detail"]


def test_the_key_can_come_from_the_environment(
    loaded: dict[str, LoadedSequence],
    fast_forecaster: AftershockForecaster,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(API_KEY_ENV, "from-env")
    app = create_app(forecaster=fast_forecaster, sequences=loaded)
    assert TestClient(app).get("/healthz").json()["api_key_configured"] is True


def test_both_mainshock_forms_at_once_is_rejected(client: TestClient, gorkha: SequenceSpec) -> None:
    body = _body(gorkha)
    body["mainshock"] = {
        "origin_time": gorkha.mainshock.origin_time.isoformat(),
        "latitude": gorkha.mainshock.latitude,
        "longitude": gorkha.mainshock.longitude,
        "magnitude": gorkha.mainshock.magnitude,
    }
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 422


def test_neither_mainshock_form_is_rejected(client: TestClient, gorkha: SequenceSpec) -> None:
    body = _body(gorkha)
    del body["mainshock_id"]
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 422


def test_unknown_sequence_is_not_found(client: TestClient, gorkha: SequenceSpec) -> None:
    body = _body(gorkha) | {"sequence": "ridgecrest"}
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 404
    assert "unknown sequence" in response.json()["detail"]


def test_unknown_mainshock_id_is_not_found(client: TestClient, gorkha: SequenceSpec) -> None:
    body = _body(gorkha) | {"mainshock_id": "nosuchevent", "sequence": "gorkha"}
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 404


def test_a_mainshock_id_with_no_catalogue_is_not_found(
    client: TestClient, gorkha: SequenceSpec
) -> None:
    body = _body(gorkha) | {"mainshock_id": "us9999zzzz"}
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 404
    assert "sequence" in response.json()["detail"]


def test_an_unparsable_horizon_is_rejected(client: TestClient, gorkha: SequenceSpec) -> None:
    body = _body(gorkha) | {"horizon": "a fortnight"}
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 422
    assert "unrecognised horizon" in response.json()["detail"]


def test_an_issue_time_before_the_mainshock_is_rejected(
    client: TestClient, gorkha: SequenceSpec
) -> None:
    early = gorkha.mainshock.origin_time - timedelta(days=1)
    body = _body(gorkha) | {"issue_time": early.isoformat()}
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 422
    assert "cannot precede the mainshock" in response.json()["detail"]


def test_a_real_forecast_round_trips_through_the_domain_model(
    client: TestClient, gorkha: SequenceSpec
) -> None:
    """A crude but genuine issuance (two continuations, coarse cells) served over HTTP."""
    response = client.post(
        "/aftershock/forecast", json=_body(gorkha), headers={API_KEY_HEADER: KEY}
    )
    assert response.status_code == 200, response.text
    forecast = AftershockForecast.model_validate(response.json())
    assert forecast.mainshock_event_id == gorkha.mainshock.event_id
    assert forecast.mainshock_magnitude == pytest.approx(7.8)
    assert forecast.horizon == timedelta(days=1)
    assert forecast.elapsed == timedelta(days=1)
    assert forecast.region_id == "aftershock-us20002926"
    assert [round(p.magnitude, 2) for p in forecast.probabilities] == [4.8, 5.8, 6.8, 7.8]
    assert all(0.0 <= p.probability <= 1.0 for p in forecast.probabilities)
    assert "Poisson" in (forecast.notes or "")


def test_the_response_validates_against_the_published_contract(
    client: TestClient, gorkha: SequenceSpec, repo_root: Path
) -> None:
    """The wire format is contracts/aftershock-forecast.v0.json, not just the pydantic model."""
    schema = json.loads(
        (repo_root / "contracts" / "aftershock-forecast.v0.json").read_text(encoding="utf-8")
    )
    response = client.post(
        "/aftershock/forecast", json=_body(gorkha), headers={API_KEY_HEADER: KEY}
    )
    assert response.status_code == 200, response.text
    jsonschema.Draft202012Validator(schema).validate(response.json())


def test_an_unscheduled_issue_time_is_refused_rather_than_refitting_in_a_request(
    client: TestClient, gorkha: SequenceSpec
) -> None:
    """An EM fit takes minutes; the service says so instead of blocking the request."""
    issue = gorkha.mainshock.origin_time + timedelta(days=3)
    body = _body(gorkha) | {"issue_time": issue.isoformat()}
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 503
    assert "no persisted fit" in response.json()["detail"]


def test_an_early_hours_issue_time_is_served_from_the_scheduled_fit(
    client: TestClient, gorkha: SequenceSpec
) -> None:
    """+3 h used to 503: only +1 h, +1 d and +7 d had fits. `rupture aftershock refit` closed it."""
    issue = gorkha.mainshock.origin_time + timedelta(hours=3)
    body = _body(gorkha) | {"issue_time": issue.isoformat()}
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 200, response.text
    forecast = AftershockForecast.model_validate(response.json())
    assert forecast.elapsed == timedelta(hours=3)
    assert "fit cutoff 2015-04-25T09:11:25.950000+00:00" in (forecast.notes or "")


def test_an_explicit_mainshock_is_accepted(client: TestClient, gorkha: SequenceSpec) -> None:
    shock = gorkha.mainshock
    body = {
        "sequence": "gorkha",
        "mainshock": {
            "event_id": shock.event_id,
            "origin_time": shock.origin_time.isoformat(),
            "latitude": shock.latitude,
            "longitude": shock.longitude,
            "magnitude": shock.magnitude,
            "depth_km": shock.depth_km,
        },
        "issue_time": (shock.origin_time + timedelta(days=1)).isoformat(),
        "horizon": "1d",
        "n_simulations": 1,
    }
    response = client.post("/aftershock/forecast", json=body, headers={API_KEY_HEADER: KEY})
    assert response.status_code == 200, response.text
    assert response.json()["mainshock_event_id"] == shock.event_id


def _body(spec: SequenceSpec) -> dict[str, object]:
    return {
        "mainshock_id": spec.mainshock.event_id,
        "issue_time": (spec.mainshock.origin_time + timedelta(days=1)).isoformat(),
        "horizon": "1d",
        "n_simulations": 1,
    }
