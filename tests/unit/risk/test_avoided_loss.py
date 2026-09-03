"""The avoided-loss contract, answered for real: each measure, and what it may not claim."""

from __future__ import annotations

from datetime import UTC, datetime

import jsonschema
import pytest

from rupture.adapters.exposure import SeracExposureSource
from rupture.adapters.exposure.serac_export import FALLBACK_REL
from rupture.domain import contracts
from rupture.domain.avoided_loss_v1 import (
    AvoidedLossRequestV1,
    AvoidedLossResponseV1,
    HazardKind,
    Intervention,
    InterventionKind,
    ResponseStatus,
)
from rupture.domain.loss import ExposurePortfolio, TriggerKind
from rupture.domain.money import ConfidenceTier, ModelProvenance
from rupture.risk import avoided_loss
from rupture.risk import loss as loss_module
from tests.unit.risk.conftest import REPO_ROOT

AOI = "lhende-khola-trishuli"
FALLBACK = REPO_ROOT / FALLBACK_REL / AOI / "exposed_assets.geojson"
CONFIG = loss_module.RunConfig(n_realisations=150, seed=99)
ATTACHMENT = 1.0e8
LIMIT = 2.0e8


@pytest.fixture(scope="module")
def portfolio() -> ExposurePortfolio:
    return SeracExposureSource(repo_root=REPO_ROOT).load(FALLBACK, portfolio_id="trishuli-corridor")


def _request(
    portfolio: ExposurePortfolio,
    interventions: tuple[Intervention, ...] = (),
    *,
    trigger_kind: TriggerKind = TriggerKind.SCENARIO,
    trigger_id: str = "gorkha-2015-repeat",
) -> AvoidedLossRequestV1:
    return AvoidedLossRequestV1(
        request_id="test-0001",
        requested_at=datetime(2026, 9, 3, tzinfo=UTC),
        portfolio=portfolio,
        trigger_kind=trigger_kind,
        trigger_id=trigger_id,
        interventions=interventions,
        consumer="tests",
    )


ALL_MEASURES: tuple[Intervention, ...] = (
    Intervention(
        id="retrofit", kind=InterventionKind.STRUCTURAL_RETROFIT, description="anchor components"
    ),
    Intervention(
        id="shutdown", kind=InterventionKind.AUTOMATED_SHUTDOWN, description="strong-motion trip"
    ),
    Intervention(
        id="exclude",
        kind=InterventionKind.LAND_USE_EXCLUSION,
        description="do not site here",
        applies_to_asset_ids=("rasuwagadhi-hep",),
    ),
    Intervention(
        id="layer",
        kind=InterventionKind.INSURANCE_LAYER,
        description="excess of loss",
        parameters={"attachment": ATTACHMENT, "limit": LIMIT},
    ),
)


@pytest.fixture(scope="module")
def response(portfolio: ExposurePortfolio) -> AvoidedLossResponseV1:
    return avoided_loss.respond(
        _request(portfolio, ALL_MEASURES), repo_root=REPO_ROOT, config=CONFIG
    )


def test_every_implemented_measure_is_priced(response: AvoidedLossResponseV1) -> None:
    assert response.status is ResponseStatus.OK
    assert response.hazard_kind is HazardKind.SEISMIC
    assert [o.intervention_id for o in response.interventions] == [
        "retrofit",
        "shutdown",
        "exclude",
        "layer",
    ]
    for outcome in response.interventions:
        avoided = outcome.avoided_vs_baseline
        assert avoided.best is not None
        assert avoided.best > 0.0
        assert avoided.low <= avoided.best <= avoided.high


def test_the_response_round_trips_through_its_published_contract(
    portfolio: ExposurePortfolio, response: AvoidedLossResponseV1
) -> None:
    payload = {
        "request": _request(portfolio, ALL_MEASURES).model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
    }
    jsonschema.validate(payload, contracts.schema_for("avoided-loss.v1.json"))
    assert AvoidedLossResponseV1.model_validate(payload["response"]).request_id == "test-0001"


def test_a_serac_shaped_request_is_answered(portfolio: ExposurePortfolio) -> None:
    """ADR-0021's aliases must work end to end, not only in the schema."""
    serac_shaped = {
        "contract_version": "1.0.0",
        "request_id": "serac-req-0002",
        "requested_utc": "2026-09-03T00:00:00Z",
        "exposure": portfolio.model_dump(mode="json"),
        "requester": "serac",
        "trigger_kind": "scenario",
        "trigger_id": "gorkha-2015-repeat",
    }
    request = AvoidedLossRequestV1.model_validate(serac_shaped)
    response = avoided_loss.respond(request, repo_root=REPO_ROOT, config=CONFIG)
    assert response.status is ResponseStatus.OK
    assert response.request_id == "serac-req-0002"


