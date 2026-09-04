# ADR-0040: Condition 2 of the promotion rule is the schedule-pooled paired T-test, and the rule is encoded once

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)
- **Amends:** [ADR-0022](0022-leakage-engineering-for-learned-models.md) (leakage engineering) by
  fixing the reading of `docs/EVALUATION_PROTOCOL.md` § 10 condition 2. It does not change any
  threshold, region, horizon or significance level.

## Context

`docs/EVALUATION_PROTOCOL.md` § 10 was written before any model in this repository was fitted. Its
condition 2 says a challenger is promotable only if

> it beats ETAS in the paired T-test at α = 0.05 with **positive information gain per event** over
> those windows (the W-test is reported alongside and disagreement is flagged)

Two implementations of that sentence were written independently, by two agents, and they read it
differently:

| | `challengers/ntpp/schedule.py::promotion_verdict` | `ensemble/protocol_runner.py::promotion_decision` |
|---|---|---|
| Statistic | pycsep's per-window `paired_t_test`, tallied | one Rhoades et al. (2011) information-gain test over the schedule's pooled target events |
| Condition 2 met when | mean per-event gain > 0 **and** T-test won in a strict majority of decidable windows | the lower bound of the pooled 95 % interval is above 0 |
| On the committed Türkiye ensemble | not met (2 wins of 10 decidable windows) | met (+0.335 per event, interval [+0.267, +0.404]) |

Both readings are defensible in isolation and both were reported honestly. That is precisely the
problem: with two readings live, the promotion verdict is not the pre-registered mechanical one
that § 10 exists to be, and the two challengers were being judged under different rules. The
project's single region-level pass — the Türkiye ensemble — exists only under the pooled reading,
which makes choosing between them look like tuning unless the choice is argued from the protocol
text and from statistics rather than from the outcome.

A third disagreement was smaller but real: "≥ 12 **consecutive** 30-day windows" was implemented on
both sides as a count of scored windows (`n_windows >= 12`), which a schedule with gaps would
satisfy without ever having twelve consecutive ones.

## Decision

1. **Condition 2 is the schedule-pooled paired T-test.** One test, over the per-event log-rate
   differences of every target event in the run, using the same statistic pycsep applies per
   window (Rhoades et al. 2011, equations 17–18). It is met when the pooled information gain per
   event is positive **and** the lower bound of its two-sided (1 − α) Student-t interval is above
   zero.

   The reasons, in order of weight:

   - **The protocol says "over those windows".** The windows are the domain of the test, not a
     collection of separate tests. A majority-of-windows rule is a sign test over window outcomes,
     a different statistic that § 10 does not name.
   - **The per-window test has almost no power here.** A 30-day window in Nepal or on the East
     Anatolian Fault holds one or two target events above Mc; pycsep can decide only 9 or 10 of 55
     windows at all, and a rule that discards 45 windows of evidence is not the more conservative
     rule, it is the noisier one.
   - **The per-window tally is retained and reported**, because when the two readings disagree the
     disagreement is itself a finding about the shape of the evidence (a few windows carrying the
     gain). It is evidence, never the decision.

2. **The W-test is reported alongside and disagreement is flagged**, unchanged from § 10. It does
   not veto: a T-test win with a W-test loss is a promotable result carrying a printed warning that
   the gain sits in a minority of events.

3. **"Consecutive" is enforced as consecutiveness.** The longest run of evaluated issue times
   spaced by exactly the schedule step must be at least 12; a count of scored windows is not
   sufficient.

4. **The rule is encoded once**, in `src/rupture/models/promotion.py`. Both schedule runners call
   it, and `make validate-challengers` recomputes every published verdict from that module over
   the committed evidence in `reports/challenger/` and `reports/protocol/`, failing if a model
   card, `RELEASE_STATUS.md` or `reports/CHALLENGER_EVALUATION.md` declares a promotion the rule
   does not admit. There is no path by which a promotion claim can be editorial.

5. **Undecidable is not passed.** Where the committed evidence cannot decide a condition — no
   comparable baseline pass rate, no pooled test, a pooled test undefined because a target event
   fell in a zero-rate bin — the condition is *not met* and the reason is carried into the verdict.
   § 10's "failing any condition means the challenger is recorded as not promoted" leaves no third
   state.

6. **The baseline of record is the published ETAS schedule** for the region
   (`reports/protocol/<region>/eval/schedule-<region>-etas-mizrahi.json`). Where a challenger was
   compared against a *matched re-run* of ETAS instead — the NTPP schedules used 100 continuations
   and no refits, to match the challenger's own budget — the gate evaluates condition 1 under both
   and **fails if they disagree**, rather than picking the flattering one. They do not disagree on
   any committed result.

## Consequences

- **No published verdict changes.** Under this reading the Türkiye ensemble meets both conditions
  in Türkiye and only there; Nepal is a loss; California was never evaluated. One region is not two,
  so the ensemble is **not promoted**, which is what `reports/CHALLENGER_EVALUATION.md`,
  `RELEASE_STATUS.md` and the model cards already say. The NTPP and gridded challengers fail
  condition 1 in both evaluated regions under either reading. This ADR was written after checking
  that; had it changed a verdict, the changed verdict would have been published, not the rule.
- **The NTPP schedule reports cannot decide condition 2 as encoded here**, because they record
  per-window comparison summaries but not the per-event log rates a pooled test needs. The gate
  reports that condition as *not decidable from committed evidence* and says so out loud; it is
  immaterial to the verdict because condition 1 already fails in both regions.
  `run_ntpp_schedule` now records the pooling terms, so a future run is decidable.
- The `promotion-<region>-ntpp.json` files committed on 2026-09-03 were written under the
  pre-ADR reading. They are left as the historical record of what was run; the gate recomputes the
  canonical verdict from the schedule JSON beside them and does not read them.
- A future challenger that wins a majority of windows but loses the pooled test is now *not*
  promotable where it once would have been, and vice versa. Both directions were accepted before
  the numbers were looked at again.

## Alternatives considered

- **Keep the per-window majority reading.** Rejected: it is a different statistic from the one § 10
  names, it discards four fifths of the evidence, and it is the reading under which the project's
  only positive result disappears — a reason to examine it more carefully, not to adopt it
  silently.
- **Require both readings (pooled *and* a majority of windows).** Rejected as post-hoc
  strengthening. Tightening a pre-registered rule after seeing which side of it a result falls on
  is tuning, even when it tightens against the challenger; the honest place for the concern is the
  reported evidence, where the per-window tally and the pooled sensitivity analysis both appear.
- **Require robustness to the largest-contributing window.** Same objection, and the sensitivity
  analysis (`pooled_sensitivity` in the committed evidence) already reports it: removing the
  Kahramanmaraş window *raises* the Türkiye ensemble's gain.
- **Amend § 10's text in place.** Rejected: the protocol's value is that it was fixed in advance,
  and rewriting it after the fact destroys the evidence that it was. It is amended *by this ADR*,
  which the protocol's own preamble requires ("changes to any numbered rule require an ADR that
  states what was known at the time of the change"). A one-line cross-reference from § 10 to this
  ADR is owed and is the only edit that document needs.
