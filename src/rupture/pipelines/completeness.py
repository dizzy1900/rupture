"""Magnitude of completeness (Mc) and b-value estimators.

Two estimators are always reported, never silently chosen between (``CompletenessEstimate`` per
method; ``Catalog.completeness`` holds all of them):

* **Maximum curvature** (Wiemer & Wyss 2000): the magnitude bin with the most events in the
  non-cumulative frequency-magnitude distribution, plus the +0.2 correction recommended by
  Woessner & Wiemer (2005) because MAXC under-estimates Mc for gradually curved distributions.
* **b-value stability** (Cao & Gao 2002, as operationalised by Woessner & Wiemer 2005): the
  smallest cut-off Mc at which the mean b-value over the next five successive 0.1 bins
  (Mc, Mc+0.1, ..., Mc+0.4) lies within the b-value uncertainty of b(Mc).

b is the Aki (1965) maximum-likelihood estimate with the Utsu (1965) half-bin correction,
``b = log10(e) / (mean(m) - (Mc - dm/2))``, and its uncertainty is the Shi & Bolt (1982)
estimate ``2.3 b^2 sqrt(sum (m_i - mean)^2 / (n (n - 1)))``.

An optional third estimate, ``mc_ks``, cross-checks with the ``etas`` package
(``etas.mc_b_est.estimate_mc``, Mizrahi et al. 2021); it is reported only when that call
succeeds and is never required.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import numpy as np
from numpy.typing import NDArray

from rupture.domain import CompletenessEstimate, McMethod, utc_now

log = logging.getLogger(__name__)

LOG10_E = math.log10(math.e)
MAXC_CORRECTION = 0.2
STABILITY_BINS = 5
MIN_EVENTS_FOR_B = 30

MagArray = Sequence[float] | NDArray[np.floating[Any]]


class InsufficientDataError(ValueError):
    """Not enough magnitudes for a meaningful estimate."""


def bin_magnitudes(mags: MagArray, delta_m: float = 0.1) -> np.ndarray:
    """Round magnitudes to the nearest bin centre (half-up), to kill float noise like 4.4999."""
    arr = np.asarray(mags, dtype=float)
    return np.floor(arr / delta_m + 0.5 + 1e-9) * delta_m


def b_value_aki(mags: MagArray, mc: float, delta_m: float = 0.1) -> tuple[float, float, int]:
    """Aki (1965) MLE b with the half-bin correction; Shi & Bolt (1982) uncertainty; n used."""
    arr = np.asarray(mags, dtype=float)
    sel = arr[arr >= mc - delta_m / 2 - 1e-9]
    n = int(sel.size)
    if n < 2:
        msg = f"need >= 2 magnitudes at or above {mc}, have {n}"
        raise InsufficientDataError(msg)
    mean = float(sel.mean())
    denom = mean - (mc - delta_m / 2)
    if denom <= 0:
        msg = "mean magnitude is not above the completeness cut-off"
        raise InsufficientDataError(msg)
    b = LOG10_E / denom
    sigma = 2.3 * b * b * math.sqrt(float(((sel - mean) ** 2).sum()) / (n * (n - 1)))
    return b, sigma, n


def maximum_curvature(
    mags: MagArray, delta_m: float = 0.1, correction: float = MAXC_CORRECTION
) -> float:
    """Mode of the binned (non-cumulative) FMD plus ``correction``."""
    binned = bin_magnitudes(mags, delta_m)
    if binned.size == 0:
        msg = "no magnitudes"
        raise InsufficientDataError(msg)
    values, counts = np.unique(np.round(binned, 6), return_counts=True)
    # ties: take the lowest magnitude among the maxima (conservative? no: lowest Mc, so we
    # add the correction on top; documented in docs/CATALOG_BUILD.md)
    top = values[counts == counts.max()].min()
    return round(float(top) + correction, 2)


def b_value_stability(
    mags: MagArray,
    delta_m: float = 0.1,
    n_bins: int = STABILITY_BINS,
    min_events: int = MIN_EVENTS_FOR_B,
) -> tuple[float, float, float, int] | None:
    """Cao & Gao (2002) / Woessner & Wiemer (2005) b-value stability Mc.

    Returns ``(mc, b, sigma_b, n)`` for the smallest cut-off whose b is within ``sigma_b`` of the
    mean b over the next ``n_bins`` cut-offs, or ``None`` when no cut-off is stable (that is a
    result, and it is reported as such rather than replaced by a guess).
    """
    binned = bin_magnitudes(mags, delta_m)
    if binned.size < min_events:
        return None
    lo = float(np.round(binned.min(), 6))
    hi = float(np.round(binned.max(), 6))
    cutoffs = np.round(np.arange(lo, hi + delta_m / 2, delta_m), 6)
    b_at: dict[float, tuple[float, float, int]] = {}
    for mc in cutoffs:
        try:
            b, sig, n = b_value_aki(binned, float(mc), delta_m)
        except InsufficientDataError:
            continue
        if n >= min_events:
            b_at[float(mc)] = (b, sig, n)
    for mc in cutoffs:
        key = float(mc)
        if key not in b_at:
            continue
        window = [float(np.round(key + i * delta_m, 6)) for i in range(n_bins)]
        if not all(w in b_at for w in window):
            continue
        b, sig, n = b_at[key]
        b_mean = float(np.mean([b_at[w][0] for w in window]))
        if abs(b_mean - b) <= sig:
            return key, b, sig, n
    return None


def estimate_completeness(
    mags: Sequence[float | None],
    *,
    window_start: datetime,
    window_end: datetime,
    delta_m: float = 0.1,
    with_etas_cross_check: bool = True,
) -> list[CompletenessEstimate]:
    """All Mc estimates for a set of Mw values. Reports each method; never picks silently.

    Raises :class:`InsufficientDataError` when fewer than two magnitudes are supplied; the caller
    records that the catalogue slice was too thin for a completeness estimate.
    """
    arr = np.asarray([m for m in mags if m is not None], dtype=float)
    if arr.size < 2:
        msg = f"completeness needs >= 2 magnitudes, have {arr.size}"
        raise InsufficientDataError(msg)
    now = utc_now()
    out: list[CompletenessEstimate] = []

    mc_maxc = maximum_curvature(arr, delta_m)
    try:
        b, sig, n = b_value_aki(arr, mc_maxc, delta_m)
    except InsufficientDataError:
        b_opt: float | None = None
        sig_opt: float | None = None
        n = int((arr >= mc_maxc - delta_m / 2).sum())
    else:
        b_opt, sig_opt = b, sig
    out.append(
        CompletenessEstimate(
            mc=mc_maxc,
            method=McMethod.MAXIMUM_CURVATURE,
            b_value=b_opt,
            b_value_uncertainty=sig_opt,
            n_events=n,
            window_start=window_start,
            window_end=window_end,
            computed_at=now,
            correction=MAXC_CORRECTION,
            notes="Wiemer & Wyss 2000 MAXC + 0.2 (Woessner & Wiemer 2005); b: Aki 1965 MLE",
        )
    )

    stab = b_value_stability(arr, delta_m)
    if stab is not None:
        mc_s, b_s, sig_s, n_s = stab
        out.append(
            CompletenessEstimate(
                mc=round(mc_s, 2),
                method=McMethod.B_VALUE_STABILITY,
                b_value=b_s,
                b_value_uncertainty=sig_s,
                n_events=n_s,
                window_start=window_start,
                window_end=window_end,
                computed_at=now,
                notes=(
                    f"Cao & Gao 2002: mean b over next {STABILITY_BINS} bins within sigma_b; "
                    f"min {MIN_EVENTS_FOR_B} events per cut-off"
                ),
            )
        )
    else:
        log.info("completeness: no stable b-value cut-off found (n=%d)", arr.size)

    if with_etas_cross_check:
        ks = _etas_mc_ks(arr, delta_m)
        if ks is not None:
            mc_ks, beta = ks
            b_ks = beta / math.log(10.0) if beta else None
            n_ks = int((arr >= mc_ks - delta_m / 2).sum())
            out.append(
                CompletenessEstimate(
                    mc=round(float(mc_ks), 2),
                    method=McMethod.MC_KS,
                    b_value=b_ks if b_ks and b_ks > 0 else None,
                    n_events=n_ks,
                    window_start=window_start,
                    window_end=window_end,
                    computed_at=now,
                    notes="etas.mc_b_est.estimate_mc (Mizrahi et al. 2021) KS test, p >= 0.1",
                )
            )
    return out


def _etas_mc_ks(
    arr: NDArray[np.floating[Any]], delta_m: float
) -> tuple[float, float | None] | None:
    """Cross-check with the ``etas`` package; ``None`` if unavailable or nothing passes."""
    try:
        from etas.mc_b_est import estimate_mc  # noqa: PLC0415  (optional heavy import)
    except Exception:
        return None
    binned = bin_magnitudes(arr, delta_m)
    lo = float(np.round(binned.min(), 6))
    hi = float(np.round(np.quantile(binned, 0.9), 6))
    mcs = np.round(np.arange(lo, hi + delta_m / 2, delta_m), 6)
    if mcs.size == 0:
        return None
    try:
        _, _, _, best_mc, beta = estimate_mc(
            binned, mcs, delta_m, p_pass=0.1, stop_when_passed=True, n_samples=2000
        )
    except Exception as exc:
        log.info("completeness: etas cross-check failed: %s", exc)
        return None
    if best_mc is None:
        return None
    return float(best_mc), (float(beta) if beta is not None else None)
