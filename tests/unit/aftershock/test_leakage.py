"""Leakage: an aftershock forecast may see only events strictly before its issue time.

The protocol rule (docs/EVALUATION_PROTOCOL.md section 7) binds this service exactly as it binds
the scheduled forecasts. The two tests that matter are the negative ones: a history carrying an
event at or after the issue time must be *refused*, not silently filtered, and the same for the
event exactly at the issue time (the window is half-open).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, FitResult, Region
from rupture.services.aftershock.forecaster import (
    AftershockForecaster,
    scheduled_fit_cutoff,
)
from rupture.services.aftershock.sequences import SequenceSpec

ISSUE_OFFSET = timedelta(days=1)
HORIZON = timedelta(days=7)


@pytest.fixture
def zone(
    fast_forecaster: AftershockForecaster, gorkha: SequenceSpec, nepal_region: Region
) -> Region:
    return fast_forecaster.zone(gorkha.mainshock, nepal_region)


@pytest.fixture
def fit_at_one_day(gorkha: SequenceSpec, gorkha_fits: dict[str, FitResult]) -> FitResult:
    cutoff = scheduled_fit_cutoff(
        gorkha.mainshock.origin_time, gorkha.mainshock.origin_time + ISSUE_OFFSET
    )
    return gorkha_fits[cutoff.isoformat()]


def test_a_post_issue_event_in_the_history_is_refused(
    fast_forecaster: AftershockForecaster,
    gorkha: SequenceSpec,
    gorkha_catalog: Catalog,
    zone: Region,
    fit_at_one_day: FitResult,
) -> None:
    issue_time = gorkha.mainshock.origin_time + ISSUE_OFFSET
    history = gorkha_catalog.before(issue_time)
    future = next(e for e in gorkha_catalog.events if e.origin_time > issue_time)
    poisoned = history.model_copy(update={"events": (*history.events, future)})

    with pytest.raises(LeakageError, match="aftershock forecast history"):
        fast_forecaster.issue(
            history=poisoned,
            region=zone,
            mainshock=gorkha.mainshock,
            fit=fit_at_one_day,
            issue_time=issue_time,
            horizon=HORIZON,
        )


def test_an_event_exactly_at_the_issue_time_is_refused(
    fast_forecaster: AftershockForecaster,
    gorkha: SequenceSpec,
    gorkha_catalog: Catalog,
    zone: Region,
    fit_at_one_day: FitResult,
) -> None:
    """The window is half-open ``[issue, issue + horizon)``: the boundary belongs to the target."""
    issue_time = gorkha.mainshock.origin_time + ISSUE_OFFSET
    history = gorkha_catalog.before(issue_time)
    edge = history.events[-1].model_copy(update={"id": "edge", "origin_time": issue_time})
    poisoned = history.model_copy(update={"events": (*history.events, edge)})

    with pytest.raises(LeakageError):
        fast_forecaster.issue(
            history=poisoned,
            region=zone,
            mainshock=gorkha.mainshock,
            fit=fit_at_one_day,
            issue_time=issue_time,
            horizon=HORIZON,
        )


def test_an_issue_time_before_the_mainshock_is_refused(
    fast_forecaster: AftershockForecaster,
    gorkha: SequenceSpec,
    gorkha_catalog: Catalog,
    zone: Region,
    fit_at_one_day: FitResult,
) -> None:
    early = gorkha.mainshock.origin_time - timedelta(hours=1)
    with pytest.raises(ValueError, match="cannot precede the mainshock"):
        fast_forecaster.issue(
            history=gorkha_catalog.before(early),
            region=zone,
            mainshock=gorkha.mainshock,
            fit=fit_at_one_day,
            issue_time=early,
            horizon=HORIZON,
        )


def test_the_committed_fits_saw_nothing_at_or_after_their_cutoff(
    gorkha_catalog: Catalog, gorkha_fits: dict[str, FitResult], zone: Region
) -> None:
    """Recompute each fit's training slice and check both the hash and the hard cut."""
    for cutoff_iso, fit in gorkha_fits.items():
        training = MizrahiETAS.training_slice(gorkha_catalog, zone, fit.fit_cutoff, fit.mc)
        latest = training.max_origin_time()
        assert latest is not None
        assert latest < fit.fit_cutoff
        assert cutoff_iso == fit.fit_cutoff.isoformat()
        assert fit.diagnostics["training_max_origin_time"] == latest.isoformat()


def test_a_real_issuance_only_uses_the_truncated_history(
    fast_forecaster: AftershockForecaster,
    gorkha: SequenceSpec,
    gorkha_catalog: Catalog,
    nepal_region: Region,
    fit_at_one_day: FitResult,
) -> None:
    """The happy path: the whole catalogue goes in, and only the past comes out.

    Deliberately crude (two continuations, 0.4-degree cells) so the offline suite stays quick;
    the published numbers use 100 continuations at the region's own 0.1 degree.
    """
    issue_time = gorkha.mainshock.origin_time + ISSUE_OFFSET
    issuance = fast_forecaster.forecast(
        catalog=gorkha_catalog,
        parent_region=nepal_region,
        mainshock=gorkha.mainshock,
        issue_time=issue_time,
        horizon=HORIZON,
        fit=fit_at_one_day,
    )
    forecast, grid = issuance.forecast, issuance.grid
    assert forecast.issue_time == issue_time
    assert forecast.elapsed == ISSUE_OFFSET
    assert forecast.horizon == HORIZON
    assert grid.window_end == issue_time + HORIZON
    assert grid.fit_cutoff <= issue_time
    assert forecast.parameter_snapshot_hash == fit_at_one_day.parameter_snapshot_hash
    assert forecast.forecast_grid_id == grid.id
    assert forecast.mainshock_event_id == gorkha.mainshock.event_id
    # every sequence event the forecast counted is in the past
    assert 0 < forecast.n_sequence_events <= len(gorkha_catalog)
    # the ladder is the four rungs, ordered, probabilities in [0, 1] and decreasing
    assert [round(p.magnitude, 2) for p in forecast.probabilities] == [4.8, 5.8, 6.8, 7.8]
    probabilities = [p.probability for p in forecast.probabilities]
    assert all(0.0 <= p <= 1.0 for p in probabilities)
    assert probabilities == sorted(probabilities, reverse=True)
    assert grid.total_expected() > 0.0
    assert "Poisson" in (forecast.notes or "")
