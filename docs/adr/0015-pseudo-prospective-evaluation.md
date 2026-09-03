# ADR-0015 — Pseudo-prospective evaluation with a hard 2022-01-01 cutoff

- **Status:** accepted
- **Date:** 2026-09-03

## Context

Non-negotiable 2: all forecast evaluation is time-forward with a hard cut, asserted in tests on
catalogue timestamps. The field's history includes skill claims produced by random
cross-validation on clustered catalogues, where aftershocks of a training event land in the test
fold. rupture cannot run truly prospective experiments in Prompt 1 (no forecasts have been
archived before their windows), so the honest alternative is a pseudo-prospective replay with
rules that make peeking impossible. The full protocol is `docs/EVALUATION_PROTOCOL.md`; this ADR
records the decision and its reasons.

## Decision

- Evaluation is **pseudo-prospective**: forecasts are issued at historical issue times using only
  events with `origin_time < issue_time`, and scored on `[issue_time, issue_time + horizon)`.
- **Hard cutoff** `2022-01-01T00:00:00Z` for the first fit and first issue; schedule every 30 days
  to `2026-08-01T00:00:00Z`; protocol horizon 30 d.
- **Refits only at logged boundaries** (default yearly, 1 January 00:00:00Z); each refit uses only
  events before its boundary and writes a `refit` entry with the new `parameter_snapshot_hash`.
  The hash must otherwise be constant across the schedule; a change is a leakage failure.
- **No random k-fold cross-validation**, anywhere, for any model, including challengers in
  Prompt 2. Development may use earlier time-forward splits; skill claims use only the protocol
  schedule.
- Targets: earthquakes only, homogenised Mw ≥ region threshold, frozen with a hash at evaluation
  time.
- The protocol document was written before any model was fitted (dated 2026-09-03) and changes to
  its numbered rules require an ADR.

## Consequences

- Results are reproducible and auditable from timestamps and hashes alone.
- The model *design* was fixed by the brief before the outcome period was examined; parameter
  values are fitted only on pre-cutoff data. This is as close to prospective as a replay can be.
- Fewer scored windows than k-fold would give, and wide uncertainty in sparse regions; the
  protocol says so rather than compensating.
- From the first archived forecast onward, rupture can accumulate genuinely prospective results;
  nothing in the design changes when that happens.

## Alternatives considered

- **Random k-fold cross-validation.** Rejected: leakage through clustering; forbidden by the
  protocol.
- **Fully retrospective fit on the whole catalogue.** Rejected: no skill claim can rest on it.
- **Refit before every window.** Not rejected as a future variant, but it multiplies compute and
  must still be logged per window; the yearly default is the documented baseline behaviour.
