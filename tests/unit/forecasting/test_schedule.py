"""The pseudo-prospective runner and its leakage assertions (positive and negative)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.adapters.forecasting.leakage import (
    LeakageError,
    assert_all_before,
    assert_issue_after_fit,
    assert_within_window,
)
from rupture.adapters.storage.run_log import JsonlTracker
from rupture.domain import Catalog, FitResult, Region, TestName
from rupture.pipelines.schedule import (
    RefitLogEntry,
    WindowRecord,
    check_fit_training,
    check_snapshot_constancy,
    issue_times,
    refit_boundaries,
    run_schedule,
)
from tests.unit.conftest import make_event
from tests.unit.forecasting.conftest import FIT_CUTOFF

DAY = timedelta(days=1)


def test_issue_times_close_at_or_before_end() -> None:
    start = datetime(2022, 1, 1, tzinfo=UTC)
    times = issue_times(start, datetime(2022, 4, 1, tzinfo=UTC), 30 * DAY, 30 * DAY)
    assert times == [start, start + 30 * DAY, start + 60 * DAY]
    assert times[-1] + 30 * DAY <= datetime(2022, 4, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="positive"):
        issue_times(start, start, timedelta(0), DAY)


def test_refit_boundaries_are_january_firsts_inside_the_schedule() -> None:
    start = datetime(2022, 1, 1, tzinfo=UTC)
    last = datetime(2026, 7, 2, tzinfo=UTC)
    assert refit_boundaries("yearly", start, last) == [
        datetime(y, 1, 1, tzinfo=UTC) for y in (2023, 2024, 2025, 2026)
    ]
    assert refit_boundaries("none", start, last) == []
    assert refit_boundaries("yearly", start, datetime(2022, 12, 2, tzinfo=UTC)) == []


def _window(issue: datetime, h: str) -> WindowRecord:
    return WindowRecord(
        issue_time=issue,
        window_end=issue + 30 * DAY,
        forecast_id="f",
        fit_cutoff=issue,
        parameter_snapshot_hash=h,
        total_expected=1.0,
        n_target_events=1,
        n_excluded_non_earthquake=0,
        n_excluded_no_mw=0,
        n_only=False,
    )


def test_snapshot_constancy_negative_and_positive() -> None:
    t0 = datetime(2022, 12, 2, tzinfo=UTC)
    windows = [_window(t0, "h1"), _window(t0 + 30 * DAY, "h2")]
    with pytest.raises(LeakageError, match="without a logged refit"):
        check_snapshot_constancy(windows, [])
    # a refit at a boundary inside (previous issue, issue] with the new hash is legitimate
    refit = RefitLogEntry(datetime(2023, 1, 1, tzinfo=UTC), "h2", "t", "run")
    check_snapshot_constancy(windows, [refit])
    # a refit logged *after* the window it would have to explain does not cover it
    late = RefitLogEntry(t0 + 45 * DAY, "h2", "t", "run")
    with pytest.raises(LeakageError):
        check_snapshot_constancy(windows, [late])


def test_fit_training_check_negative(committed_fit: FitResult) -> None:
    check_fit_training(committed_fit)
    bad = committed_fit.model_copy(
        update={
            "diagnostics": {
                **committed_fit.diagnostics,
                "training_max_origin_time": committed_fit.fit_cutoff.isoformat(),
            }
        }
    )
    with pytest.raises(LeakageError, match="not before the cutoff"):
        check_fit_training(bad)
    with pytest.raises(LeakageError, match="lacks"):
        check_fit_training(committed_fit.model_copy(update={"diagnostics": {}}))


def test_bare_assertions_on_real_timestamps(fixture_catalog: Catalog) -> None:
    assert_all_before(fixture_catalog.before(FIT_CUTOFF), FIT_CUTOFF, what="ok")
    with pytest.raises(LeakageError, match="origin_time >= 2019-07-01"):
        assert_all_before(fixture_catalog, FIT_CUTOFF, what="injected")
    window = fixture_catalog.between(FIT_CUTOFF, FIT_CUTOFF + 30 * DAY)
    assert_within_window(window, FIT_CUTOFF, FIT_CUTOFF + 30 * DAY, what="ok")
    with pytest.raises(LeakageError, match="before the window start"):
        assert_within_window(fixture_catalog, FIT_CUTOFF, FIT_CUTOFF + 30 * DAY, what="x")
    with pytest.raises(LeakageError, match="precedes"):
        assert_issue_after_fit(FIT_CUTOFF - DAY, FIT_CUTOFF)


def test_injected_post_cutoff_event_is_caught(fixture_catalog: Catalog) -> None:
    """The protocol's negative test: one event after the cut in an otherwise clean slice."""
    clean = fixture_catalog.before(FIT_CUTOFF)
    intruder = make_event(clean.events[0].provenance, eid="intruder", when=FIT_CUTOFF + DAY)
    dirty = clean.model_copy(update={"events": (*clean.events, intruder)})
    with pytest.raises(LeakageError) as err:
        assert_all_before(dirty, FIT_CUTOFF, what="fit training catalogue")
    assert "intruder" in str(err.value)


def test_schedule_on_the_fixture(
    tmp_path: Path,
    fixture_catalog: Catalog,
    region: Region,
    baselines_with_committed_fit: Path,
    committed_fit: FitResult,
) -> None:
    tracker = JsonlTracker(tmp_path / "runs.jsonl")
    report = run_schedule(
        fixture_catalog,
        region,
        start=FIT_CUTOFF,
        end=datetime(2019, 10, 1, tzinfo=UTC),
        step=30 * DAY,
        horizon=30 * DAY,
        baselines_dir=baselines_with_committed_fit,
        forecasts_dir=tmp_path / "data" / "forecasts",
        reports_dir=tmp_path / "reports",
        refit="yearly",
        model=MizrahiETAS(auxiliary_years=0.5),
        tracker=tracker,
        tests=(TestName.N, TestName.M, TestName.S),
        n_simulations=5,
        eval_simulations=50,
        seed=1,
        plots=False,
    )
    assert report["n_issued"] == 3
    assert report["n_scored"] == 3
    assert report["refits"] == [], "no 1 January inside Jul-Oct 2019"
    hashes = {w["parameter_snapshot_hash"] for w in report["windows"]}
    assert hashes == {committed_fit.parameter_snapshot_hash}, "the persisted fit was reused"
    first = report["windows"][0]
    assert first["issue_time"].startswith("2019-07-01")
    assert first["n_target_events"] > 50, "the Ridgecrest window"
    assert first["tests"]["N"]["passed"] is False, "ETAS from a quiet year cannot carry Ridgecrest"
    assert set(first["tests"]) == {"N", "M", "S"}
    assert report["pass_rates"]["N"]["scored"] == 3
    path = Path(report["report_path"])
    assert path.name == "schedule-california-fixture-etas-mizrahi.json"
    assert json.loads(path.read_text(encoding="utf-8"))["catalog_event_hash"] == (
        fixture_catalog.event_hash()
    )
    kinds = [r.kind for r in tracker.records()]
    assert kinds.count("issue") == 3
    assert kinds.count("evaluate") == 3
    assert "fit" not in kinds
    assert kinds[-1] == "schedule"
    for w in report["windows"]:
        bundle = tmp_path / "reports" / "eval" / w["forecast_id"]
        assert (bundle / "results.json").exists()
        assert (bundle / "target.parquet").exists()
