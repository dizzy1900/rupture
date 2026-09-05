"""The promotion rule of ``docs/EVALUATION_PROTOCOL.md`` § 10, encoded exactly once.

Before this module the rule lived in two places that read it differently — a per-window tally in
``challengers/ntpp/schedule.py`` and a schedule-pooled test in ``ensemble/protocol_runner.py`` —
so the two challengers were judged under two different rules. ADR-0040 reconciles them to the
single reading encoded here, and ``rupture validate challengers`` recomputes every published
verdict from this module over the committed evidence, so no promotion claim can be editorial.

The rule, for one model:

* **Condition 1 — consistency.** Its N-, M-, S- and L-test pass rates are each at or above the
  ETAS baseline's, over at least :data:`MIN_CONSECUTIVE_WINDOWS` *consecutive* protocol windows.
  Consecutive means what it says: the longest run of evaluated issue times spaced by exactly the
  schedule step, not merely a count of evaluated windows.
* **Condition 2 — skill.** It beats ETAS in the paired T-test at alpha = 0.05 with positive
  information gain per event *over those windows*: one test over the schedule's pooled target
  events (Rhoades et al. 2011), not a majority of per-window tests. The per-window tally and the
  W-test are reported alongside as evidence and disagreement is flagged, but neither decides.
* **Condition 3 — regions.** Conditions 1 and 2 hold in at least :data:`MIN_REGIONS` of the three
  protocol regions. A region that was never evaluated is not a pass; it is reported by name.

Two rules of construction hold everywhere below:

1. **Undecidable is not passed.** Where the evidence cannot decide a condition — no comparable
   baseline rate, no pooled test, a pooled test that is undefined — the condition is *not met*
   and the reason is carried through to the verdict. § 10's "failing any condition means not
   promoted" leaves no third state.
2. **Nothing here knows which model it is judging.** The functions take pass rates and test
   results, never a model object, so the same code judges the challenger, the baseline against
   itself, or a fixture.

a promotion here means a rate model is a candidate for
operational use, nothing more.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import numpy as np
from scipy import stats

if TYPE_CHECKING:  # pragma: no cover - typing only, so the gate need not import pycsep
    from rupture.domain import Catalog, ForecastGrid

MIN_CONSECUTIVE_WINDOWS = 12
MIN_REGIONS = 2
ALPHA = 0.05
PROTOCOL_TESTS: tuple[str, ...] = ("N", "M", "S", "L")
PROTOCOL_REGIONS: tuple[str, ...] = ("california", "nepal-himalaya", "turkiye-eaf")

CONDITION_2_STATISTIC = (
    "paired T-test on the per-event log-rate differences pooled over the schedule "
    "(Rhoades et al. 2011 information gain per event); ADR-0040"
)


def _instant(value: object) -> datetime | None:
    """Parse an ISO timestamp; ``None`` when it is not one. Never compares timestamps as strings."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def longest_consecutive_run(
    issue_times: Sequence[object],
    step: timedelta,
    *,
    tolerance: timedelta = timedelta(hours=1),
) -> int:
    """Longest run of issue times spaced by ``step``, which is what "consecutive windows" means.

    A schedule that skipped a window — a gap, a refit that failed, a hand-picked subset — has a
    shorter run than it has windows, and § 10 asks for the run. Times are parsed to instants and
    sorted; unparseable entries break the run rather than being silently dropped, because a
    schedule whose issue times cannot be read is not evidence that they were consecutive.
    """
    if step <= timedelta(0):
        msg = "step must be positive"
        raise ValueError(msg)
    parsed = [_instant(t) for t in issue_times]
    if not parsed:
        return 0
    if any(t is None for t in parsed):
        return 0
    ordered = sorted(t for t in parsed if t is not None)
    best = run = 1
    for earlier, later in pairwise(ordered):
        gap = later - earlier
        run = run + 1 if abs(gap - step) <= tolerance else 1
        best = max(best, run)
    return best


def pass_rate_table(report: Mapping[str, Any] | None, key: str = "pass_rates") -> dict[str, float]:
    """The N/M/S/L rates of a schedule report, with anything missing simply absent."""
    rates: dict[str, float] = {}
    table = (report or {}).get(key) or {}
    if not isinstance(table, Mapping):
        return rates
    for test in PROTOCOL_TESTS:
        entry = table.get(test)
        if isinstance(entry, Mapping) and isinstance(entry.get("rate"), int | float):
            rates[test] = float(entry["rate"])
    return rates


