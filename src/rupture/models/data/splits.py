"""Blocked time-forward cross-validation. There is no other kind here (ADR-0022 decision 3).

Random k-fold on an earthquake catalogue leaks: aftershocks of a mainshock in a training fold land
in the validation fold, so the model is scored on sequences it has effectively already seen. The
protocol (§ 7 rule 6) forbids it, and this module makes it unavailable rather than discouraged:
the API offers no way to reorder anything, and nothing here imports a random number generator. A
test asserts both — that the signature carries no such option, and that the source imports no
source of randomness.

A split is a pair of half-open time intervals with ``train_end <= val_start``. Because the cut is
on time and every index is derived from it by ``searchsorted``, every validation index is strictly
later than every training index by construction; :func:`split_indices` re-checks it anyway, and a
property test asserts it over many random configurations.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import numpy.typing as npt

from rupture.adapters.forecasting.leakage import LeakageError

_I8 = npt.NDArray[np.int64]


@dataclass(frozen=True)
class BlockedSplit:
    """One time-forward fold.

    Train on ``[train_start, train_end)``; validate on ``[val_start, val_end)``.
    """

    fold: int
    train_start: datetime
    train_end: datetime
    val_start: datetime
    val_end: datetime

    def __post_init__(self) -> None:
        if not (self.train_start < self.train_end <= self.val_start < self.val_end):
            msg = (
                "a blocked split must satisfy train_start < train_end <= val_start < val_end; got "
                f"{self.train_start.isoformat()} / {self.train_end.isoformat()} / "
                f"{self.val_start.isoformat()} / {self.val_end.isoformat()}"
            )
            raise ValueError(msg)

    @property
    def gap(self) -> timedelta:
        return self.val_start - self.train_end

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold": self.fold,
            "train_start": self.train_start.isoformat(),
            "train_end": self.train_end.isoformat(),
            "val_start": self.val_start.isoformat(),
            "val_end": self.val_end.isoformat(),
        }


def blocked_splits(
    start: datetime,
    end: datetime,
    n_folds: int,
    *,
    gap: timedelta = timedelta(0),
    expanding: bool = True,
    min_train: timedelta | None = None,
) -> list[BlockedSplit]:
    """Time-forward folds over ``[start, end)``.

    The span is divided into ``n_folds + 1`` equal blocks. Fold *k* validates on block *k + 1* and
    trains on everything before it (``expanding=True``, the default) or on block *k* alone
    (``expanding=False``, a rolling window). ``gap`` inserts dead time between the end of training
    and the start of validation, which is how you stop an aftershock sequence straddling the cut
    from carrying information across it.

    There is deliberately no way to reorder the events. If you want one, you want a different
    validation scheme, and ADR-0022 says no.
    """
    if n_folds < 1:
        msg = "n_folds must be >= 1"
        raise ValueError(msg)
    if end <= start:
        msg = "end must be after start"
        raise ValueError(msg)
    if gap < timedelta(0):
        msg = "gap must not be negative"
        raise ValueError(msg)
    span = (end - start) / (n_folds + 1)
    if span <= timedelta(0):
        msg = "the span is too short to divide into folds"
        raise ValueError(msg)
    out: list[BlockedSplit] = []
    for k in range(n_folds):
        block_end = start + span * (k + 1)
        val_start = block_end + gap
        val_end = min(val_start + span, end)
        if val_end <= val_start:
            break
        train_start = start if expanding else start + span * k
        if min_train is not None and block_end - train_start < min_train:
            continue
        out.append(
            BlockedSplit(
                fold=k,
                train_start=train_start,
                train_end=block_end,
                val_start=val_start,
                val_end=val_end,
            )
        )
    if not out:
        msg = (
            f"no fold survives: {n_folds} folds over "
            f"{(end - start).total_seconds() / 86400.0:.2f} days with gap {gap} and "
            f"min_train {min_train}"
        )
        raise ValueError(msg)
    return out


def iter_blocked_splits(
    start: datetime, end: datetime, n_folds: int, **kwargs: Any
) -> Iterator[BlockedSplit]:
    """Iterator form of :func:`blocked_splits`, in time order. Never shuffled."""
    yield from blocked_splits(start, end, n_folds, **kwargs)


def split_indices(times: npt.ArrayLike, epoch: datetime, split: BlockedSplit) -> tuple[_I8, _I8]:
    """Training and validation index arrays for event ``times`` (float days since ``epoch``).

    Raises :class:`~rupture.adapters.forecasting.leakage.LeakageError` if any validation index is
    not strictly later than every training index — which cannot happen by construction, and is
    checked because "cannot happen" is what leakage looks like from the inside.
    """
    t = np.asarray(times, dtype=np.float64)
    if t.size > 1 and bool(np.any(np.diff(t) < 0.0)):
        msg = "times must be non-decreasing"
        raise ValueError(msg)

    def days(when: datetime) -> float:
        return (when - epoch).total_seconds() / 86400.0

    train = np.flatnonzero((t >= days(split.train_start)) & (t < days(split.train_end)))
    val = np.flatnonzero((t >= days(split.val_start)) & (t < days(split.val_end)))
    if train.size and val.size and float(t[train].max()) >= float(t[val].min()):
        msg = (
            f"leakage: fold {split.fold} has a training event at or after the first validation "
            f"event ({t[train].max()} >= {t[val].min()} days since epoch)"
        )
        raise LeakageError(msg)
    return train.astype(np.int64), val.astype(np.int64)
