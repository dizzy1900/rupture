# ADR-0065 — Intervals resample blocks of windows, because earthquakes are not independent

- **Status:** accepted
- **Date:** 2026-09-10 (UTC)
- **Related:** [ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md) (power is mandatory),
  [ADR-0040](0040-promotion-rule-single-encoding.md) (the promotion rule),
  [ADR-0010](0010-pycsep-evaluation.md), [ADR-0063](0063-alarm-scorer-implementation.md)

## Context

Every confidence interval in this repository's challenger evidence is a Student-t interval on the
per-event log-likelihood differences, following Rhoades et al. (2011). That statistic is the right
one. The interval around it assumes those per-event differences are independent, and RELEASE_STATUS
has said since Prompt 2 that this is the weak point of the only result the project has:

> The one metric beaten (Türkiye ensemble information gain) rests on an interval that assumes
> independent events

Earthquakes are the canonical violation, and the committed evidence shows exactly how badly:

| | |
|---|---|
| Türkiye target events, pooled | 217 |
| …in the single 2023-01-26 window (Kahramanmaraş) | **160 (74 %)** |
| effective independent windows, Kish | **1.8** of 55 |
| Nepal target events | 66, most in one window, effective 6.8 |

A Student-t interval on 217 points that are really something closer to two is not a conservative
approximation. It is the wrong width, and nothing in the repository could say by how much.

## Decision

1. **The block is the scored window.** It is the unit a schedule issues, it is what the per-event
   log rates are already grouped by in the committed JSON, and dependence within an aftershock
   sequence lives inside it. A **moving block** of `block_length` consecutive windows extends that
   to sequences spilling over a window boundary; blocks are drawn circularly so windows near the
   ends of a short schedule are not under-sampled.

2. **No single block length carries a conclusion.** `block_length_sensitivity` reports the
   interval at 1, 2, 3, 5 and 8 windows and the honest reading is what holds across all of them.
   Choosing a block length is a claim about how far dependence reaches, and 55 windows cannot
   settle it; reporting the range is cheaper than defending a pick.

3. **The bootstrap recomputes the point estimate from the same committed per-event log rates**
   rather than reading the published one, so the interval and the statistic cannot drift apart.
   The recomputation reproduces the published figure to floating-point noise, which is the check
   that the inputs are complete.

4. **A verdict that does not survive is reported as a result, not as a gate failure.**
   `validate-challengers` prints the intervals and names any published verdict the block interval
   overturns. Nothing about the promotion rule changes: the rule asks whether a challenger *beats*
   ETAS, and no interval here moves a model across that line.

5. **Every minimum detectable effect gets a block-based companion.** A wider interval means a
   larger smallest-findable effect, so `ClusteringCheck.block_mde` reports the figure implied by
   the widest block interval alongside the one implied by the Student-t interval.

## Consequences

**The only positive result in this repository survives.** The Türkiye log-linear ensemble,
+0.3354 nats/event, published as [+0.267, +0.404]:

| block length | 95 % interval | width vs normal | excludes zero |
|---|---|---|---|
| 1 | [+0.266, +0.825] | 4.1x | yes |
| 2 | [+0.278, +0.725] | 3.3x | yes |
| 3 | [+0.286, +0.636] | 2.6x | yes |
| 5 | [+0.287, +0.659] | 2.7x | yes |
| 8 | [+0.289, +0.626] | 2.5x | yes |

It is not an artefact of the independence assumption. It is also strongly right-skewed
(skew ≈ +2.0 at block length 1), which a symmetric interval cannot express and which the published
bracket therefore misrepresented in shape even where it was right about the sign.

**One published verdict is withdrawn.** The Nepal gridded ConvLSTM was published at −0.6215
[−1.105, −0.138], p = 0.0125, and read as significantly *worse* than ETAS. Every block interval
crosses zero. The model is not shown to be worse than ETAS in Nepal — only not shown to be better.
`docs/CHALLENGER_GRIDDED.md`, `reports/CHALLENGER_EVALUATION.md` and
`reports/MODEL_CARD_gridded.md` are corrected.

**Both nulls were blinder than they looked.** Under the widest block interval Türkiye's gridded
model could only have found 1.61 nats/event rather than 0.456, and Nepal's ensemble 0.54 rather
than 0.339. A null result's upper bound is only as good as the interval it came from.

**A defect in the power retrofit was found and fixed on the way.** `scoring/evidence.py` read
`target_events` from `pooled_information_gain` (198 on Türkiye, a target-count-weighted average
over windows whose *per-window* test was decided) while taking the interval from
`pooled_paired_test` (217, pooling every window's per-event log rates). The minimum detectable
effect was unaffected — it is `(z_alpha + z_power) x standard error` and the event count cancels —
but that was luck. `sd_per_event` was wrong by a factor of sqrt(198/217) and is now right.

**What this does not fix.** The bootstrap re-intervals what was already scored; it does not rescore
anything, and it cannot repair a schedule in which three quarters of the evidence is one sequence.
The real remedy for Türkiye is more independent sequences, which means more regions or a longer
schedule, and California's is 6 windows of 55. The N/M/S/L/CL consistency tests still report no
power and are untouched by this ADR.

## Alternatives considered

- **Keep the Student-t interval and widen it by a design effect.** Rejected: a design effect needs
  an intraclass correlation nobody has estimated for this statistic, and it would still produce a
  symmetric interval for a distribution with skew +2.
- **Bootstrap events rather than windows.** That is the interval we already have, and it is the
  thing being corrected.
- **Choose one block length by an automatic rule** (Politis & White). Rejected for now: the rule
  is designed for long stationary series, 55 windows is not that, and the conclusions here are
  insensitive to the choice — which is worth demonstrating rather than assuming.
- **Withhold the Türkiye result until more regions are scored.** Rejected: it survives its own
  correction, and suppressing a result that passes a harder test than it was published under
  would be its own kind of dishonesty. The narrow evidence base is stated instead.