def condition_1(
    *,
    challenger: Mapping[str, float],
    baseline: Mapping[str, float],
    consecutive_windows: int,
) -> dict[str, Any]:
    """Pass rates at or above ETAS on every protocol test, over enough consecutive windows."""
    per_test: dict[str, Any] = {}
    reasons: list[str] = []
    met = True
    for test in PROTOCOL_TESTS:
        mine = challenger.get(test)
        theirs = baseline.get(test)
        if mine is None or theirs is None:
            per_test[test] = {"challenger": mine, "etas": theirs, "at_least_etas": None}
            reasons.append(f"{test}-test: no comparable pass rate on both sides")
            met = False
            continue
        ok = mine >= theirs
        per_test[test] = {"challenger": mine, "etas": theirs, "at_least_etas": ok}
        if not ok:
            reasons.append(f"{test}-test pass rate {mine:.3f} is below ETAS's {theirs:.3f}")
            met = False
    if consecutive_windows < MIN_CONSECUTIVE_WINDOWS:
        reasons.append(
            f"{consecutive_windows} consecutive window(s); the rule needs "
            f">= {MIN_CONSECUTIVE_WINDOWS}"
        )
        met = False
    return {
        "met": met,
        "consecutive_windows": consecutive_windows,
        "min_consecutive_windows": MIN_CONSECUTIVE_WINDOWS,
        "per_test": per_test,
        "reasons": reasons,
    }


def condition_2(
    pooled: Mapping[str, Any] | None,
    *,
    per_window: Mapping[str, Any] | None = None,
    alpha: float = ALPHA,
) -> dict[str, Any]:
    """The pooled paired T-test decides; the per-window tally and the W-test are evidence.

    ``pooled`` is a :func:`rupture.models.ensemble.protocol_runner.pooled_paired_test` result.
    ``per_window`` is the schedule's own window-by-window tally (``t_test_wins`` and friends),
    recorded so a reader can see when the two readings disagree — as they do for the Türkiye
    ensemble, where the pooled test wins and 2 of 10 decidable windows do.
    """
    reasons: list[str] = []
    evidence: dict[str, Any] = {"alpha": alpha, "statistic": CONDITION_2_STATISTIC}
    if per_window:
        wins = per_window.get("t_test_wins")
        compared = per_window.get("windows_compared")
        evidence["per_window_tally"] = {
            "t_test_wins": wins,
            "windows_compared": compared,
            "w_test_wins": per_window.get("w_test_wins"),
            "w_test_windows": per_window.get("w_test_windows")
            or per_window.get("windows_w_compared"),
            "note": (
                "reported as evidence only; the rule is the pooled test over the schedule "
                "(ADR-0040), because a 30-day window with one or two target events has almost "
                "no power"
            ),
        }
    if pooled is None:
        return {
            **evidence,
            "met": False,
            "decidable": False,
            "reasons": ["no pooled paired test in the evidence, so condition 2 cannot be decided"],
        }
    if not pooled.get("decided"):
        return {
            **evidence,
            "met": False,
            "decidable": False,
            "reasons": [str(pooled.get("reason") or "the pooled paired test is undefined")],
        }
    gain = pooled.get("information_gain_per_event")
    lower = pooled.get("ig_lower")
    gain_ok = isinstance(gain, int | float) and gain > 0.0
    interval_ok = isinstance(lower, int | float) and lower > 0.0
    if not gain_ok:
        reasons.append(f"pooled information gain per event is {gain}, not positive")
    if not interval_ok:
        reasons.append(f"the lower bound of the {1 - alpha:.0%} interval is {lower}, not above 0")
    w_p = pooled.get("w_test_p_value")
    w_beats = pooled.get("w_test_beats_benchmark")
    met = bool(gain_ok and interval_ok)
    disagrees = bool(met and w_beats is False)
    return {
        **evidence,
        "met": met,
        "decidable": True,
        "information_gain_per_event": gain,
        "ig_lower": lower,
        "ig_upper": pooled.get("ig_upper"),
        "p_value": pooled.get("p_value"),
        "target_events": pooled.get("target_events"),
        "windows_pooled": pooled.get("windows_pooled"),
        "w_test_p_value": w_p,
        "w_test_beats_benchmark": w_beats,
        "w_test_disagrees": disagrees,
        "reasons": reasons,
        # § 10 asks for the W-test alongside and for disagreement to be flagged. It is a warning,
        # not a veto (ADR-0040 decision 2), so it must survive into a verdict that *passed* —
        # which is precisely the verdict where anyone needs to read it.
        "warnings": (
            [
                "the W-test disagrees with the T-test: the mean per-event log-rate difference is "
                "positive where the median is not, so a minority of events were placed much "
                "better and the majority worse"
            ]
            if disagrees
            else []
        ),
    }


