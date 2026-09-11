"""Retrofitting the power figure ADR-0055 makes mandatory onto results that predate it.

Decision 4 says a p-value without a power figure is not a finding. RELEASE_STATUS records that
**no consistency-test or challenger result in this repository reports its power**, and that the
one metric ever beaten here — the Türkiye log-linear ensemble, +0.335 nats/event over 55 windows
— has no figure saying whether it could have been seen by chance.

Nothing needs re-running to fix that. The committed schedule JSONs already carry the pooled
information gain, its confidence interval and the target count, and a symmetric normal interval
determines the standard error that produced it:

    se = (upper - lower) / (2 * z_{1-alpha/2})

from which the per-event standard deviation and the minimum detectable effect follow. This module
reads the committed evidence and computes both, so the retrofit is arithmetic on published
numbers rather than a new experiment.

**The assumption travels with the number.** The intervals in those files assume independent
events, which a clustered catalogue violates; RELEASE_STATUS says so about the intervals and it is
equally true of everything derived from them. The real detectable effect is larger than the
figures here. A block bootstrap would fix both at once and is not built.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scipy.stats import norm

from rupture.scoring.power import minimum_detectable_information_gain

EVIDENCE_VERSION = "1.0.0"
DEFAULT_INTERVAL_LEVEL = 0.95


@dataclass(frozen=True, slots=True)
class PoweredResult:
    """One published information-gain result with the power it actually had."""

    region_id: str
    model_id: str
    benchmark_model_id: str
    n_target_events: int
    information_gain_per_event: float
    ig_lower: float
    ig_upper: float
    p_value: float | None
    sd_per_event: float
    minimum_detectable_gain: float
    alpha: float
    target_power: float

    @property
    def significant(self) -> bool | None:
        return None if self.p_value is None else self.p_value <= self.alpha

    @property
    def effect_over_mde(self) -> float:
        """Observed gain as a multiple of the smallest one this test could have found.

        Signed: a model significantly *worse* than its reference has a negative ratio, and
        reporting it as a magnitude would read as skill.
        """
        return self.information_gain_per_event / self.minimum_detectable_gain

    @property
    def beats_reference(self) -> bool | None:
        """True only when the result is significant *and* the gain is positive."""
        if self.significant is None:
            return None
        return self.significant and self.information_gain_per_event > 0.0

    def render(self) -> str:
        verdict = (
            "undecided"
            if self.significant is None
            else ("significant" if self.significant else "null")
        )
        line = (
            f"{self.region_id}/{self.model_id} vs {self.benchmark_model_id}: "
            f"IG = {self.information_gain_per_event:+.4f} nats/event "
            f"[{self.ig_lower:+.4f}, {self.ig_upper:+.4f}] on {self.n_target_events} event(s), "
            f"{verdict}; minimum detectable effect at {self.target_power:.0%} power = "
            f"{self.minimum_detectable_gain:.4f} nats/event"
        )
        if verdict == "null":
            return (
                line + f". Upper bound: an effect of {self.minimum_detectable_gain:.4f} nats/event "
                "would have been found, and was not (ADR-0055 decision 5)"
            )
        if verdict == "significant":
            if self.information_gain_per_event > 0.0:
                return line + f" ({self.effect_over_mde:.1f}x the detectable effect)"
            return (
                line + f". The sign matters: this is significantly *worse* than "
                f"{self.benchmark_model_id}, by {abs(self.effect_over_mde):.1f}x the detectable "
                "effect, and is a rejection of the challenger rather than a result for it"
            )
        return line


def sd_from_interval(
    lower: float, upper: float, n_events: int, *, level: float = DEFAULT_INTERVAL_LEVEL
) -> float:
    """Per-event standard deviation implied by a symmetric normal interval.

    The committed schedules publish the interval and not the spread, and the interval is a
    two-sided normal one at ``level``, so the spread is recoverable exactly. If a future schedule
    publishes an asymmetric interval — a block bootstrap would — this inversion stops being valid
    and the caller has to read the spread directly.
    """
    if n_events <= 0:
        msg = f"n_events must be positive, got {n_events}"
        raise ValueError(msg)
    if upper < lower:
        msg = f"interval is inverted: [{lower}, {upper}]"
        raise ValueError(msg)
    z = float(norm.isf((1.0 - level) / 2.0))
    standard_error = (upper - lower) / (2.0 * z)
    return float(standard_error * float(n_events) ** 0.5)


def power_for_result(
    *,
    region_id: str,
    model_id: str,
    benchmark_model_id: str,
    n_target_events: int,
    information_gain_per_event: float,
    ig_lower: float,
    ig_upper: float,
    p_value: float | None,
    alpha: float = 0.05,
    target_power: float = 0.8,
    level: float = DEFAULT_INTERVAL_LEVEL,
) -> PoweredResult:
    """Attach the minimum detectable effect to one published comparison."""
    sd = sd_from_interval(ig_lower, ig_upper, n_target_events, level=level)
    mde = minimum_detectable_information_gain(
        n_target_events, sd, alpha=alpha, target_power=target_power
    )
    return PoweredResult(
        region_id=region_id,
        model_id=model_id,
        benchmark_model_id=benchmark_model_id,
        n_target_events=n_target_events,
        information_gain_per_event=information_gain_per_event,
        ig_lower=ig_lower,
        ig_upper=ig_upper,
        p_value=p_value,
        sd_per_event=sd,
        minimum_detectable_gain=mde,
        alpha=alpha,
        target_power=target_power,
    )


def read_schedule(
    path: Path, *, alpha: float = 0.05, target_power: float = 0.8
) -> list[PoweredResult]:
    """Every comparison in one committed challenger schedule, with its power.

    A model whose paired test was not decided (no targets, or an undefined comparison) is skipped
    rather than given a power figure for a test that did not run.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    region = str(payload.get("region_id", path.stem))
    out: list[PoweredResult] = []
    for model_id, record in sorted(payload.get("models", {}).items()):
        paired = record.get("pooled_paired_test") or {}
        if not paired.get("decided"):
            continue
        pooled = record.get("pooled_information_gain") or {}
        n_events = int(pooled.get("target_events", 0))
        if n_events <= 0:
            continue
        lower, upper = paired.get("ig_lower"), paired.get("ig_upper")
        if lower is None or upper is None:
            continue
        out.append(
            power_for_result(
                region_id=region,
                model_id=model_id,
                benchmark_model_id=str(
                    paired.get("benchmark_model_id")
                    or record.get("comparison_vs_etas", {}).get("benchmark_model_id")
                    or "etas-mizrahi"
                ),
                n_target_events=n_events,
                information_gain_per_event=float(
                    paired.get(
                        "information_gain_per_event", pooled.get("information_gain_per_event", 0.0)
                    )
                ),
                ig_lower=float(lower),
                ig_upper=float(upper),
                p_value=None if paired.get("p_value") is None else float(paired["p_value"]),
                alpha=alpha,
                target_power=target_power,
            )
        )
    return out


def read_all(
    reports_dir: Path, *, alpha: float = 0.05, target_power: float = 0.8
) -> list[PoweredResult]:
    """Every committed challenger schedule under ``reports_dir``."""
    results: list[PoweredResult] = []
    for path in sorted(reports_dir.glob("*/schedule-*-challengers.json")):
        results.extend(read_schedule(path, alpha=alpha, target_power=target_power))
    return results
