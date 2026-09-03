"""PRE-MERGE SEAM. Delete this module when ``rupture.models.data`` lands on ``main``.

``rupture.models.data`` (dataset builders that raise on a post-cutoff event, strictly causal
windows, blocked time-forward splits, train-only normalisation) is built on a sibling branch and
does not exist in this worktree. The gridded challenger imports the four things it needs from
here instead: this module binds each of them to the shared implementation **when it is
importable**, and otherwise to a minimal local one that obeys exactly the same rules
(ADR-0022 decisions 1, 2, 3 and 5).

Nothing else in ``rupture.models.challengers.gridded`` imports ``rupture.models.data`` directly,
so the merge is a one-file deletion: point the four names at the shared module and drop the
fallbacks. ``SEAM_SOURCE`` records which side is live and is written into every fit's
diagnostics, so a persisted fit says which implementation produced it.

The fallbacks are deliberately minimal. They are not a second home for dataset code: anything
richer belongs in ``rupture.models.data``.
"""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import numpy.typing as npt

from rupture.adapters.forecasting.leakage import LeakageError

__all__ = [
    "SEAM_SOURCE",
    "LeakageError",
    "TrainOnlyScaler",
    "assert_before_cutoff",
    "blocked_time_forward_split",
    "causal_window",
]

SHARED_MODULE = "rupture.models.data"


def _shared() -> Any | None:
    try:
        return importlib.import_module(SHARED_MODULE)
    except ImportError:
        return None


# ---------------------------------------------------------------------- local fallbacks
def _local_assert_before_cutoff(
    times: Sequence[datetime] | npt.NDArray[Any], cutoff: datetime, *, what: str
) -> None:
    """ADR-0022 decision 1: refuse, never filter, when anything sits at or after the cutoff."""
    offenders = [t for t in times if t >= cutoff]
    if offenders:
        msg = (
            f"leakage: {what} contains {len(offenders)} record(s) at or after "
            f"{cutoff.isoformat()} (latest {max(offenders).isoformat()}); dataset builders refuse "
            f"post-cutoff data rather than dropping it"
        )
        raise LeakageError(msg)


def _local_causal_window(
    end: datetime, span_index: int, frame_span: float, n_frames: int
) -> tuple[float, float]:
    """ADR-0022 decision 2: closed-left, open-right frame bounds, all strictly before ``end``.

    Frame ``span_index`` (0 = oldest) of ``n_frames`` frames of ``frame_span`` seconds each,
    the last of which ends exactly at ``end``. Returned as epoch seconds so the caller can bin
    with numpy without leaving UTC.
    """
    if not 0 <= span_index < n_frames:
        msg = f"span_index {span_index} outside [0, {n_frames})"
        raise ValueError(msg)
    stop = end.timestamp() - (n_frames - 1 - span_index) * frame_span
    return stop - frame_span, stop


def _local_blocked_time_forward_split(
    times: Sequence[datetime], *, train_end: datetime, validation_end: datetime
) -> tuple[npt.NDArray[np.int64], npt.NDArray[np.int64]]:
    """ADR-0022 decision 3: one blocked, time-forward cut. There is no shuffle parameter.

    Returns the indices of samples whose window ends at or before ``train_end`` and of samples
    whose window ends in ``(train_end, validation_end]``. Every validation index is strictly
    later than every training index, and that is asserted here rather than trusted.
    """
    if validation_end <= train_end:
        msg = "validation_end must be after train_end"
        raise ValueError(msg)
    train = np.array([i for i, t in enumerate(times) if t <= train_end], dtype=np.int64)
    val = np.array(
        [i for i, t in enumerate(times) if train_end < t <= validation_end], dtype=np.int64
    )
    if len(train) and len(val):
        latest_train = max(times[int(i)] for i in train)
        earliest_val = min(times[int(i)] for i in val)
        if earliest_val <= latest_train:
            msg = "blocked split is not time-forward: a validation sample precedes a training one"
            raise LeakageError(msg)
    return train, val


@dataclass
class _LocalTrainOnlyScaler:
    """ADR-0022 decision 5: per-channel mean/std from training data only, carried with the model."""

    mean: npt.NDArray[np.float64]
    std: npt.NDArray[np.float64]
    fitted_on: str

    @classmethod
    def fit(
        cls, values: npt.NDArray[np.float64], *, axis: tuple[int, ...], fitted_on: str
    ) -> _LocalTrainOnlyScaler:
        mean = np.asarray(values.mean(axis=axis), dtype=np.float64)
        std = np.asarray(values.std(axis=axis), dtype=np.float64)
        std = np.where(std < 1e-8, 1.0, std)
        return cls(mean=mean, std=std, fitted_on=fitted_on)

    def transform(self, values: npt.NDArray[np.float64]) -> npt.NDArray[np.float64]:
        out: npt.NDArray[np.float64] = (values - self.mean) / self.std
        return out

    def as_dict(self) -> dict[str, Any]:
        return {
            "mean": [float(v) for v in np.ravel(self.mean)],
            "std": [float(v) for v in np.ravel(self.std)],
            "fitted_on": self.fitted_on,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> _LocalTrainOnlyScaler:
        return cls(
            mean=np.asarray(payload["mean"], dtype=np.float64),
            std=np.asarray(payload["std"], dtype=np.float64),
            fitted_on=str(payload["fitted_on"]),
        )


# ---------------------------------------------------------------------- binding
_module = _shared()
assert_before_cutoff = getattr(_module, "assert_before_cutoff", _local_assert_before_cutoff)
causal_window = getattr(_module, "causal_window", _local_causal_window)
blocked_time_forward_split = getattr(
    _module, "blocked_time_forward_split", _local_blocked_time_forward_split
)
TrainOnlyScaler = getattr(_module, "TrainOnlyScaler", _LocalTrainOnlyScaler)

SEAM_SOURCE: str = (
    SHARED_MODULE
    if _module is not None and hasattr(_module, "blocked_time_forward_split")
    else "gridded._data (pre-merge fallback)"
)
