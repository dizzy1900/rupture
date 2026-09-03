"""Contracts: export is deterministic, checked-in files match, fixtures validate."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rupture.domain import AvoidedLossRequest, SourceTypeAssessment, contracts

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.parametrize("name", sorted(contracts.CONTRACTS))
def test_schema_is_valid_draft_2020_12(name: str) -> None:
    schema = contracts.schema_for(name)
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$id"].endswith(name)


def test_export_is_deterministic(tmp_path: Path) -> None:
    first = {p.name: p.read_text() for p in contracts.export_all(tmp_path / "a")}
    second = {p.name: p.read_text() for p in contracts.export_all(tmp_path / "b")}
    assert first == second


def test_checked_in_contracts_match_models() -> None:
    drifted = contracts.drift(REPO_ROOT / "contracts")
    assert drifted == [], f"run `make schema-export`; drifted: {drifted}"


def test_avoided_loss_request_fixture_round_trips() -> None:
    payload = json.loads((FIXTURES / "avoided-loss.request.example.json").read_text())
    request = AvoidedLossRequest.model_validate(payload)
    assert request.contract_version == "0"
    dumped = request.model_dump(mode="json")
    again = AvoidedLossRequest.model_validate(dumped)
    assert again == request
    # the request half of the shared avoided-loss schema accepts it
    schema = contracts.schema_for("avoided-loss.v0.json")
    request_schema = {**schema, **schema["$defs"]["AvoidedLossRequest"]}
    request_schema.pop("properties", None)
    jsonschema.validate(dumped, {"$defs": schema["$defs"], **schema["$defs"]["AvoidedLossRequest"]})


def test_serac_source_type_fixture_validates() -> None:
    payload = json.loads((FIXTURES / "serac" / "source-type-assessment.example.json").read_text())
    schema = contracts.schema_for("source-type-assessment.v0.json")
    jsonschema.validate(payload, schema)
    model = SourceTypeAssessment.model_validate(payload)
    assert abs(model.p_mass_movement + model.p_tectonic + model.p_other - 1.0) < 1e-9


def test_source_type_probabilities_must_sum_to_one() -> None:
    payload = json.loads((FIXTURES / "serac" / "source-type-assessment.example.json").read_text())
    payload["p_tectonic"] = 0.5
    with pytest.raises(ValueError, match="sum to 1"):
        SourceTypeAssessment.model_validate(payload)