# ------------------------------------------------ the statistic condition 2 is made of
def pooling_terms(
    evaluator: Any,
    grid: ForecastGrid,
    benchmark: ForecastGrid,
    target: Catalog,
) -> dict[str, Any]:
    """The per-window quantities the schedule-wide paired T-test needs (Rhoades et al. 2011).

    ``log_rates`` are the forecast rates in the cell-magnitude bin of each observed target event,
    logged; ``n_forecast`` is the window's total expected count. Pooling these across windows is
    what turns pycsep's per-window paired test into the "over those windows" test the promotion
    rule asks for.
    """
    g1 = evaluator.to_gridded_forecast(grid)
    g2 = evaluator.to_gridded_forecast(benchmark)
    csep_catalog, _ = evaluator.to_csep_catalog(target, g1, grid)
    rates1, n1 = g1.target_event_rates(csep_catalog, scale=False)
    rates2, n2 = g2.target_event_rates(csep_catalog, scale=False)
    with np.errstate(divide="ignore"):
        log1 = np.log(np.asarray(rates1, dtype=np.float64))
        log2 = np.log(np.asarray(rates2, dtype=np.float64))
    return {
        "log_rates": [float(v) for v in log1],
        "benchmark_log_rates": [float(v) for v in log2],
        "n_forecast": float(n1),
        "benchmark_n_forecast": float(n2),
    }


