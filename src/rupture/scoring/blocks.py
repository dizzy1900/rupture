"""Intervals that survive clustering: the moving-block bootstrap over scored windows.

Every confidence interval in this repository's challenger evidence assumes the per-event
log-likelihood differences are independent. RELEASE_STATUS says so about the one metric this
project has ever beaten:

    The one metric beaten (Türkiye ensemble information gain) rests on an interval that assumes
    independent events

Earthquakes are the canonical counter-example. On the Türkiye schedule **160 of the 217 scored
target events fall in a single 30-day window** — the Kahramanmaraş sequence — so the Student-t
interval is counting one aftershock cascade as 160 independent observations. The 55 windows
carrying those events are worth about **1.8 independent windows** by Kish's measure.

The fix is the standard one for a dependent series: resample *blocks* rather than points. The
block here is the scored window, which is the unit a schedule actually issues, and a moving block
of ``block_length`` consecutive windows captures a sequence that spills across a window boundary.
``block_length=1`` is the plain window bootstrap. No single choice is allowed to carry a
conclusion: :func:`block_length_sensitivity` reports the interval across a range of lengths, and
the honest reading is whatever holds across all of them.

**What this changes, measured on the committed evidence.** Both conclusions hold at every block
length from 1 to 8 windows:

* The Türkiye log-linear ensemble **survives**. Its interval widens roughly fourfold and stays
  clear of zero, so the only positive result in this repository is not an artefact of the
  independence assumption. It is also strongly right-skewed, which a symmetric interval cannot
  express.
* The Nepal gridded ConvLSTM **does not**. It was published as significantly *worse* than ETAS
  (p = 0.0125); every block interval crosses zero. That verdict does not survive its own
  clustering correction.

This module reads the committed per-event log rates and recomputes. Nothing is re-fitted and no
model is loaded.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

BOOTSTRAP_VERSION = "1.0.0"
DEFAULT_RESAMPLES = 20_000
DEFAULT_LEVEL = 0.95
DEFAULT_BLOCK_LENGTHS: tuple[int, ...] = (1, 2, 3, 5, 8)


@dataclass(frozen=True, slots=True)
class BlockBootstrapResult:
    """One block-bootstrap interval for a pooled information gain."""

    observed: float
    lower: float
    upper: float
    level: float
    block_length: int
    n_resamples: int
    n_windows: int
    n_events: int
    effective_blocks: float
    skew: float
    normal_lower: float | None = None
    normal_upper: float | None = None

    @property
    def crosses_zero(self) -> bool:
        return self.lower <= 0.0 <= self.upper

    @property
    def width(self) -> float:
        return self.upper - self.lower

    @property
    def width_ratio(self) -> float | None:
        """How much wider than the published normal interval, if one was supplied."""
        if self.normal_lower is None or self.normal_upper is None:
            return None
        normal_width = self.normal_upper - self.normal_lower
        return None if normal_width <= 0 else self.width / normal_width

    @property
    def verdict_changed(self) -> bool | None:
        """True when the normal interval excluded zero and this one does not, or the reverse."""
        if self.normal_lower is None or self.normal_upper is None:
            return None
        normal_crosses = self.normal_lower <= 0.0 <= self.normal_upper
        return normal_crosses != self.crosses_zero

    def render(self) -> str:
        bits = [
            f"block={self.block_length}",
            f"IG {self.observed:+.4f}",
            f"{self.level:.0%} CI [{self.lower:+.4f}, {self.upper:+.4f}]",
        ]
        ratio = self.width_ratio
        if ratio is not None:
            bits.append(f"{ratio:.1f}x the normal width")
        bits.append("crosses zero" if self.crosses_zero else "excludes zero")
        if abs(self.skew) > 0.5:
            bits.append(f"skew {self.skew:+.2f} (a symmetric interval cannot express this)")
        return "; ".join(bits)


def _window_terms(window: dict[str, Any]) -> tuple[float, float, int] | None:
    """``(log-rate difference, forecast-count difference, events)`` for one window."""
    pooling = window.get("pooling")
    if not pooling:
        return None
    log_a = pooling.get("log_rates") or []
    log_b = pooling.get("benchmark_log_rates") or []
    if len(log_a) != len(log_b):
        msg = (
            f"window {window.get('issue_time')!r} has {len(log_a)} model log-rates against "
            f"{len(log_b)} benchmark ones; they are paired per event and must match"
        )
        raise ValueError(msg)
    diff = float(sum(log_a) - sum(log_b))
    counts = float(pooling.get("n_forecast", 0.0)) - float(pooling.get("benchmark_n_forecast", 0.0))
    return diff, counts, len(log_a)


def pooled_information_gain(windows: Sequence[dict[str, Any]]) -> float | None:
    """Rhoades et al. (2011) information gain per event, pooled over ``windows``.

    The same statistic ``pooled_paired_test`` publishes, recomputed from the committed per-event
    log rates so the bootstrap and the published point estimate cannot drift apart. ``None`` when
    the selection holds no target event.
    """
    total_diff = 0.0
    total_counts = 0.0
    n_events = 0
    for window in windows:
        terms = _window_terms(window)
        if terms is None:
            continue
        diff, counts, n = terms
        total_diff += diff
        total_counts += counts
        n_events += n
    if n_events == 0:
        return None
    return (total_diff - total_counts) / n_events


def effective_blocks(windows: Sequence[dict[str, Any]]) -> float:
    """Kish's effective number of independent windows, given how the events are distributed.

    ``(sum n_i)^2 / sum n_i^2``. Equal to the number of windows when every window carries the
    same count, and collapses towards one when a single window dominates. On the Türkiye schedule
    it is about 1.8, because one window holds 74 % of the events.
    """
    counts = [n for w in windows if (t := _window_terms(w)) is not None and (n := t[2]) > 0]
    total = sum(counts)
    if total == 0:
        return 0.0
    return float(total**2) / float(sum(c * c for c in counts))


def moving_block_bootstrap(
    windows: Sequence[dict[str, Any]],
    *,
    block_length: int = 1,
    n_resamples: int = DEFAULT_RESAMPLES,
    level: float = DEFAULT_LEVEL,
    rng: np.random.Generator | None = None,
    normal_lower: float | None = None,
    normal_upper: float | None = None,
) -> BlockBootstrapResult:
    """Percentile interval for the pooled information gain, resampling blocks of windows.

    Blocks are drawn circularly from the window sequence so that every window has equal
    probability of appearing, including those near the ends — the usual correction for a moving
    block bootstrap, and it matters here because the schedule is short.
    """
    if not windows:
        msg = "no windows to resample"
        raise ValueError(msg)
    if block_length < 1:
        msg = f"block_length must be at least 1, got {block_length}"
        raise ValueError(msg)
    if not 0.0 < level < 1.0:
        msg = f"level must lie in (0, 1), got {level}"
        raise ValueError(msg)
    observed = pooled_information_gain(windows)
    if observed is None:
        msg = "the schedule holds no target event, so there is no statistic to bootstrap"
        raise ValueError(msg)

    generator = rng if rng is not None else np.random.default_rng()
    n_windows = len(windows)
    block_length = min(block_length, n_windows)
    n_blocks = math.ceil(n_windows / block_length)

    draws: list[float] = []
    for _ in range(n_resamples):
        starts = generator.integers(0, n_windows, size=n_blocks)
        picked = [
            windows[(int(start) + offset) % n_windows]
            for start in starts
            for offset in range(block_length)
        ][:n_windows]
        value = pooled_information_gain(picked)
        if value is not None:
            draws.append(value)
    if len(draws) < 2:
        msg = (
            "almost every resample held no target event, so no interval can be formed; the "
            "schedule is too sparse for a block bootstrap at this block length"
        )
        raise ValueError(msg)

    sample = np.asarray(draws, dtype=np.float64)
    tail = (1.0 - level) / 2.0
    lower, upper = (float(v) for v in np.percentile(sample, [100 * tail, 100 * (1 - tail)]))
    spread = float(sample.std())
    skew = 0.0 if spread == 0.0 else float(((sample - sample.mean()) ** 3).mean() / spread**3)
    return BlockBootstrapResult(
        observed=observed,
        lower=lower,
        upper=upper,
        level=level,
        block_length=block_length,
        n_resamples=len(draws),
        n_windows=n_windows,
        n_events=sum(t[2] for w in windows if (t := _window_terms(w)) is not None),
        effective_blocks=effective_blocks(windows),
        skew=skew,
        normal_lower=normal_lower,
        normal_upper=normal_upper,
    )


def block_length_sensitivity(
    windows: Sequence[dict[str, Any]],
    *,
    lengths: Sequence[int] = DEFAULT_BLOCK_LENGTHS,
    n_resamples: int = DEFAULT_RESAMPLES,
    level: float = DEFAULT_LEVEL,
    seed: int | None = None,
    normal_lower: float | None = None,
    normal_upper: float | None = None,
) -> list[BlockBootstrapResult]:
    """The interval at several block lengths, so no single choice carries the conclusion.

    A block length is a modelling choice about how far dependence reaches, and there is no way to
    read it off 55 windows with confidence. Reporting the range is cheaper than defending a pick,
    and a conclusion that holds at every length is one the choice did not produce.
    """
    return [
        moving_block_bootstrap(
            windows,
            block_length=length,
            n_resamples=n_resamples,
            level=level,
            rng=np.random.default_rng(seed),
            normal_lower=normal_lower,
            normal_upper=normal_upper,
        )
        for length in lengths
    ]


def conclusion_holds_across_lengths(results: Sequence[BlockBootstrapResult]) -> bool | None:
    """True when every block length agrees on whether the interval excludes zero."""
    if not results:
        return None
    verdicts = {r.crosses_zero for r in results}
    return len(verdicts) == 1
