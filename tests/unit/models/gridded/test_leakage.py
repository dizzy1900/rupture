"""ADR-0022 on real catalogue timestamps: nothing at or after a cut may reach the model.

Every test here has a negative twin: a case that injects data past the cut and expects a
``LeakageError``, because a leakage guard that has never been seen to fire is not a guard.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, Region
from rupture.models.challengers.gridded import GriddedChallenger
from rupture.models.challengers.gridded import features as feat
from rupture.models.challengers.gridded._data import (
    assert_before_cutoff,
    blocked_time_forward_split,
    causal_window,
)
from tests.fixtures.models.gridded import FIXTURE_CUTOFF, FIXTURE_MC, small_config

HORIZON = timedelta(days=30)


def test_causal_window_ends_exactly_at_the_issue_time() -> None:
    end = datetime(2019, 7, 1, tzinfo=UTC)
    span = 30 * 86400.0
    first_start, _ = causal_window(end, 0, span, 4)
    last_start, last_stop = causal_window(end, 3, span, 4)
    assert last_stop == pytest.approx(end.timestamp())
    assert first_start == pytest.approx(end.timestamp() - 4 * span)
    assert last_start == pytest.approx(end.timestamp() - span)


def test_causal_window_rejects_an_index_outside_the_lookback() -> None:
    with pytest.raises(ValueError, match="span_index"):
        causal_window(datetime(2019, 7, 1, tzinfo=UTC), 4, 86400.0, 4)


def test_assert_before_cutoff_refuses_rather_than_filters() -> None:
    cutoff = datetime(2019, 7, 1, tzinfo=UTC)
    ok = [cutoff - timedelta(seconds=1)]
    assert_before_cutoff(ok, cutoff, what="unit test")
    with pytest.raises(LeakageError, match="at or after"):
        assert_before_cutoff([*ok, cutoff], cutoff, what="unit test")


def test_blocked_split_is_time_forward_and_has_no_shuffle_option() -> None:
    import inspect

    signature = inspect.signature(blocked_time_forward_split)
    assert "shuffle" not in signature.parameters
    base = datetime(2018, 1, 1, tzinfo=UTC)
    times = [base + timedelta(days=30 * k) for k in range(10)]
    train, val = blocked_time_forward_split(
        times, train_end=times[5], validation_end=times[9]
    )
    assert len(train) == 6
    assert len(val) == 4
    assert max(times[int(i)] for i in train) < min(times[int(i)] for i in val)


def test_dynamic_frames_exclude_an_event_at_the_issue_time(
    events: feat.EventArrays, raster: feat.Raster
) -> None:
    """A frame is closed on the left and open on the right: the issue instant is excluded."""
    if len(events) == 0:  # pragma: no cover - the fixture always has events in the box
        pytest.skip("no fixture events inside the test box")
    when = datetime.fromtimestamp(float(events.epoch_s[len(events) // 2]), tz=UTC)
    included = feat.dynamic_frames(
        events, raster, when + timedelta(seconds=1), n_frames=2, frame_days=30.0, mc=FIXTURE_MC
    )
    excluded = feat.dynamic_frames(
        events, raster, when, n_frames=2, frame_days=30.0, mc=FIXTURE_MC
    )
    assert included.sum() > 0.0
    # the shifted window still holds the earlier events, so compare the cell of this event only
    iy, ix = int(events.iy[len(events) // 2]), int(events.ix[len(events) // 2])
    assert included[-1, 1, iy, ix] > excluded[-1, 1, iy, ix]


def test_sample_set_refuses_a_window_reaching_past_the_cutoff(
    events: feat.EventArrays, raster: feat.Raster
) -> None:
    cutoff = FIXTURE_CUTOFF
    good = [cutoff - timedelta(days=30)]
    bad = [cutoff - timedelta(days=29)]
    feat.sample_set(
        events,
        raster,
        good,
        horizon_days=30.0,
        n_frames=2,
        frame_days=30.0,
        mc=FIXTURE_MC,
        mc_lower=FIXTURE_MC - 0.05,
        cutoff=cutoff,
    )
    with pytest.raises(LeakageError, match="sample target windows"):
        feat.sample_set(
            events,
            raster,
            bad,
            horizon_days=30.0,
            n_frames=2,
            frame_days=30.0,
            mc=FIXTURE_MC,
            mc_lower=FIXTURE_MC - 0.05,
            cutoff=cutoff,
        )


def test_static_covariates_use_only_events_before_their_cutoff(
    events: feat.EventArrays, raster: feat.Raster, region: Region
) -> None:
    early = feat.static_covariates(
        events,
        raster,
        region,
        datetime(2019, 1, 1, tzinfo=UTC),
        mc=FIXTURE_MC,
        frame_days=30.0,
        smoothing_sigma_cells=1.5,
        faults_path=None,
    )
    late = feat.static_covariates(
        events,
        raster,
        region,
        datetime(2020, 1, 1, tzinfo=UTC),
        mc=FIXTURE_MC,
        frame_days=30.0,
        smoothing_sigma_cells=1.5,
        faults_path=None,
    )
    assert early.provenance["n_events_before_cutoff"] < late.provenance["n_events_before_cutoff"]
    assert not np.array_equal(early.values, late.values)


def test_fit_training_slice_ends_before_the_cutoff(fitted: GriddedChallenger) -> None:
    fit = fitted.fit_result
    assert fit is not None
    assert fit.fit_cutoff == FIXTURE_CUTOFF
    assert fit.training_start < fit.fit_cutoff
    assert datetime.fromisoformat(fit.diagnostics["last_issue_time"]) < fit.fit_cutoff


def test_forecast_refuses_a_history_reaching_the_issue_time(
    fitted: GriddedChallenger, catalog: Catalog
) -> None:
    issue = FIXTURE_CUTOFF
    fitted.forecast(catalog.before(issue), issue, HORIZON)
    # 2019-07-04 is the Ridgecrest M6.4, three days past the cutoff: a real post-cutoff event
    leaked = catalog.before(issue + timedelta(days=10))
    assert len(leaked) > len(catalog.before(issue))
    with pytest.raises(LeakageError, match="forecast history"):
        fitted.forecast(leaked, issue, HORIZON)


def test_forecast_refuses_an_issue_time_before_the_fit_cutoff(
    fitted: GriddedChallenger, catalog: Catalog
) -> None:
    earlier = FIXTURE_CUTOFF - timedelta(days=30)
    with pytest.raises(LeakageError, match="precedes the fit cutoff"):
        fitted.forecast(catalog.before(earlier), earlier, HORIZON)


def test_fit_refuses_a_non_positive_horizon(fitted: GriddedChallenger, catalog: Catalog) -> None:
    with pytest.raises(ValueError, match="horizon must be positive"):
        fitted.forecast(catalog.before(FIXTURE_CUTOFF), FIXTURE_CUTOFF, timedelta(0))


def test_fit_refuses_a_region_without_an_mc(catalog: Catalog, region: Region) -> None:
    model = GriddedChallenger(small_config(), faults_path=None)
    assert region.mc is None
    with pytest.raises(ValueError, match="no fitted mc"):
        model.fit(catalog, region, FIXTURE_CUTOFF)
