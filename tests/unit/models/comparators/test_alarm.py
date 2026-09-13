"""AlarmSet helper: clustering-aware reference required, uniform refused."""

from __future__ import annotations

import numpy as np
import pytest
from tests.unit.models.comparators.conftest import HORIZON, ISSUE, MC

from rupture.domain import Catalog
from rupture.domain.alarm import ReferenceKind
from rupture.models.comparators.alarm import alarm_from_logistic
from rupture.models.comparators.logistic import OneNeuronAftershockModel
from rupture.scoring.errors import MissingReferenceError, UniformReferenceRefusedError
from rupture.scoring.reference import from_forecast_grid, smoothed_seismicity, uniform


def test_uniform_reference_is_refused(fitted: OneNeuronAftershockModel, training: Catalog) -> None:
    dummy = uniform(fitted.cell_origins, 0.25, expected_events=10.0)
    with pytest.raises(UniformReferenceRefusedError, match="spatially uniform"):
        alarm_from_logistic(
            fitted,
            training,
            tau=0.2,
            reference=dummy,
            issue_time=ISSUE,
            horizon=HORIZON,
            target_min_magnitude=MC,
        )


def test_spatially_varying_poisson_is_not_the_reference_of_record(
    fitted: OneNeuronAftershockModel, training: Catalog
) -> None:
    counts = np.ones(len(fitted.cell_origins), dtype=np.float64)
    svp = smoothed_seismicity(fitted.cell_origins, 0.25, counts)
    with pytest.raises(MissingReferenceError, match="not clustering-aware"):
        alarm_from_logistic(
            fitted,
            training,
            tau=0.2,
            reference=svp,
            issue_time=ISSUE,
            horizon=HORIZON,
            target_min_magnitude=MC,
        )


def test_declared_footprint_covers_the_requested_tau(
    fitted: OneNeuronAftershockModel, training: Catalog
) -> None:
    grid = fitted.forecast(training, ISSUE, HORIZON)
    reference = from_forecast_grid(grid, kind=ReferenceKind.CLUSTERING_AWARE)
    tau = 0.2
    alarm = alarm_from_logistic(
        fitted,
        training,
        tau=tau,
        reference=reference,
        issue_time=ISSUE,
        horizon=HORIZON,
        target_min_magnitude=MC,
    )
    assert alarm.declared_threshold is not None
    footprint = alarm.declared_footprint()
    mass = float(reference.probabilities[footprint].sum())
    assert mass >= tau - 1e-12
    values = alarm.values()
    stricter = values > alarm.declared_threshold + 1e-15
    if stricter.any() and not np.array_equal(stricter, footprint):
        assert float(reference.probabilities[stricter].sum()) < tau + 1e-12
    assert alarm.model_id == fitted.model_id
    assert "area skill" in (alarm.notes or "")
