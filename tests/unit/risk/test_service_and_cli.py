"""The HTTP surface and the CLI. No network: ``TestClient`` speaks to the app in process."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from rupture.adapters.exposure import SeracExposureSource
from rupture.adapters.exposure.serac_export import FALLBACK_REL
from rupture.commands import risk as risk_cli
from rupture.domain.avoided_loss_v1 import AvoidedLossRequestV1
from rupture.domain.loss import ExposurePortfolio, TriggerKind
from rupture.risk import service as service_module
from tests.unit.risk.conftest import REPO_ROOT

AOI = "lhende-khola-trishuli"
FALLBACK = REPO_ROOT / FALLBACK_REL / AOI / "exposed_assets.geojson"
KEY = "test-key-0123456789"
OK = 200
UNAUTHORIZED = 401
UNAVAILABLE = 503
BAD_REQUEST = 400
SMALL_RUN = 40


@pytest.fixture
def portfolio() -> ExposurePortfolio:
    return SeracExposureSource(repo_root=REPO_ROOT).load(FALLBACK, portfolio_id="trishuli-corridor")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv(service_module.API_KEY_ENV, f"{KEY},another-key")
    monkeypatch.setenv(service_module.REPO_ROOT_ENV, str(REPO_ROOT))
    return TestClient(service_module.create_app())


def _payload(portfolio: ExposurePortfolio, **overrides: object) -> dict[str, object]:
    request = AvoidedLossRequestV1(
        request_id="http-0001",
        requested_at=datetime(2026, 9, 3, tzinfo=UTC),
        portfolio=portfolio,
        trigger_kind=TriggerKind.SCENARIO,
        trigger_id="gorkha-2015-repeat",
        consumer="tests",
    )
    return {**request.model_dump(mode="json"), **overrides}


def test_health_needs_no_key(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == OK
    assert response.json()["contract_version"] == "1.0.0"


def test_a_request_without_a_key_is_refused(
    client: TestClient, portfolio: ExposurePortfolio
) -> None:
    response = client.post("/v1/avoided-loss", json=_payload(portfolio))
    assert response.status_code == UNAUTHORIZED


def test_a_request_with_the_wrong_key_is_refused(
    client: TestClient, portfolio: ExposurePortfolio
) -> None:
    response = client.post(
        "/v1/avoided-loss", json=_payload(portfolio), headers={"X-API-Key": "nope"}
    )
    assert response.status_code == UNAUTHORIZED


def test_with_no_keys_configured_the_service_refuses_rather_than_running_open(
    monkeypatch: pytest.MonkeyPatch, portfolio: ExposurePortfolio
) -> None:
    monkeypatch.delenv(service_module.API_KEY_ENV, raising=False)
    unconfigured = TestClient(service_module.create_app())
    response = unconfigured.post(
        "/v1/avoided-loss", json=_payload(portfolio), headers={"X-API-Key": KEY}
    )
    assert response.status_code == UNAVAILABLE
    assert service_module.API_KEY_ENV in response.json()["detail"]


def test_the_endpoint_answers_the_contract(
    client: TestClient, portfolio: ExposurePortfolio
) -> None:
    response = client.post("/v1/avoided-loss", json=_payload(portfolio), headers={"X-API-Key": KEY})
    assert response.status_code == OK
    body = response.json()
    assert body["status"] == "ok"
    assert body["hazard_kind"] == "seismic"
    assert body["baseline_total"]["best"] > 0.0
    assert body["provenance_kind"] == "assumed"
    assert body["assumptions"]


def test_an_unknown_scenario_is_a_client_error(
    client: TestClient, portfolio: ExposurePortfolio
) -> None:
    response = client.post(
        "/v1/avoided-loss",
        json=_payload(portfolio, trigger_id="not-a-scenario"),
        headers={"X-API-Key": KEY},
    )
    assert response.status_code == BAD_REQUEST


def test_the_scenario_listing_needs_a_key(client: TestClient) -> None:
    assert client.get("/v1/scenarios").status_code == UNAUTHORIZED
    listed = client.get("/v1/scenarios", headers={"X-API-Key": KEY})
    assert listed.status_code == OK
    assert {item["id"] for item in listed.json()} == {
        "gorkha-2015-repeat",
        "mht-m8-hypothetical",
    }


# ------------------------------------------------------------------ CLI
def test_the_cli_lists_scenarios_and_gsims() -> None:
    runner = CliRunner()
    scenarios_out = runner.invoke(risk_cli.app, ["scenarios"])
    assert scenarios_out.exit_code == 0
    assert "HYPOTHETICAL" in scenarios_out.stdout
    gsims_out = runner.invoke(risk_cli.app, ["gsims"])
    assert gsims_out.exit_code == 0
    assert "BooreEtAl2014" in gsims_out.stdout


def test_the_cli_prints_the_loss_and_the_avoided_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pinned to the committed fixture so the test does not depend on a sibling checkout."""
    monkeypatch.setenv("SERAC_EXPORT_DIR", str(REPO_ROOT / "does-not-exist"))
    result = CliRunner().invoke(
        risk_cli.app,
        ["run", "--scenario", "gorkha-2015-repeat", "--realisations", str(SMALL_RUN)],
    )
    assert result.exit_code == 0, result.stdout
    assert "expected loss:" in result.stdout
    assert "avoided loss by intervention:" in result.stdout
    assert "committed fallback fixture" in result.stdout
    assert "assumption:" in result.stdout


def test_the_cli_refuses_both_or_neither_trigger() -> None:
    runner = CliRunner()
    assert runner.invoke(risk_cli.app, ["run"]).exit_code != 0
    both = runner.invoke(risk_cli.app, ["run", "--scenario", "a", "--forecast", "b"])
    assert both.exit_code != 0


def test_the_cli_forecast_path_exits_non_zero_saying_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERAC_EXPORT_DIR", str(REPO_ROOT / "does-not-exist"))
    result = CliRunner().invoke(
        risk_cli.app,
        ["run", "--forecast", "etas-nepal-30d", "--realisations", str(SMALL_RUN)],
    )
    assert result.exit_code == 1
    assert "not_implemented" in result.stdout
