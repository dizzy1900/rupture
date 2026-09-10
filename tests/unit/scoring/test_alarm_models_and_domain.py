"""The AlarmSet type's own guarantees, and the two alarm models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from rupture.domain import Provenance
from rupture.domain.alarm import AlarmSet
from rupture.models.alarms import (
    RECENT_LARGE_MODEL_ID,
    RecentLargeParameters,
    alarm_from_forecast_grid,
    recent_large_alarm,
)
from rupture.scoring.errors import MissingReferenceError
from tests.unit.scoring.conftest import (
    CELL,
    GRID_SIDE,
    HORIZON,
    ISSUE,
    make_alarm,
    make_catalog,
)

N_CELLS = GRID_SIDE * GRID_SIDE


def test_a_binary_alarm_must_declare_its_footprint(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    with pytest.raises(ValueError, match="declared_threshold is required"):
        AlarmSet(
            id="a",
            region_id="r",
            model_id="m",
            model_version="1",
            issue_time=ISSUE,
            horizon=HORIZON,
            target_min_magnitude=4.0,
            cell_size_deg=CELL,
            cell_origins=cell_origins,
            alarm_values=tuple([1.0] * N_CELLS),
            binary=True,
            declared_threshold=None,
            fit_cutoff=ISSUE,
            training_catalog_hash="0" * 64,
            parameter_snapshot_hash="x",
            created_at=ISSUE,
        )


def test_asking_an_undeclared_alarm_for_a_footprint_is_refused(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    alarm = make_alarm(cell_origins, np.zeros(N_CELLS), declared_threshold=None)
    with pytest.raises(ValueError, match="chosen after the targets"):
        alarm.declared_footprint()


def test_an_alarm_issued_before_its_own_fit_cutoff_is_refused(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    with pytest.raises(ValueError, match="must not precede fit_cutoff"):
        make_alarm(
            cell_origins,
            np.zeros(N_CELLS),
            issue_time=ISSUE,
            fit_cutoff=ISSUE + timedelta(days=1),
        )


def test_the_trivial_rule_declares_nothing_when_nothing_has_broken(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    quiet = make_catalog(scoring_provenance, list(cell_origins[:3]), inside_window=False, mw=4.0)
    alarm = recent_large_alarm(
        quiet,
        region_id="synthetic",
        cell_origins=cell_origins,
        cell_size_deg=CELL,
        issue_time=ISSUE,
        horizon=HORIZON,
        target_min_magnitude=4.0,
    )
    assert alarm.model_id == RECENT_LARGE_MODEL_ID
    assert float(alarm.values().max()) == 0.0
    assert "0 trigger(s)" in (alarm.notes or "")


def test_the_trivial_rule_fires_around_a_recent_large_event(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    trigger_cell = cell_origins[N_CELLS // 2]
    history = make_catalog(scoring_provenance, [trigger_cell], inside_window=False, mw=6.0)
    alarm = recent_large_alarm(
        history,
        region_id="synthetic",
        cell_origins=cell_origins,
        cell_size_deg=CELL,
        issue_time=ISSUE,
        horizon=HORIZON,
        target_min_magnitude=4.0,
    )
    values = alarm.values()
    assert int(np.argmax(values)) == N_CELLS // 2
    assert float(values.max()) > 1.0, "an M6 weighs more than the M5.5 trigger threshold"
    assert alarm.declared_threshold == 0.5


def test_the_trivial_rule_cannot_see_its_own_window(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    """Handed the whole catalogue, it still cuts at the issue time itself."""
    future = make_catalog(scoring_provenance, [cell_origins[0]], inside_window=True, mw=7.0)
    alarm = recent_large_alarm(
        future,
        region_id="synthetic",
        cell_origins=cell_origins,
        cell_size_deg=CELL,
        issue_time=ISSUE,
        horizon=HORIZON,
        target_min_magnitude=4.0,
    )
    assert float(alarm.values().max()) == 0.0
    assert alarm.fit_cutoff == ISSUE


def test_a_trigger_older_than_the_lookback_is_ignored(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    old = make_catalog(scoring_provenance, [cell_origins[0]], inside_window=False, mw=7.0)
    alarm = recent_large_alarm(
        old,
        region_id="synthetic",
        cell_origins=cell_origins,
        cell_size_deg=CELL,
        issue_time=ISSUE,
        horizon=HORIZON,
        target_min_magnitude=4.0,
        parameters=RecentLargeParameters(lookback_days=2.0),
    )
    assert float(alarm.values().max()) > 0.0
    stale = recent_large_alarm(
        old,
        region_id="synthetic",
        cell_origins=cell_origins,
        cell_size_deg=CELL,
        issue_time=ISSUE + timedelta(days=90),
        horizon=HORIZON,
        target_min_magnitude=4.0,
        parameters=RecentLargeParameters(lookback_days=30.0),
    )
    assert float(stale.values().max()) == 0.0


def test_the_parameter_hash_changes_when_a_parameter_does(
    cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    quiet = make_catalog(scoring_provenance, [cell_origins[0]], inside_window=False)
    kwargs = {
        "region_id": "synthetic",
        "cell_origins": cell_origins,
        "cell_size_deg": CELL,
        "issue_time": ISSUE,
        "horizon": HORIZON,
        "target_min_magnitude": 4.0,
    }
    a = recent_large_alarm(quiet, **kwargs)  # type: ignore[arg-type]
    b = recent_large_alarm(
        quiet,
        parameters=RecentLargeParameters(radius_km=25.0),
        **kwargs,  # type: ignore[arg-type]
    )
    assert a.parameter_snapshot_hash != b.parameter_snapshot_hash


def test_a_forecast_read_as_an_alarm_keeps_its_provenance(ridgecrest_grid: object) -> None:
    grid = ridgecrest_grid
    alarm = alarm_from_forecast_grid(grid, target_min_magnitude=4.95)  # type: ignore[arg-type]
    assert alarm.cell_origins == grid.cell_origins  # type: ignore[attr-defined]
    assert alarm.fit_cutoff == grid.fit_cutoff  # type: ignore[attr-defined]
    assert alarm.training_catalog_hash == grid.training_catalog_hash  # type: ignore[attr-defined]
    assert alarm.declared_threshold is None
    assert float(alarm.values().sum()) > 0.0


def test_a_forecast_with_no_bin_at_the_alarm_magnitude_is_refused(
    ridgecrest_grid: object,
) -> None:
    with pytest.raises(MissingReferenceError, match="no magnitude bin"):
        alarm_from_forecast_grid(ridgecrest_grid, target_min_magnitude=9.9)  # type: ignore[arg-type]


def test_the_alarm_id_is_stable_and_carries_the_window() -> None:
    made = AlarmSet.make_id("m", "r", datetime(2020, 3, 4, tzinfo=UTC), timedelta(days=30))
    assert made == "m-r-20200304T000000Z-30d"
