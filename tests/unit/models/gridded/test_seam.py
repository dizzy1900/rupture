"""The pre-merge ``rupture.models.data`` seam only binds an implementation that behaves.

These tests exercise the self-checks directly. The point of the seam is that a shared helper with
a different convention cannot silently replace a leakage guard, so the interesting cases are the
ones where a plausible-looking candidate is rejected.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
import pytest

from rupture.adapters.forecasting.leakage import LeakageError
from rupture.models.challengers.gridded import _data


def test_the_local_fallbacks_pass_their_own_self_checks() -> None:
    _data._check_assert_before_cutoff(_data._local_assert_before_cutoff)
    _data._check_causal_window(_data._local_causal_window)
    _data._check_blocked_split(_data._local_blocked_time_forward_split)
    _data._check_scaler(_data._LocalTrainOnlyScaler)


def test_seam_source_names_the_live_implementation() -> None:
    assert _data.SEAM_SOURCE.startswith(("rupture.models.data", "gridded._data", "mixed:"))


def test_a_guard_that_filters_instead_of_raising_is_rejected() -> None:
    """The classic wrong implementation: drop the late records and carry on."""

    def filtering(times: Any, cutoff: datetime, *, what: str) -> None:
        return None

    with pytest.raises(AssertionError, match="did not raise"):
        _data._check_assert_before_cutoff(filtering)


def test_a_window_that_does_not_end_at_the_cut_is_rejected() -> None:
    """A frame convention off by one span would feed the model data it must not see."""

    def shifted(
        end: datetime, span_index: int, frame_span: float, n_frames: int
    ) -> tuple[float, float]:
        stop = end.timestamp() - (n_frames - span_index) * frame_span
        return stop - frame_span, stop

    with pytest.raises(AssertionError, match="does not end exactly"):
        _data._check_causal_window(shifted)


def test_a_split_with_the_wrong_boundary_is_rejected() -> None:
    def off_by_one(
        times: list[datetime], *, train_end: datetime, validation_end: datetime
    ) -> tuple[Any, Any]:
        train = np.array([i for i, t in enumerate(times) if t < train_end], dtype=np.int64)
        val = np.array(
            [i for i, t in enumerate(times) if train_end <= t <= validation_end], dtype=np.int64
        )
        return train, val

    with pytest.raises(AssertionError, match="blocked split sizes"):
        _data._check_blocked_split(off_by_one)


def test_a_scaler_that_loses_its_statistics_on_a_round_trip_is_rejected() -> None:
    class Forgetful(_data._LocalTrainOnlyScaler):
        def as_dict(self) -> dict[str, Any]:
            payload = super().as_dict()
            payload["std"] = [1.0 for _ in payload["std"]]
            return payload

    with pytest.raises(AssertionError, match="round trip"):
        _data._check_scaler(Forgetful)


class _FakeShared:
    """Stands in for a merged ``rupture.models.data`` whose guard filters instead of raising."""

    @staticmethod
    def assert_before_cutoff(times: Any, cutoff: datetime, *, what: str) -> None:
        return None


def test_a_rejected_candidate_leaves_the_fallback_live_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_before = list(_data.SEAM_NOTES)
    monkeypatch.setattr(_data, "_shared", lambda: _FakeShared)
    try:
        bound = _data._checked(
            "assert_before_cutoff",
            _data._local_assert_before_cutoff,
            _data._check_assert_before_cutoff,
        )
        assert bound is _data._local_assert_before_cutoff
        assert any("assert_before_cutoff" in note for note in _data.SEAM_NOTES)
    finally:
        _data.SEAM_NOTES[:] = notes_before


class _GoodShared:
    """Stands in for a merged module whose guard does obey the convention."""

    assert_before_cutoff = staticmethod(_data._local_assert_before_cutoff)


def test_a_candidate_that_passes_its_check_is_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    notes_before = list(_data.SEAM_NOTES)
    monkeypatch.setattr(_data, "_shared", lambda: _GoodShared)
    try:
        bound = _data._checked(
            "assert_before_cutoff",
            object(),
            _data._check_assert_before_cutoff,
        )
        assert bound is _data._local_assert_before_cutoff
        assert notes_before == _data.SEAM_NOTES
    finally:
        _data.SEAM_NOTES[:] = notes_before


def test_the_live_split_is_the_one_the_model_actually_uses() -> None:
    """Whichever side is bound, the model's own convention must hold."""
    base = datetime(2020, 1, 1, tzinfo=UTC)
    times = [base + timedelta(days=30 * k) for k in range(8)]
    train, val = _data.blocked_time_forward_split(
        times, train_end=times[3], validation_end=times[7]
    )
    assert max(times[int(i)] for i in train) < min(times[int(i)] for i in val)
    with pytest.raises(LeakageError, match="at or after"):
        _data.assert_before_cutoff(times, times[-1], what="seam test")