def test_every_branch_shares_one_set_of_ground_motion_realisations(
    response: AvoidedLossResponseV1,
) -> None:
    """A difference taken across independent samples would be noise, not an effect."""
    assert response.n_realisations == CONFIG.n_realisations
    baseline = response.baseline_total
    assert baseline is not None
    for outcome in response.interventions:
        avoided = outcome.avoided_vs_baseline.best
        loss_with = outcome.expected_loss.best
        assert avoided is not None
        assert loss_with is not None
        assert loss_with + avoided == pytest.approx(baseline.best, rel=1e-9)


def test_land_use_exclusion_avoids_exactly_that_assets_loss(
    response: AvoidedLossResponseV1,
) -> None:
    excluded = next(o for o in response.interventions if o.intervention_id == "exclude")
    baseline_for_asset = next(
        al for al in response.baseline if al.asset_id == "rasuwagadhi-hep"
    ).expected_loss
    assert excluded.avoided_vs_baseline.best == pytest.approx(baseline_for_asset.best)


def test_an_insurance_layer_cedes_no_more_than_its_limit(
    response: AvoidedLossResponseV1,
) -> None:
    layer = next(o for o in response.interventions if o.intervention_id == "layer")
    assert layer.avoided_vs_baseline.high <= LIMIT + 1e-6
    assert any("changes who pays" in a for a in layer.assumptions)


def test_the_shutdown_fraction_is_a_request_parameter(portfolio: ExposurePortfolio) -> None:
    def avoided_for(fraction: float) -> float:
        response = avoided_loss.respond(
            _request(
                portfolio,
                (
                    Intervention(
                        id="shutdown",
                        kind=InterventionKind.AUTOMATED_SHUTDOWN,
                        description="trip",
                        parameters={"avoided_fraction": fraction},
                    ),
                ),
            ),
            repo_root=REPO_ROOT,
            config=CONFIG,
        )
        best = response.interventions[0].avoided_vs_baseline.best
        assert best is not None
        return best

    assert avoided_for(0.30) == pytest.approx(2.0 * avoided_for(0.15), rel=1e-9)


def test_an_out_of_range_fraction_is_refused(portfolio: ExposurePortfolio) -> None:
    with pytest.raises(avoided_loss.AvoidedLossError, match=r"must be in \[0, 1\]"):
        avoided_loss.respond(
            _request(
                portfolio,
                (
                    Intervention(
                        id="shutdown",
                        kind=InterventionKind.AUTOMATED_SHUTDOWN,
                        description="trip",
                        parameters={"avoided_fraction": 1.5},
                    ),
                ),
            ),
            repo_root=REPO_ROOT,
            config=CONFIG,
        )


def test_a_forecast_trigger_says_not_implemented_rather_than_guessing(
    portfolio: ExposurePortfolio,
) -> None:
    response = avoided_loss.respond(
        _request(portfolio, trigger_kind=TriggerKind.FORECAST, trigger_id="etas-nepal-30d"),
        repo_root=REPO_ROOT,
        config=CONFIG,
    )
    assert response.status is ResponseStatus.NOT_IMPLEMENTED
    assert response.provenance_kind is ModelProvenance.STUB
    assert response.confidence is ConfidenceTier.UNQUALIFIED
    assert response.message is not None
    assert "does not implement" in response.message
    assert response.baseline_total is not None
    assert response.baseline_total.best == 0.0


def test_an_unknown_scenario_is_an_error_naming_the_ones_that_exist(
    portfolio: ExposurePortfolio,
) -> None:
    response = avoided_loss.respond(
        _request(portfolio, trigger_id="not-a-scenario"), repo_root=REPO_ROOT, config=CONFIG
    )
    assert response.status is ResponseStatus.ERROR
    assert response.message is not None
    assert "gorkha-2015-repeat" in response.message


def test_a_serac_only_intervention_kind_is_refused_here(portfolio: ExposurePortfolio) -> None:
    with pytest.raises(avoided_loss.AvoidedLossError, match="serac's, not rupture's"):
        avoided_loss.respond(
            _request(
                portfolio,
                (
                    Intervention(
                        id="warn",
                        kind=InterventionKind.WARNING,
                        description="issue a warning",
                        lead_time_minutes=30.0,
                    ),
                ),
            ),
            repo_root=REPO_ROOT,
            config=CONFIG,
        )


def test_the_response_never_claims_more_than_low_confidence(
    response: AvoidedLossResponseV1,
) -> None:
    assert response.provenance_kind is ModelProvenance.ASSUMED
    assert response.confidence is ConfidenceTier.LOW
    assert response.assumptions
    assert response.provenance is not None
