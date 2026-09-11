"""How large an effect a test could have found, and how often it would have found it.

ADR-0055 decision 4: a p-value without a power figure is not a finding. Decision 5: a null result
states the smallest effect it could have detected, not that it saw nothing. Neither rule is
rhetorical. Khawaja et al. (2023) show the CSEP S-test cannot reject a uniform, non-informative
global forecast on a 0.1 degree grid without roughly 32,000 events — about three centuries — so a
passing S-test on a decade of data may be reporting nothing but its own blindness. Nakatani (2020)
sets the scale an alarm experiment has to be powered for: every non-triggering precursor
phenomenon he reviews sits at probability gain *G* < 20 and mostly near 2, while clustering alone
gives *G* in the hundreds. An experiment whose minimum detectable gain is 40 has already decided
its answer.

For the alarm arm all of this is exact rather than simulated. Under the null, hits in an alarm of
reference mass ``tau`` are ``Binomial(N, tau)``; under the alternative "this alarm has true
probability gain *G*" they are ``Binomial(N, min(G * tau, 1))``. Everything below follows from
those two lines.
"""

from __future__ import annotations

import math

from scipy.stats import binom, norm

MAX_GAIN_STEPS = 4096


def critical_hits(n_targets: int, tau: float, alpha: float) -> int | None:
    """Fewest hits that reject the reference at ``alpha``; ``None`` when no outcome would.

    ``None`` is not an error and is the more interesting answer: it means the test had no
    rejection region at all, so its "pass" carried no information whatsoever.
    """
    _check(n_targets, tau, alpha)
    if n_targets == 0:
        return None
    for c in range(n_targets + 1):
        if float(binom.sf(c - 1, n_targets, tau)) <= alpha:
            return c
    return None


def power_at_gain(n_targets: int, tau: float, gain: float, alpha: float) -> float:
    """P(reject the reference | the alarm's true probability gain is ``gain``)."""
    _check(n_targets, tau, alpha)
    if gain < 0.0:
        msg = f"probability gain must be non-negative, got {gain}"
        raise ValueError(msg)
    c = critical_hits(n_targets, tau, alpha)
    if c is None:
        return 0.0
    return float(binom.sf(c - 1, n_targets, min(gain * tau, 1.0)))


def minimum_detectable_gain(
    n_targets: int, tau: float, alpha: float = 0.05, target_power: float = 0.8
) -> float | None:
    """Smallest true probability gain rejected at ``target_power``; ``None`` if unreachable.

    ``None`` means no probability gain whatever — not even a perfect alarm that catches every
    event inside its footprint — would be detected at this sample size and alarm fraction. Report
    it as the upper bound the experiment actually achieved, which is ``1 / tau`` and unattained.
    """
    _check(n_targets, tau, alpha)
    if not 0.0 < target_power < 1.0:
        msg = f"target_power must lie in (0, 1), got {target_power}"
        raise ValueError(msg)
    ceiling = 1.0 / tau
    if power_at_gain(n_targets, tau, ceiling, alpha) < target_power:
        return None
    low, high = 1.0, ceiling
    if power_at_gain(n_targets, tau, low, alpha) >= target_power:
        return low
    for _ in range(MAX_GAIN_STEPS):
        mid = 0.5 * (low + high)
        if power_at_gain(n_targets, tau, mid, alpha) >= target_power:
            high = mid
        else:
            low = mid
        if high - low < 1e-6 * max(1.0, high):
            break
    return float(high)


def minimum_detectable_information_gain(
    n_events: int,
    sd_per_event: float,
    *,
    alpha: float = 0.05,
    target_power: float = 0.8,
    one_sided: bool = True,
) -> float:
    """Smallest mean information gain per event a paired test could detect, in nats per event.

    The companion to the alarm calculation for the ``RateForecast`` arm. ``sd_per_event`` is the
    standard deviation of the per-event log-likelihood *difference* against the reference, which
    is the quantity the paired T-test averages. The usual normal approximation applies and it is
    the same approximation the T-test itself makes, so this understates nothing the test does not
    already understate.

    It carries the same independence assumption as the interval it accompanies, and in a clustered
    catalogue the events are not independent, so the true detectable effect is larger than this.
    Rupture's own challenger intervals make that assumption and say so; this figure inherits it.
    """
    if n_events <= 0:
        msg = f"n_events must be positive, got {n_events}"
        raise ValueError(msg)
    if sd_per_event < 0.0 or not math.isfinite(sd_per_event):
        msg = f"sd_per_event must be finite and non-negative, got {sd_per_event}"
        raise ValueError(msg)
    z_alpha = norm.isf(alpha) if one_sided else norm.isf(alpha / 2.0)
    z_power = norm.isf(1.0 - target_power)
    return float((z_alpha + z_power) * sd_per_event / math.sqrt(n_events))


def events_needed_for_gain(
    tau: float, gain: float, *, alpha: float = 0.05, target_power: float = 0.8, cap: int = 2_000_000
) -> int | None:
    """Target events needed before an alarm of fraction ``tau`` could show gain ``gain``.

    The number to quote when an experiment is not yet worth running: Khawaja et al.'s roughly
    32,000 events is this quantity for a different test. ``None`` means more than ``cap`` events,
    which for most regions is a statement about centuries.

    Binomial power does not increase strictly monotonically with ``n`` — adding one target can
    push the critical hit count up a whole integer and lose power — so the returned figure is the
    smallest ``n`` from which power holds continuously upward over the scanned neighbourhood, not
    a guaranteed global minimum. The difference is one or two events and never changes a decision.
    """
    if gain <= 1.0:
        msg = "a gain of 1 is the reference itself and is never detectable"
        raise ValueError(msg)
    high = 1
    while high <= cap and power_at_gain(high, tau, gain, alpha) < target_power:
        high *= 2
    if high > cap:
        return None
    low = max(1, high // 2)
    while low < high:
        mid = (low + high) // 2
        if power_at_gain(mid, tau, gain, alpha) >= target_power:
            high = mid
        else:
            low = mid + 1
    while low > 1 and power_at_gain(low - 1, tau, gain, alpha) >= target_power:
        low -= 1
    return int(low)


def _check(n_targets: int, tau: float, alpha: float) -> None:
    if n_targets < 0:
        msg = f"n_targets must be non-negative, got {n_targets}"
        raise ValueError(msg)
    if not 0.0 < tau <= 1.0:
        msg = f"alarm fraction tau must lie in (0, 1], got {tau}"
        raise ValueError(msg)
    if not 0.0 < alpha < 1.0:
        msg = f"alpha must lie in (0, 1), got {alpha}"
        raise ValueError(msg)
