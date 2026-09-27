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
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from scipy.stats import norm

from rupture.scoring.blocks import (
    DEFAULT_BLOCK_LENGTHS,
    DEFAULT_RESAMPLES,
    BlockBootstrapResult,
    block_length_sensitivity,
    conclusion_holds_across_lengths,
)
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
        # `target_events` from the *paired test*, not from `pooled_information_gain`. The two
        # differ and are both published: `pooled_information_gain` is a target-count-weighted
        # average of the per-window T-test statistics and skips windows whose per-window test was
        # undecided (198 events and IG 0.2892 on Türkiye), while `pooled_paired_test` pools every
        # window's per-event log rates (217 events and IG 0.3354). The interval below belongs to
        # the second, so its event count must come from there too. Reading N from the first was a
        # real defect; it left `sd_per_event` wrong by sqrt(198/217). The minimum detectable
        # effect was not affected — it is (z_alpha + z_power) * standard error and the N cancels —
        # but that was luck, not design.
        pooled = record.get("pooled_information_gain") or {}
        n_events = int(paired.get("target_events", 0) or pooled.get("target_events", 0))
        if n_events <= 0:
            continue
        lower, upper = paired.get("ig_lower"), paired.get("ig_upper")
        if lower is None or upper is None:
            continue
        result = power_for_result(
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
        out.append(result)
    return out


def read_all(
    reports_dir: Path, *, alpha: float = 0.05, target_power: float = 0.8
) -> list[PoweredResult]:
    """Every committed challenger schedule under ``reports_dir``."""
    results: list[PoweredResult] = []
    for path in sorted(reports_dir.glob("*/schedule-*-challengers.json")):
        results.extend(read_schedule(path, alpha=alpha, target_power=target_power))
    return results


@dataclass(frozen=True, slots=True)
class ClusteringCheck:
    """One published comparison, its normal interval, and what a block bootstrap does to it."""

    powered: PoweredResult
    sensitivity: list[BlockBootstrapResult]

    @property
    def robust(self) -> bool | None:
        """True when every block length agrees on whether the interval excludes zero."""
        return conclusion_holds_across_lengths(self.sensitivity)

    @property
    def verdict_survives(self) -> bool | None:
        """True when the published significance verdict holds at every block length.

        ``False`` is the interesting answer and it is not a bug: a result published as significant
        whose every clustering-aware interval crosses zero was significant only because the
        interval assumed away the clustering.
        """
        if self.powered.significant is None or not self.sensitivity:
            return None
        published_significant = self.powered.significant
        return all(r.crosses_zero != published_significant for r in self.sensitivity)

    @property
    def block_mde(self) -> float | None:
        """Minimum detectable effect implied by the widest block interval.

        The honest companion to the figure derived from the normal interval: if the interval
        should have been this wide, the smallest findable effect is correspondingly larger.
        """
        if not self.sensitivity:
            return None
        widest = max(self.sensitivity, key=lambda r: r.width)
        z_alpha = float(norm.isf(self.powered.alpha))
        z_power = float(norm.isf(1.0 - self.powered.target_power))
        z_level = float(norm.isf((1.0 - widest.level) / 2.0))
        standard_error = widest.width / (2.0 * z_level)
        return float((z_alpha + z_power) * standard_error)

    def render(self) -> str:
        p = self.powered
        lines = [p.render()]
        for result in self.sensitivity:
            lines.append(f"    {result.render()}")
        if self.sensitivity:
            first = self.sensitivity[0]
            lines.append(
                f"    {first.n_events} event(s) over {first.n_windows} window(s), worth about "
                f"{first.effective_blocks:.1f} independent window(s) (Kish)"
            )
        if self.verdict_survives is False:
            lines.append(
                "    THE PUBLISHED VERDICT DOES NOT SURVIVE: it was "
                f"{'significant' if p.significant else 'null'} on an interval assuming "
                "independent events, and every clustering-aware interval here disagrees"
            )
        elif self.verdict_survives is True:
            lines.append("    the published verdict survives at every block length")
        if self.robust is False:
            lines.append(
                "    the block lengths disagree with each other, so no conclusion is safe here"
            )
        mde = self.block_mde
        if mde is not None:
            lines.append(
                f"    minimum detectable effect under the widest block interval: "
                f"{mde:.4f} nats/event (against {p.minimum_detectable_gain:.4f} under the "
                "independence assumption)"
            )
        return "\n".join(lines)


def read_schedule_with_blocks(
    path: Path,
    *,
    alpha: float = 0.05,
    target_power: float = 0.8,
    lengths: Sequence[int] = DEFAULT_BLOCK_LENGTHS,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int | None = 0,
) -> list[ClusteringCheck]:
    """Every decided comparison in one schedule, with its normal and block intervals."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_model = {
        model_id: record.get("windows") or []
        for model_id, record in (payload.get("models") or {}).items()
    }
    checks: list[ClusteringCheck] = []
    for powered in read_schedule(path, alpha=alpha, target_power=target_power):
        windows = by_model.get(powered.model_id) or []
        if not windows:
            checks.append(ClusteringCheck(powered=powered, sensitivity=[]))
            continue
        checks.append(
            ClusteringCheck(
                powered=powered,
                sensitivity=block_length_sensitivity(
                    windows,
                    lengths=lengths,
                    n_resamples=n_resamples,
                    seed=seed,
                    normal_lower=powered.ig_lower,
                    normal_upper=powered.ig_upper,
                ),
            )
        )
    return checks


def read_all_with_blocks(
    reports_dir: Path,
    *,
    alpha: float = 0.05,
    target_power: float = 0.8,
    lengths: Sequence[int] = DEFAULT_BLOCK_LENGTHS,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int | None = 0,
) -> list[ClusteringCheck]:
    """Every committed challenger schedule, with clustering-aware intervals."""
    checks: list[ClusteringCheck] = []
    for path in sorted(reports_dir.glob("*/schedule-*-challengers.json")):
        checks.extend(
            read_schedule_with_blocks(
                path,
                alpha=alpha,
                target_power=target_power,
                lengths=lengths,
                n_resamples=n_resamples,
                seed=seed,
            )
        )
    return checks
