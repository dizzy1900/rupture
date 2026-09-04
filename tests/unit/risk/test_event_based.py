"""Expected annual loss, exceedance curves and event-based avoided loss (ADR-0036, ADR-0038)."""

from __future__ import annotations

import json

import numpy as np
import pytest

from rupture.adapters.exposure.serac_export import FALLBACK_REL, SeracExposureSource
from rupture.adapters.vulnerability import HydropowerVulnerability
from rupture.domain.avoided_loss_v1 import (
    AvoidedLossRequestV1,
    Intervention,
    InterventionKind,
    ResponseStatus,
)
from rupture.domain.common import utc_now
from rupture.domain.forecast import ForecastGrid
from rupture.domain.loss import ExposurePortfolio, TriggerKind
from rupture.risk import avoided_loss as al
from rupture.risk import event_based as eb
from rupture.risk import event_set as es
from rupture.risk import loss as loss_module
from tests.unit.risk.conftest import REPO_ROOT, RISK_FIXTURES

SLICE_FILE = RISK_FIXTURES / "forecast" / "trishuli-corridor-slice.json"
AOI = "lhende-khola-trishuli"


@pytest.fixture(scope="module")
def grid() -> ForecastGrid:
    return ForecastGrid.model_validate(json.loads(SLICE_FILE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def portfolio() -> ExposurePortfolio:
    """Always the committed fallback, never a sibling checkout that may or may not be present."""
    source = SeracExposureSource(repo_root=REPO_ROOT)
    return source.load(
        REPO_ROOT / FALLBACK_REL / AOI / "exposed_assets.geojson",
        portfolio_id="trishuli-corridor",
    )


@pytest.fixture(scope="module")
def event_set(grid: ForecastGrid) -> es.StochasticEventSet:
    return es.sample_from_forecast_grid(
        grid,
        config=es.SamplingConfig(n_catalogues=120, min_magnitude=5.0, seed=20260903),
    )


@pytest.fixture(scope="module")
def result(portfolio: ExposurePortfolio, event_set: es.StochasticEventSet) -> eb.EventBasedLoss:
    return eb.run_event_based(
        portfolio,
        event_set,
        config=loss_module.RunConfig(seed=20260903),
        n_gm_realisations=12,
    )


def test_annual_loss_is_positive_finite_and_carries_its_basis(
    result: eb.EventBasedLoss,
) -> None:
    aal = result.annual_expected_loss_money()
    assert aal.best is not None
    assert 0.0 < aal.best < float("inf")
    assert aal.low <= aal.best <= aal.high
    assert "expected annual loss" in aal.basis
    assert "NOT the spread of annual loss" in aal.basis


def test_the_aal_equals_the_rate_weighted_mean_of_the_event_losses(
    result: eb.EventBasedLoss,
) -> None:
    """The headline number must be reproducible by hand from the per-catalogue contributions."""
    per_catalogue = np.asarray(result.baseline.per_catalogue_annual, dtype=np.float64)
    assert result.baseline.annual_expected_loss.best == pytest.approx(
        float(per_catalogue.mean()), rel=1e-12
    )


def test_exceedance_curves_are_monotone_and_stop_at_what_the_set_resolves(
    result: eb.EventBasedLoss,
) -> None:
    assert result.resolvable_return_period_years == 120.0
    for curve in (result.baseline.aggregate_exceedance, result.baseline.occurrence_exceedance):
        assert curve
        periods = [p.return_period_years for p in curve]
        assert periods == sorted(periods)
        assert max(periods) <= result.resolvable_return_period_years
        losses = [p.loss for p in curve]
        assert losses == sorted(losses)
        for point in curve:
            assert point.annual_exceedance_rate == pytest.approx(1.0 / point.return_period_years)
            assert 0.0 < point.exceedance_probability_1y < 1.0


def test_no_return_period_beyond_the_event_set_is_reported(
    portfolio: ExposurePortfolio, event_set: es.StochasticEventSet
) -> None:
    short = eb.run_event_based(
        portfolio,
        es.sample_from_forecast_grid(
            ForecastGrid.model_validate(json.loads(SLICE_FILE.read_text(encoding="utf-8"))),
            config=es.SamplingConfig(n_catalogues=8, min_magnitude=5.0, seed=1),
        ),
        config=loss_module.RunConfig(seed=1),
        n_gm_realisations=4,
    )
    assert all(p.return_period_years <= 8.0 for p in short.baseline.aggregate_exceedance)


def test_unmodelled_assets_are_named_not_dropped(result: eb.EventBasedLoss) -> None:
    assert len(result.modelled_asset_ids) == 9
    assert len(result.unmodelled) == 5
    assert all(reason for _, reason in result.unmodelled)


def test_the_assumed_share_is_reported(result: eb.EventBasedLoss) -> None:
    assert 0.0 < result.assumed_share < 1.0


def test_the_event_sets_assumptions_travel_with_the_loss(result: eb.EventBasedLoss) -> None:
    joined = " ".join(result.assumptions)
    assert "POINT rupture" in joined
    assert "lower estimate" in joined
    assert "not modelled" in joined or "not because they are small" in joined


def test_a_branch_priced_on_the_same_catalogues_can_be_differenced(
    portfolio: ExposurePortfolio, event_set: es.StochasticEventSet
) -> None:
    model = HydropowerVulnerability()
    excluded = frozenset({portfolio.assets[0].id})
    curves = al.curves_for_portfolio(portfolio, model)
    run = eb.run_event_based(
        portfolio,
        event_set,
        config=loss_module.RunConfig(seed=20260903),
        n_gm_realisations=12,
        branches=[eb.BranchSpec(label="exclude", curves=curves, excluded=excluded)],
    )
    avoided = eb.avoided_annual_loss(
        run.baseline,
        run.branch("exclude"),
        currency=portfolio.currency,
        price_year=2025,
        interval_level=0.9,
        seed=1,
        basis="unit test",
    )
    assert avoided.money.best is not None
    assert avoided.money.best > 0.0
    assert avoided.negative_catalogue_fraction == 0.0
    assert avoided.note() is None


def test_a_measure_that_raises_the_expected_loss_is_refused_not_zeroed(
    result: eb.EventBasedLoss,
) -> None:
    inverted = eb.BranchResult(
        label="worse",
        annual_expected_loss=result.baseline.annual_expected_loss,
        per_asset_annual={},
        per_catalogue_annual=tuple(v * 2.0 for v in result.baseline.per_catalogue_annual),
        catalogue_year_losses=(),
        aggregate_exceedance=(),
        occurrence_exceedance=(),
    )
    with pytest.raises(eb.EventBasedError, match="raises the expected annual loss"):
        eb.avoided_annual_loss(
            result.baseline,
            inverted,
            currency="USD",
            price_year=2025,
            interval_level=0.9,
            seed=1,
            basis="unit test",
        )


def test_shutdown_trigger_needs_both_a_trip_and_time_to_act() -> None:
    trigger = eb.ShutdownTrigger(
        threshold_g=0.05, s_wave_km_s=3.5, latency_s=5.0, stopping_time_s=10.0
    )
    assert trigger.required_seconds == 15.0
    # 100 km away: 28.6 s of S-wave travel, so 13.6 s to spare.
    assert trigger.warning_seconds(100.0) == pytest.approx(100.0 / 3.5 - 15.0)
    far = trigger.fires(np.array([0.2, 0.01]), 100.0)
    assert far.tolist() == [True, False]
    # 30 km away: 8.6 s of travel, which is less than the 15 s the trip needs.
    assert trigger.warning_seconds(30.0) < 0.0
    near = trigger.fires(np.array([0.9, 0.2]), 30.0)
    assert near.tolist() == [False, False]


def test_forecast_trigger_is_answered_end_to_end_offline(
    portfolio: ExposurePortfolio, grid: ForecastGrid
) -> None:
    """`--forecast` is no longer a dead end: a ForecastGrid in, an annual figure out."""
    request = AvoidedLossRequestV1(
        request_id="unit-forecast-0001",
        requested_at=utc_now(),
        portfolio=portfolio,
        trigger_kind=TriggerKind.FORECAST,
        trigger_id=grid.id,
        horizon="1y",
        interventions=(
            Intervention(
                id="exclude-largest",
                kind=InterventionKind.LAND_USE_EXCLUSION,
                description="do not site the largest plant here",
                applies_to_asset_ids=("upper-trishuli-1",),
            ),
        ),
        consumer="unit-test",
    )
    response, detail = al.respond_with_detail(
        request,
        repo_root=REPO_ROOT,
        grids={grid.id: grid},
        sampling=es.SamplingConfig(n_catalogues=60, min_magnitude=5.0, seed=7),
        config=loss_module.RunConfig(seed=7),
        n_gm_realisations=8,
    )
    assert response.status is ResponseStatus.OK
    assert detail is not None
    total = response.baseline_total
    assert total is not None
    assert total.best is not None
    assert total.best > 0.0
    assert "per year" in (response.message or "")
    assert response.interventions
    assert response.interventions[0].avoided_vs_baseline.best is not None
    assert detail.baseline.aggregate_exceedance


def test_a_missing_forecast_grid_fails_loudly_rather_than_returning_zero(
    portfolio: ExposurePortfolio,
) -> None:
    request = AvoidedLossRequestV1(
        request_id="unit-forecast-0002",
        requested_at=utc_now(),
        portfolio=portfolio,
        trigger_kind=TriggerKind.FORECAST,
        trigger_id="no-such-grid",
        consumer="unit-test",
    )
    response = al.respond(request, repo_root=REPO_ROOT, grids={})
    assert response.status is ResponseStatus.ERROR
    assert "no ForecastGrid" in (response.message or "")
    assert response.baseline_total is None


def test_a_long_term_hazard_trigger_still_says_what_is_missing(
    portfolio: ExposurePortfolio,
) -> None:
    request = AvoidedLossRequestV1(
        request_id="unit-hazard-0001",
        requested_at=utc_now(),
        portfolio=portfolio,
        trigger_kind=TriggerKind.HAZARD,
        trigger_id="nepal-psha",
        consumer="unit-test",
    )
    response = al.respond(request, repo_root=REPO_ROOT)
    assert response.status is ResponseStatus.NOT_IMPLEMENTED
    assert "source model" in (response.message or "")
    assert response.confidence.value == "unqualified"
