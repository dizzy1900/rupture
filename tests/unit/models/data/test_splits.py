"""Blocked time-forward CV: every validation index is later than every training index, and a
random shuffle is not expressible (ADR-0022 decision 3, protocol § 7 rule 6)."""

from __future__ import annotations

import inspect
import random
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, Region
from rupture.models.data import blocked_splits, build_sequence, causal_slice, split_indices
from rupture.models.data import splits as splits_module
from tests.unit.models.conftest import CUTOFF, MC

START = datetime(2018, 1, 1, tzinfo=UTC)


def test_the_splitter_api_has_no_shuffle_or_seed() -> None:
    """The forbidden option is absent from the signature, not merely defaulted to False."""
    names = set(inspect.signature(blocked_splits).parameters)
    assert not names & {"shuffle", "random_state", "seed", "rng", "stratify"}


def test_the_splits_module_imports_no_randomness() -> None:
    """No generator, no permutation, no reordering call anywhere in the module."""
    source = inspect.getsource(splits_module)
    for forbidden in ("import random", "np.random", "numpy.random", ".shuffle(", "permutation"):
        assert forbidden not in source, f"splits.py must not contain {forbidden!r}"


def test_every_validation_index_is_later_than_every_training_index(
    fixture_catalog: Catalog, region: Region
) -> None:
    """The property, over many random configurations of the *splitter* (not of the data)."""
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    # Randomising the *splitter configuration*, never the data order.
    rng = random.Random(20220101)
    checked = 0
    for _ in range(200):
        n_folds = rng.randint(1, 6)
        gap = timedelta(days=rng.choice([0, 1, 7, 30]))
        expanding = rng.choice([True, False])
        span_days = rng.randint(120, 540)
        end = START + timedelta(days=span_days)
        try:
            folds = blocked_splits(START, end, n_folds, gap=gap, expanding=expanding)
        except ValueError:
            continue
        for fold in folds:
            assert fold.train_end <= fold.val_start
            assert fold.gap == gap
            train, val = split_indices(sequence.t, sequence.spec.epoch, fold)
            if train.size and val.size:
                assert float(sequence.t[train].max()) < float(sequence.t[val].min())
                assert not set(train.tolist()) & set(val.tolist())
                checked += 1
    assert checked > 50, "the property test did not exercise enough non-empty folds"


def test_split_indices_raise_if_the_order_is_ever_violated() -> None:
    """A hand-built split that overlaps is rejected at construction, and a shuffled time array is
    rejected by the index builder."""
    with pytest.raises(ValueError, match="train_start < train_end <= val_start"):
        splits_module.BlockedSplit(
            fold=0,
            train_start=START,
            train_end=START + timedelta(days=100),
            val_start=START + timedelta(days=50),
            val_end=START + timedelta(days=150),
        )
    fold = blocked_splits(START, START + timedelta(days=300), 1)[0]
    scrambled = np.array([10.0, 3.0, 200.0, 50.0])
    with pytest.raises(ValueError, match="non-decreasing"):
        split_indices(scrambled, START, fold)


def test_expanding_and_rolling_training_windows_differ_as_documented() -> None:
    end = START + timedelta(days=400)
    expanding = blocked_splits(START, end, 3, expanding=True)
    rolling = blocked_splits(START, end, 3, expanding=False)
    assert all(f.train_start == START for f in expanding)
    assert rolling[-1].train_start > rolling[0].train_start
    assert all(
        f.train_end - f.train_start == rolling[0].train_end - rolling[0].train_start
        for f in rolling
    )


def test_a_gap_pushes_validation_later_without_extending_training() -> None:
    end = START + timedelta(days=400)
    without = blocked_splits(START, end, 2)[0]
    with_gap = blocked_splits(START, end, 2, gap=timedelta(days=30))[0]
    assert with_gap.train_end == without.train_end
    assert with_gap.val_start == without.val_start + timedelta(days=30)


def test_min_train_drops_folds_that_are_too_short() -> None:
    end = START + timedelta(days=400)
    all_folds = blocked_splits(START, end, 3)
    long_only = blocked_splits(START, end, 3, min_train=timedelta(days=200))
    assert len(long_only) < len(all_folds)
    assert all(f.train_end - f.train_start >= timedelta(days=200) for f in long_only)


def test_leakage_error_is_raised_when_indices_would_overlap() -> None:
    """The belt-and-braces check in ``split_indices`` fires if the boundaries ever lie."""
    fold = blocked_splits(START, START + timedelta(days=300), 1)[0]
    broken = splits_module.BlockedSplit.__new__(splits_module.BlockedSplit)
    object.__setattr__(broken, "fold", 0)
    object.__setattr__(broken, "train_start", START)
    object.__setattr__(broken, "train_end", fold.val_end)
    object.__setattr__(broken, "val_start", fold.val_start)
    object.__setattr__(broken, "val_end", fold.val_end)
    times = np.arange(0.0, 300.0, 5.0)
    with pytest.raises(LeakageError, match="training event at or after"):
        split_indices(times, START, broken)
