"""The v1 avoided-loss contract must actually accept serac's field names, not merely claim to.

ADR-0014 obliged rupture to reconcile with the sibling `serac` if it published a differing schema
of the same name. It has (2026-09-03). These tests prove the reconciliation on payloads shaped the
way serac writes them; a compatibility claim that is not executed is not a claim.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from rupture.domain import contracts
from rupture.domain.avoided_loss_v1 import (
    AvoidedLossRequestV1,
    AvoidedLossResponseV1,
    HazardKind,
    InterventionKind,
    ResponseStatus,
)
from rupture.domain.money import ConfidenceTier, ModelProvenance, MoneyRange

FIXTURES = Path(__file__).parent / "fixtures"


def _portfolio() -> dict[str, object]:
    return {
        "id": "trishuli-corridor",
        "currency": "USD",
        "valuation_date": "2026-01-01T00:00:00Z",
        "assets": [
            {
                "id": "rasuwagadhi-hep",
                "longitude": 85.3778,
                "latitude": 28.2669,
                "taxonomy": "hydropower_plant",
                "value": 111000000.0,
            }
        ],
        "provenance": {
            "source": "serac-export",
            "retrieved_at": "2026-09-03T00:00:00Z",
            "adapter_version": "0.1.0",
            "licence": "see serac",
        },
    }


def test_request_accepts_serac_field_names() -> None:
    """serac writes requested_utc / exposure / requester; rupture must read them."""
    serac_shaped = {
        "contract_version": "1.0.0",
        "request_id": "serac-req-0001",
        "requested_utc": "2026-09-03T00:00:00Z",
        "exposure": _portfolio(),
        "requester": "serac",
        "trigger_kind": "scenario",
        "trigger_id": "mht-m8",
    }
    request = AvoidedLossRequestV1.model_validate(serac_shaped)
    assert request.requested_at == datetime(2026, 9, 3, tzinfo=UTC)
    assert request.consumer == "serac"
    assert request.portfolio.id == "trishuli-corridor"
    assert request.hazard_kind is HazardKind.SEISMIC


def test_request_accepts_ruptures_own_field_names() -> None:
    """The canonical names must keep working, so v1 does not break rupture's own consumers."""
    request = AvoidedLossRequestV1.model_validate(
        {
            "request_id": "rupture-req-0001",
            "requested_at": "2026-09-03T00:00:00Z",
            "portfolio": _portfolio(),
            "trigger_kind": "forecast",
            "trigger_id": "etas-mizrahi-nepal-himalaya-20220101T000000Z-30d",
            "horizon": "30d",
            "consumer": "rupture",
        }
    )
    assert request.consumer == "rupture"
    assert request.horizon == "30d"


def test_serac_intervention_kinds_are_representable() -> None:
    """serac's enum is a subset of rupture's, so a serac request round-trips."""
    for kind in ("none", "warning", "evacuation", "combined"):
        assert InterventionKind(kind)


def test_money_range_matches_seracs_shape() -> None:
    """The shared value type: same field names, same constraints."""
    money = MoneyRange(
        low=1.0e6,
        high=5.0e6,
        best=2.0e6,
        currency="USD",
        price_year=2026,
        basis="scenario loss, 1000 realisations",
    )
    dumped = money.model_dump(mode="json")
    assert set(dumped) >= {"low", "high", "best", "currency", "price_year", "basis"}
    with pytest.raises(ValueError, match="exceeds"):
        MoneyRange(low=5.0, high=1.0, currency="USD", price_year=2026, basis="x")


def test_a_stub_response_cannot_claim_confidence() -> None:
    """serac's rule, adopted here: `unqualified` is the only tier a stub may claim."""
    with pytest.raises(ValueError, match="only claim"):
        AvoidedLossResponseV1(
            request_id="r",
            status=ResponseStatus.NOT_IMPLEMENTED,
            computed_at=datetime(2026, 9, 3, tzinfo=UTC),
            provenance_kind=ModelProvenance.STUB,
            confidence=ConfidenceTier.HIGH,
        )


def test_v1_schema_validates_a_serac_shaped_payload() -> None:
    schema = contracts.schema_for("avoided-loss.v1.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    request = AvoidedLossRequestV1.model_validate(
        {
            "request_id": "serac-req-0002",
            "requested_utc": "2026-09-03T00:00:00Z",
            "exposure": _portfolio(),
            "trigger_kind": "scenario",
            "trigger_id": "gorkha-repeat",
        }
    )
    response = AvoidedLossResponseV1(
        request_id=request.request_id,
        status=ResponseStatus.NOT_IMPLEMENTED,
        computed_at=datetime(2026, 9, 3, tzinfo=UTC),
        message="not implemented yet",
    )
    payload = {
        "request": request.model_dump(mode="json", by_alias=False),
        "response": response.model_dump(mode="json", by_alias=False),
    }
    jsonschema.validate(payload, schema)


def test_v0_is_unchanged_and_still_published() -> None:
    """Bumping to v1 must not break anything reading v0."""
    v0 = json.loads((Path("contracts") / "avoided-loss.v0.json").read_text())
    assert v0["$id"].endswith("avoided-loss.v0.json")
    assert "avoided-loss.v0.json" in contracts.CONTRACTS