def pooled_paired_test(
    windows: Sequence[dict[str, Any]], *, alpha: float = 0.05, exclude: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """The paired T-test and W-test over the whole schedule, not one window at a time.

    The promotion rule (protocol section 10, condition 2) asks whether the challenger beats ETAS
    in the paired T-test *over* at least twelve consecutive windows. pycsep's ``paired_t_test``
    scores one window, and on a 30-day window with one or two target events it has almost no
    power. This pools every window's target events into a single test, using the same statistic
    (Rhoades et al. 2011, equations 17 and 18) that pycsep implements per window: the information
    gain is ``(sum(log lambda_A - log lambda_B) - (N_A - N_B)) / N`` over all events and all
    windows, with N_A and N_B the summed forecast counts, and the Student-t interval is taken on
    the per-event differences.
    """
    log_a: list[float] = []
    log_b: list[float] = []
    n_a = 0.0
    n_b = 0.0
    used = 0
    for w in windows:
        pooling = w.get("pooling")
        if not pooling or w["issue_time"] in exclude:
            continue
        used += 1
        n_a += float(pooling["n_forecast"])
        n_b += float(pooling["benchmark_n_forecast"])
        log_a.extend(float(v) for v in pooling["log_rates"])
        log_b.extend(float(v) for v in pooling["benchmark_log_rates"])
    n_obs = len(log_a)
    base = {
        "windows_pooled": used,
        "windows_excluded": sorted(exclude),
        "target_events": n_obs,
        "total_forecast": n_a,
        "benchmark_total_forecast": n_b,
        "alpha": alpha,
        "statistic": "Rhoades et al. 2011 information gain per event, pooled over the schedule",
    }
    if n_obs < 2:
        return {**base, "decided": False, "reason": "fewer than two target events in the schedule"}
    diff = np.asarray(log_a, dtype=np.float64) - np.asarray(log_b, dtype=np.float64)
    if not np.all(np.isfinite(diff)):
        n_infinite = int(np.sum(~np.isfinite(diff)))
        return {
            **base,
            "decided": False,
            "reason": (
                f"{n_infinite} target event(s) fell in a bin one forecast gave zero rate, so the "
                f"log-rate difference is not finite; the pooled test is undefined"
            ),
        }
    information_gain = float((diff.sum() - (n_a - n_b)) / n_obs)
    first = float((diff**2).sum() / (n_obs - 1))
    second = float(diff.sum() ** 2 / (n_obs**2 - n_obs))
    variance = first - second
    if variance <= 0.0:
        return {**base, "decided": False, "reason": "zero variance in the per-event differences"}
    std = float(np.sqrt(variance))
    t_statistic = information_gain / (std / float(np.sqrt(n_obs)))
    t_critical = float(stats.t.ppf(1.0 - alpha / 2.0, n_obs - 1))
    half = t_critical * std / float(np.sqrt(n_obs))
    p_value = float(2.0 * stats.t.sf(abs(t_statistic), df=n_obs - 1))
    median_value = (n_a - n_b) / n_obs
    try:
        w_p: float | None = float(
            stats.wilcoxon(
                diff - median_value, alternative="two-sided", zero_method="wilcox"
            ).pvalue
        )
    except ValueError:  # every difference equals the median: the signed-rank test is undefined
        w_p = None
    return {
        **base,
        "decided": True,
        "information_gain_per_event": information_gain,
        "ig_lower": information_gain - half,
        "ig_upper": information_gain + half,
        "t_statistic": t_statistic,
        "t_critical": t_critical,
        "p_value": p_value,
        "t_test_beats_benchmark": bool(information_gain - half > 0.0),
        "w_test_p_value": w_p,
        "w_test_beats_benchmark": (
            bool(w_p < alpha and information_gain > 0.0) if w_p is not None else None
        ),
    }


def region_verdict(
    *,
    region_id: str,
    model_id: str,
    challenger_rates: Mapping[str, float],
    baseline_rates: Mapping[str, float],
    consecutive_windows: int,
    pooled: Mapping[str, Any] | None,
    per_window: Mapping[str, Any] | None = None,
    baseline_label: str = "etas-mizrahi",
    alpha: float = ALPHA,
) -> dict[str, Any]:
    """Conditions 1 and 2 for one model in one region. Condition 3 needs more than one region."""
    c1 = condition_1(
        challenger=challenger_rates,
        baseline=baseline_rates,
        consecutive_windows=consecutive_windows,
    )
    c2 = condition_2(pooled, per_window=per_window, alpha=alpha)
    promotable = bool(c1["met"] and c2["met"])
    return {
        "region_id": region_id,
        "model_id": model_id,
        "baseline": baseline_label,
        "condition_1_pass_rates": c1,
        "condition_2_paired_t_test": c2,
        "promotable_in_this_region": promotable,
        "reasons_not_promotable": [] if promotable else [*c1["reasons"], *c2["reasons"]],
        "warnings": list(c2.get("warnings") or []),
        "note": (
            "Promotion also requires both conditions in at least "
            f"{MIN_REGIONS} of the {len(PROTOCOL_REGIONS)} protocol regions; that is decided "
            "across regions, not here. A pass rate is not a skill claim."
        ),
    }


def overall_verdict(
    region_verdicts: Sequence[Mapping[str, Any]],
    *,
    model_id: str,
    expected_regions: Sequence[str] = PROTOCOL_REGIONS,
    min_regions: int = MIN_REGIONS,
    regions_that_cannot_pass: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Condition 3: the two-of-three clause, with the regions nobody ran named explicitly.

    A region with no evidence is reported in ``regions_not_evaluated``. It cannot count towards
    promotion, and the arithmetic that says so is written out: when the passing regions plus the
    ones that could still pass fall short of ``min_regions``, the verdict could not change however
    those regions came out — a stronger statement than "not promoted", and worth printing.

    ``regions_that_cannot_pass`` maps a region id to why no model can pass there at all — the
    published baseline schedule being too short to satisfy condition 1, for instance. Such a
    region is unevaluated *and* unreachable, and saying so is the difference between "we did not
    run it" and "running it could not have changed this".
    """
    blocked = dict(regions_that_cannot_pass or {})
    passing = sorted(
        str(v["region_id"]) for v in region_verdicts if v.get("promotable_in_this_region")
    )
    evaluated = {str(v["region_id"]) for v in region_verdicts}
    missing = sorted(r for r in expected_regions if r not in evaluated)
    could_still_pass = [r for r in missing if r not in blocked]
    reachable = len(passing) + len(could_still_pass)
    return {
        "model_id": model_id,
        "promoted": len(passing) >= min_regions,
        "regions_required": min_regions,
        "regions_passing": passing,
        "regions_evaluated": sorted(evaluated),
        "regions_not_evaluated": missing,
        "regions_that_cannot_pass": {r: blocked[r] for r in missing if r in blocked},
        "regions_that_could_still_pass": could_still_pass,
        "verdict_robust_to_unevaluated_regions": reachable < min_regions,
        "per_region": [dict(v) for v in region_verdicts],
        "rule": (
            "docs/EVALUATION_PROTOCOL.md section 10 as encoded in rupture.models.promotion "
            "(ADR-0040)"
        ),
    }
