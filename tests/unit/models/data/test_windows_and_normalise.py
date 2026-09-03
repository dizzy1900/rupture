"""Causal windows (decision 2) and training-only normalisation (decision 5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, Region
from rupture.models.data import (
    Standardiser,
    build_sequence,
    causal_bounds,
    causal_feature_matrix,
    causal_slice,
    n_strictly_before,
    rolling_count,
    rolling_reduce,
    time_since_previous,
)
from tests.unit.models.conftest import CUTOFF, MC


def test_a_simultaneous_event_is_excluded_from_its_own_window() -> None:
    """The whole of decision 2 in one assertion: the window is open on the right."""
    times = np.array([0.0, 1.0, 1.0, 1.0, 2.0])
    assert n_strictly_before(times, [1.0]).tolist() == [1]
    assert rolling_count(times, [1.0], 10.0).tolist() == [1]
    assert n_strictly_before(times, [1.0000001]).tolist() == [4]


def test_causal_bounds_are_closed_left_and_open_right() -> None:
    times = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    lo, hi = causal_bounds(times, [3.0], 2.0)
    assert times[lo[0] : hi[0]].tolist() == [1.0, 2.0]  # [1.0, 3.0): 3.0 excluded, 1.0 included


def test_rolling_features_on_a_real_sequence_use_only_earlier_events(
    fixture_catalog: Catalog, region: Region
) -> None:
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    counts = rolling_count(sequence.t, sequence.t, 30.0)
    # An event never counts itself, so the first event's 30-day window is empty.
    assert counts[0] == 0
    for k in range(1, min(len(sequence), 60)):
        window = sequence.t[(sequence.t >= sequence.t[k] - 30.0) & (sequence.t < sequence.t[k])]
        assert counts[k] == window.size


def test_rolling_reduce_reports_the_empty_value_where_no_event_qualifies() -> None:
    times = np.array([0.0, 100.0])
    values = np.array([5.0, 6.0])
    out = rolling_reduce(times, values, np.array([0.0, 1.0, 101.0]), 1.0, lambda a: float(a.max()))
    # q=0: window [-1, 0) is empty -> the empty value; q=1: [0, 1) holds the first event;
    # q=101: [100, 101) holds the second.
    assert out.tolist() == [0.0, 5.0, 6.0]


def test_time_since_previous_is_infinite_before_the_first_event() -> None:
    times = np.array([10.0, 20.0])
    out = time_since_previous(times, np.array([5.0, 15.0, 25.0]))
    assert not np.isfinite(out[0])
    assert out[1] == pytest.approx(5.0)
    assert out[2] == pytest.approx(5.0)


def test_causal_feature_matrix_columns_are_named_and_finite(
    fixture_catalog: Catalog, region: Region
) -> None:
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    matrix, names = causal_feature_matrix(sequence.t, sequence.t, magnitudes=sequence.mw)
    assert matrix.shape == (len(sequence), len(names))
    assert np.all(np.isfinite(matrix))
    assert "log1p_count_30d" in names
    assert "max_mw_7d" in names


def test_a_feature_at_t_is_unchanged_by_anything_after_t(
    fixture_catalog: Catalog, region: Region
) -> None:
    """Truncating the future must not move a causal feature. If it does, it was not causal."""
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    half = len(sequence) // 2
    full, _ = causal_feature_matrix(sequence.t, sequence.t[:half], magnitudes=sequence.mw)
    truncated, _ = causal_feature_matrix(
        sequence.t[:half], sequence.t[:half], magnitudes=sequence.mw[:half]
    )
    assert np.allclose(full, truncated)


# ---------------------------------------------------------------------- normalisation
def test_normalisation_refuses_rows_at_or_after_the_cut(
    fixture_catalog: Catalog, region: Region
) -> None:
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    features = np.column_stack([sequence.mw, np.nan_to_num(sequence.depth_km)])
    split = sequence.spec.epoch + timedelta(days=float(sequence.t[len(sequence) // 2]))
    with pytest.raises(LeakageError, match="normalisation statistics must be fitted"):
        Standardiser.fit_causal(
            features,
            ("mw", "depth"),
            times=sequence.t,
            epoch=sequence.spec.epoch,
            before=split,
        )


def test_normalisation_fitted_before_the_cut_cannot_see_later_rows(
    fixture_catalog: Catalog, region: Region
) -> None:
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    features = np.column_stack([sequence.mw, np.nan_to_num(sequence.depth_km)])
    half = len(sequence) // 2
    split = sequence.spec.epoch + timedelta(days=float(sequence.t[half]))
    train = Standardiser.fit_causal(
        features[:half],
        ("mw", "depth"),
        times=sequence.t[:half],
        epoch=sequence.spec.epoch,
        before=split,
    )
    everything = Standardiser.fit(features, ("mw", "depth"))
    assert train.n_rows_fitted == half
    assert train.fitted_before == split
    assert not np.allclose(train.mean, everything.mean)
    assert np.allclose(train.mean, features[:half].mean(axis=0))


def test_standardiser_round_trips_and_digests_change_with_the_statistics() -> None:
    a = Standardiser.fit(np.array([[1.0, 2.0], [3.0, 6.0]]), ("x", "y"))
    b = Standardiser.fit(np.array([[1.0, 2.0], [3.0, 7.0]]), ("x", "y"))
    assert Standardiser.from_dict(a.to_dict()).digest() == a.digest()
    assert a.digest() != b.digest()
    assert np.allclose(a.inverse_transform(a.transform([[1.0, 2.0]])), [[1.0, 2.0]])


def test_a_constant_column_is_left_alone_rather_than_divided_by_zero() -> None:
    s = Standardiser.fit(np.array([[5.0, 1.0], [5.0, 2.0]]), ("constant", "varying"))
    assert s.scale[0] == 1.0
    assert np.all(np.isfinite(s.transform([[5.0, 1.5]])))


def test_fitting_on_no_rows_is_an_error() -> None:
    with pytest.raises(ValueError, match="zero rows"):
        Standardiser.fit(np.zeros((0, 2)), ("a", "b"))


def test_epoch_is_shared_across_slices(fixture_catalog: Catalog, region: Region) -> None:
    """Two sequences built with the same epoch put the same event at the same time coordinate."""
    early = build_sequence(
        causal_slice(fixture_catalog, region, datetime(2019, 1, 1, tzinfo=UTC), MC),
        region,
        datetime(2019, 1, 1, tzinfo=UTC),
        mc=MC,
    )
    later = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC),
        region,
        CUTOFF,
        mc=MC,
        epoch=early.spec.epoch,
        projection=early.spec.projection,
    )
    assert later.event_ids[: len(early)] == early.event_ids
    assert np.allclose(later.t[: len(early)], early.t)
