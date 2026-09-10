"""Pooling a schedule: the unit of evidence is the schedule, not the window."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from rupture.domain import Provenance
from rupture.scoring import reference as refmod
from rupture.scoring.errors import MissingReferenceError, UniformReferenceRefusedError
from rupture.scoring.schedule import WindowInput, score_alarm_schedule
from tests.unit.scoring.conftest import (
    CELL,
    GRID_SIDE,
    HORIZON,
    ISSUE,
    make_alarm,
    make_catalog,
    make_reference,
)

N_CELLS = GRID_SIDE * GRID_SIDE


def _window(
    cell_origins: tuple[tuple[float, float], ...],
    k: int,
    values: np.ndarray,
    *,
    expected_events: float,
) -> WindowInput:
    issue = ISSUE + k * HORIZON
    return WindowInput(
        make_alarm(cell_origins, values, issue_time=issue),
        make_reference(cell_origins, np.ones(N_CELLS), expected_events=expected_events),
    )


def test_an_empty_schedule_is_refused() -> None:
    with pytest.raises(ValueError, match="empty schedule"):
        score_alarm_schedule([], make_catalog, schedule_id="x")  # type: ignore[arg-type]


def test_a_uniform_reference_is_refused_for_a_schedule_too(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    values = np.zeros(N_CELLS)
    values[:5] = 1.0
    ref = refmod.uniform(cell_origins, CELL, expected_events=5.0)
    windows = [WindowInput(make_alarm(cell_origins, values), ref)]
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]))
    with pytest.raises(UniformReferenceRefusedError, match="spatially uniform"):
        score_alarm_schedule(windows, catalog, schedule_id="x", n_simulations=10)


def test_a_window_whose_reference_is_on_other_cells_is_refused(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    values = np.zeros(N_CELLS)
    windows = [
        WindowInput(
            make_alarm(cell_origins, values),
            make_reference(cell_origins[:-1], np.ones(N_CELLS - 1)),
        )
    ]
    catalog = make_catalog(scoring_provenance, list(cell_origins[:1]))
    with pytest.raises(MissingReferenceError, match="different cells"):
        score_alarm_schedule(windows, catalog, schedule_id="x", n_simulations=10)


def test_targets_are_counted_in_the_window_they_fell_in(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    """A schedule sees each window's own targets, not the union across all of them."""
    hot = np.zeros(N_CELLS)
    hot[:5] = 1.0
    windows = [_window(cell_origins, k, hot, expected_events=5.0) for k in range(3)]
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]))
    result = score_alarm_schedule(windows, catalog, schedule_id="s", n_simulations=200, seed=1)
    assert result.n_target_events == 5, "the events sit in window 0 only"
    assert result.n_cells == 3 * N_CELLS
    assert any("pooled over 3 window(s)" in n for n in result.notes)


def test_a_busy_window_outweighs_a_quiet_one(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    hot = np.zeros(N_CELLS)
    hot[:5] = 1.0
    busy = _window(cell_origins, 0, hot, expected_events=100.0)
    quiet = _window(cell_origins, 1, hot, expected_events=1.0)
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]))
    result = score_alarm_schedule(
        [busy, quiet], catalog, schedule_id="s", n_simulations=200, seed=2
    )
    # The declared footprint is 5 of 100 cells in each window; the busy window carries 100/101
    # of the pooled mass, so the pooled alarm fraction sits near 0.05, not near half of it.
    assert result.declared_tau == pytest.approx(0.05, abs=0.005)


def test_windows_that_declared_different_operating_points_declare_none(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    values = np.linspace(0.0, 1.0, N_CELLS)
    a = WindowInput(
        make_alarm(cell_origins, values, declared_threshold=0.5),
        make_reference(cell_origins, np.ones(N_CELLS)),
    )
    b = WindowInput(
        make_alarm(cell_origins, values, declared_threshold=0.9, issue_time=ISSUE + HORIZON),
        make_reference(cell_origins, np.ones(N_CELLS)),
    )
    catalog = make_catalog(scoring_provenance, list(cell_origins[-3:]))
    result = score_alarm_schedule([a, b], catalog, schedule_id="s", n_simulations=100, seed=3)
    assert result.declared_threshold is None
    assert result.declared_probability_gain is None
    assert any("declared different operating points" in n for n in result.notes)


def test_a_schedule_with_no_target_anywhere_is_undecidable(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    hot = np.zeros(N_CELLS)
    hot[:5] = 1.0
    windows = [_window(cell_origins, k, hot, expected_events=5.0) for k in range(2)]
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]), inside_window=False)
    result = score_alarm_schedule(windows, catalog, schedule_id="s", n_simulations=50, seed=4)
    assert result.n_target_events == 0
    assert result.significant is None
    assert any("undecidable, not passed" in n for n in result.notes)


def test_the_schedule_window_spans_every_window_it_pooled(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    hot = np.zeros(N_CELLS)
    hot[:5] = 1.0
    windows = [_window(cell_origins, k, hot, expected_events=5.0) for k in range(4)]
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]))
    result = score_alarm_schedule(windows, catalog, schedule_id="s", n_simulations=50, seed=5)
    assert result.target_window_start == ISSUE
    assert result.target_window_end == ISSUE + 4 * HORIZON
    assert result.target_window_end - result.target_window_start == timedelta(days=120)
