"""Strictly causal feature windows (ADR-0022 decision 2).

One rule, applied everywhere: **a feature evaluated at time *t* may use only events with
``origin_time < t``.** Windows are closed on the left and open on the right, so an event never
contributes to its own features and a window ending at *t* never includes *t*.

The implementation is a single primitive, :func:`n_strictly_before`, which every other function
here is built from. It uses ``np.searchsorted(..., side="left")``: for a query time *t* that
coincides exactly with one or more event times, ``side="left"`` returns the index of the first
such event, so those simultaneous events are excluded. ``side="right"`` would include them, and
that one character is the whole difference between a causal feature and a leaky one.

Simultaneous timestamps are common in real catalogues (rounded origin times, template-matched
detections), so this is not a hypothetical.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import numpy.typing as npt

_F8 = npt.NDArray[np.float64]
_I8 = npt.NDArray[np.int64]


def _check_sorted(times: _F8) -> None:
    if times.size > 1 and bool(np.any(np.diff(times) < 0.0)):
        msg = "times must be non-decreasing"
        raise ValueError(msg)


def n_strictly_before(times: npt.ArrayLike, query: npt.ArrayLike) -> _I8:
    """Number of ``times`` strictly less than each ``query`` value. The causal primitive.

    ``times`` must be non-decreasing. An event whose time equals the query time is **not**
    counted: the window is open on the right.
    """
    t = np.asarray(times, dtype=np.float64)
    q = np.asarray(query, dtype=np.float64)
    _check_sorted(t)
    out: _I8 = np.searchsorted(t, q, side="left").astype(np.int64)
    return out


def causal_bounds(times: npt.ArrayLike, query: npt.ArrayLike, length: float) -> tuple[_I8, _I8]:
    """Index bounds ``[lo, hi)`` of the window ``[q - length, q)`` for each query time.

    ``length`` is in the same units as ``times`` (days, for an
    :class:`~rupture.models.data.dataset.EventSequence`). The lower edge is closed and the upper
    edge is open, so ``times[lo:hi]`` is exactly the causal window.
    """
    if not np.isfinite(length) or length <= 0.0:
        msg = "window length must be positive and finite"
        raise ValueError(msg)
    t = np.asarray(times, dtype=np.float64)
    q = np.asarray(query, dtype=np.float64)
    _check_sorted(t)
    lo: _I8 = np.searchsorted(t, q - length, side="left").astype(np.int64)
    hi: _I8 = np.searchsorted(t, q, side="left").astype(np.int64)
    return lo, hi


def rolling_count(times: npt.ArrayLike, query: npt.ArrayLike, length: float) -> _I8:
    """How many events fall in ``[q - length, q)`` for each query time."""
    lo, hi = causal_bounds(times, query, length)
    out: _I8 = (hi - lo).astype(np.int64)
    return out


def rolling_reduce(
    times: npt.ArrayLike,
    values: npt.ArrayLike,
    query: npt.ArrayLike,
    length: float,
    reduce: Callable[[_F8], float],
    *,
    empty: float = 0.0,
) -> _F8:
    """Apply ``reduce`` to ``values`` inside each causal window ``[q - length, q)``.

    ``empty`` is used where the window holds no event, so a model never sees a NaN it did not ask
    for. The reduction is a plain Python callable because these windows are short; if that ever
    becomes the bottleneck, replace the loop, not the window semantics.
    """
    v = np.asarray(values, dtype=np.float64)
    lo, hi = causal_bounds(times, query, length)
    out = np.full(lo.shape, float(empty), dtype=np.float64)
    for k, (a, b) in enumerate(zip(lo.tolist(), hi.tolist(), strict=True)):
        if b > a:
            out[k] = float(reduce(v[a:b]))
    return out


def time_since_previous(
    times: npt.ArrayLike, query: npt.ArrayLike, *, empty: float = np.inf
) -> _F8:
    """``q - (the largest time strictly below q)``; ``empty`` where no earlier event exists."""
    t = np.asarray(times, dtype=np.float64)
    q = np.asarray(query, dtype=np.float64)
    idx = n_strictly_before(t, q) - 1
    out = np.full(q.shape, float(empty), dtype=np.float64)
    ok = idx >= 0
    out[ok] = q[ok] - t[idx[ok]]
    return out


def causal_feature_matrix(
    times: npt.ArrayLike,
    query: npt.ArrayLike,
    *,
    lengths: Sequence[float] = (1.0, 7.0, 30.0),
    magnitudes: npt.ArrayLike | None = None,
) -> tuple[_F8, tuple[str, ...]]:
    """A small, general causal history summary: log counts, max magnitude, recency.

    Columns are ``log1p_count_<L>d`` per window length, ``max_mw_<L>d`` per window length when
    ``magnitudes`` is given (``0.0`` where the window is empty), and ``log1p_days_since_previous``.
    Every column is a function of events strictly before the query time.

    This is offered as the shared default, not as a mandate: a model is free to build its own
    features, provided it builds them from :func:`causal_bounds`.
    """
    q = np.asarray(query, dtype=np.float64)
    columns: list[_F8] = []
    names: list[str] = []
    for length in lengths:
        columns.append(np.log1p(rolling_count(times, q, length).astype(np.float64)))
        names.append(f"log1p_count_{length:g}d")
    if magnitudes is not None:
        for length in lengths:
            columns.append(
                rolling_reduce(times, magnitudes, q, length, lambda a: float(a.max()), empty=0.0)
            )
            names.append(f"max_mw_{length:g}d")
    since = time_since_previous(times, q, empty=np.inf)
    columns.append(np.log1p(np.where(np.isfinite(since), since, 0.0)))
    names.append("log1p_days_since_previous")
    return np.column_stack(columns) if columns else np.zeros((q.size, 0)), tuple(names)
