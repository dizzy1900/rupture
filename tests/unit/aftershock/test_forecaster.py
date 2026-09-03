"""The refit schedule, the magnitude ladder, and the Poisson summary of a grid."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from rupture.domain import ForecastGrid, Region, snapshot_hash
from rupture.services.aftershock.forecaster import (
    REFIT_SCHEDULE,
    AftershockForecaster,
    magnitude_ladder,
    probabilities_from_grid,
    scheduled_fit_cutoff,
)
from rupture.services.aftershock.sequences import Mainshock

MAINSHOCK_TIME = datetime(2015, 4, 25, 6, 11, 26, tzinfo=UTC)


def _grid(edges: tuple[float, ...], per_bin: tuple[float, ...]) -> ForecastGrid:
    """Two cells sharing the same per-bin mass, so column sums are ``per_bin``."""
    half = tuple(v / 2.0 for v in per_bin)
    return ForecastGrid(
        id="g",
        region_id="r",
        model_id="m",
        model_version="v",
        parameter_snapshot_hash=snapshot_hash({}),
        fit_cutoff=MAINSHOCK_TIME,
        training_catalog_hash="h",
        issue_time=MAINSHOCK_TIME,
        horizon=timedelta(days=1),
        cell_size_deg=0.1,
        cell_origins=((84.0, 28.0), (84.1, 28.0)),
        magnitude_bin_edges=edges,
        magnitude_bin_width=0.1,
        expected_counts=(half, half),
        created_at=MAINSHOCK_TIME,
    )


# ---------------------------------------------------------------- refit schedule
@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        (timedelta(0), timedelta(0)),
        (timedelta(minutes=59), timedelta(0)),
        (timedelta(hours=1), timedelta(hours=1)),
        (timedelta(hours=2, minutes=59), timedelta(hours=1)),
        (timedelta(hours=13), timedelta(hours=12)),
        (timedelta(days=1), timedelta(days=1)),
        (timedelta(days=7, hours=5), timedelta(days=7)),
        (timedelta(days=400), timedelta(days=30)),
    ],
)
def test_scheduled_fit_cutoff(elapsed: timedelta, expected: timedelta) -> None:
    got = scheduled_fit_cutoff(MAINSHOCK_TIME, MAINSHOCK_TIME + elapsed)
    assert got == MAINSHOCK_TIME + expected
    assert got <= MAINSHOCK_TIME + elapsed  # a fit is never cut after the issue time


def test_scheduled_fit_cutoff_refuses_an_issue_before_the_mainshock() -> None:
    with pytest.raises(ValueError, match="cannot precede the mainshock"):
        scheduled_fit_cutoff(MAINSHOCK_TIME, MAINSHOCK_TIME - timedelta(seconds=1))


def test_refit_schedule_is_increasing_and_starts_at_one_hour() -> None:
    assert list(REFIT_SCHEDULE) == sorted(REFIT_SCHEDULE)
    assert REFIT_SCHEDULE[0] == timedelta(hours=1)
    assert REFIT_SCHEDULE[-1] == timedelta(days=30)


# ---------------------------------------------------------------- ladder
def test_magnitude_ladder_snaps_to_bin_edges() -> None:
    assert magnitude_ladder(7.8, floor=4.7, bin_width=0.1) == (4.8, 5.8, 6.8, 7.8)
    assert magnitude_ladder(7.8, floor=4.6, bin_width=0.1) == (4.8, 5.8, 6.8, 7.8)


def test_magnitude_ladder_drops_rungs_below_the_floor() -> None:
    # M6.0 - 3 = 3.0, below a 4.7 target threshold: the grid carries no mass there.
    assert magnitude_ladder(6.0, floor=4.7, bin_width=0.1) == (5.0, 6.0)
    assert all(m >= 4.7 for m in magnitude_ladder(5.5, floor=4.7, bin_width=0.1))


def test_magnitude_ladder_is_sorted_and_unique() -> None:
    ladder = magnitude_ladder(7.8, floor=4.7, bin_width=0.1, offsets=(-1.0, -1.0, 0.0))
    assert ladder == (6.8, 7.8)


# ---------------------------------------------------------------- probabilities
def test_probabilities_are_one_minus_exp_minus_lambda() -> None:
    grid = _grid((4.7, 4.8, 4.9), (1.0, 2.0, 4.0))
    (low, high) = probabilities_from_grid(grid, (4.7, 4.9))
    assert low.expected_count == pytest.approx(7.0)
    assert low.probability == pytest.approx(1.0 - math.exp(-7.0))
    assert high.expected_count == pytest.approx(4.0)
    assert high.probability == pytest.approx(1.0 - math.exp(-4.0))


def test_probabilities_decrease_with_magnitude() -> None:
    grid = _grid((4.7, 4.8, 4.9, 5.0), (8.0, 4.0, 2.0, 1.0))
    rungs = probabilities_from_grid(grid, (4.7, 4.8, 4.9, 5.0))
    assert [r.magnitude for r in rungs] == [4.7, 4.8, 4.9, 5.0]
    assert [r.expected_count for r in rungs] == sorted(
        (r.expected_count for r in rungs), reverse=True
    )
    assert [r.probability for r in rungs] == sorted((r.probability for r in rungs), reverse=True)


def test_probability_is_zero_for_an_empty_tail() -> None:
    grid = _grid((4.7, 4.8), (1.0, 0.0))
    (rung,) = probabilities_from_grid(grid, (4.8,))
    assert rung.expected_count == 0.0
    assert rung.probability == 0.0


def test_probabilities_refuse_a_threshold_below_the_grid() -> None:
    grid = _grid((4.7, 4.8), (1.0, 1.0))
    with pytest.raises(ValueError, match="below the grid's first magnitude bin"):
        probabilities_from_grid(grid, (4.0,))


def test_probabilities_need_at_least_one_threshold() -> None:
    grid = _grid((4.7,), (1.0,))
    with pytest.raises(ValueError, match="at least one magnitude threshold"):
        probabilities_from_grid(grid, ())


# ---------------------------------------------------------------- model configuration
def test_beta_is_fixed_from_the_regions_published_b(nepal_region: Region) -> None:
    forecaster = AftershockForecaster()
    model = forecaster.model_for(nepal_region)
    assert nepal_region.mc is not None
    assert nepal_region.mc.b_value is not None
    assert model.fixed_beta == pytest.approx(nepal_region.mc.b_value * math.log(10.0))
    assert model.m_max == nepal_region.magnitude_max


def test_beta_can_be_estimated_instead(nepal_region: Region) -> None:
    model = AftershockForecaster(fix_b_value=False).model_for(nepal_region)
    assert model.fixed_beta is None


def test_zone_uses_the_configured_cell_size(nepal_region: Region) -> None:
    shock = Mainshock(
        event_id="x",
        origin_time=MAINSHOCK_TIME,
        latitude=28.0,
        longitude=85.0,
        magnitude=7.0,
    )
    default = AftershockForecaster().zone(shock, nepal_region)
    coarse = AftershockForecaster(cell_size_deg=0.5).zone(shock, nepal_region)
    assert default.cell_size_deg == nepal_region.cell_size_deg
    assert coarse.cell_size_deg == 0.5
    assert coarse.id == default.id == "aftershock-x"
