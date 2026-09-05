# ADR-0054 — Observation sources are latency-aware: `available_as_of(t)`, not `before(t)`

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Amends:** [ADR-0015](0015-pseudo-prospective-evaluation.md) (the leakage rule is extended from
  origin time to availability), [ADR-0022](0022-leakage-engineering-for-learned-models.md) (rule 2,
  strictly causal feature windows)
- **Related:** [ADR-0053](0053-rupture-targets-earthquake-prediction.md),
  [ADR-0057](0057-prospective-open-benchmark.md),
  [ADR-0060](0060-completeness-as-a-field.md)

## Context

Every leakage assertion in this repository compares an **origin time** against a cut.
`src/rupture/adapters/forecasting/leakage.py` is the whole of it: `assert_all_before` raises when
any event has `origin_time >= cutoff`; `assert_within_window` bounds a target slice;
`assert_issue_after_fit` stops parameters being used before they were fitted. Those are correct and
they are not enough, and the reason is that a catalogue record has two different times and rupture
currently models only one of them.

An event at time *t* is not in the catalogue at time *t*. It is detected minutes later, associated,
located, reviewed by an analyst, relocated, and its magnitude revised — over hours to months. The
ComCat record downloaded today is not the record that existed an hour after the event. The same is
true of everything below the catalogue, and worse: a GNSS position solution from rapid orbits is
available in about a day and is less accurate than the final-orbit solution that arrives about two
weeks later; an InSAR interferogram waits for a satellite revisit (the review records Sentinel-1 at
a 6-day repeat and NISAR at 12-day, `single-study`/vendor documentation, not independently verified
here); a slow-slip inversion product carries its own processing lag (the review records Gualandi's
daily-updated Cascadia stream at roughly two days).

A model evaluated at "one-hour lead time" using final-orbit GNSS and reviewed magnitudes has leaked
through **latency**, not through timestamps, and every assertion in `leakage.py` passes while it
does so. The one field in rupture that looks like it might catch this does not: `Provenance.retrieved_at`
records when *rupture* fetched the payload — a 2026 timestamp on a 2019 event — not when the value
became readable from the source in that revision.

The failure is not hypothetical and it runs in exactly the direction that flatters a model.

- **Revision leakage.** Girona & Drymoni (2024, *Nature Communications*, doi
  10.1038/s41467-024-51596-z) report abnormal low-magnitude seismicity preceding large earthquakes;
  the Anchorage detection is reported to depend on USGS events later removed from the catalogue and
  to vanish on the current catalogue. Status `contested`: that rebuttal exists as Bradley &
  Hubbard's Substack analysis, which carries a DOI but is not peer review, and the audit found no
  formal Matters Arising. Cited here as the field's clearest worked example of a data-vintage
  effect, with its rebuttal's status attached, and not as settled.
- **Availability lag.** The review records the Nevada Geodetic Laboratory serving final daily
  solutions at roughly two weeks' latency against 24-hour rapid and 5-minute rapid streams. Reading
  the final product at issue time is reading the future.
- **Completeness-regime mismatch.** The real-time catalogue in the first hours after a mainshock is
  a different object from the archive. Hainzl et al. (2024) quantify short-term aftershock
  incompleteness as a roughly 162-second blind time (`single-study`); Li & Luo (2024) show that
  maximum-likelihood, b-positive and KMS b-value estimators all fail under realistic real-time
  incompleteness and magnitude error (`single-study`), which is why the Gulia–Wiemer traffic-light
  dispute cannot be settled on archival catalogues at all.

The field knows and proceeds anyway. Rhoades et al. (2018) state that the New Zealand CSEP testing
centre did not consistently capture the real-time catalogue, so most of its results are reprocessed —
the flagship prospective experiment, evaluated on revised data. Mizrahi et al. (2024) note that
catalogue-based tests have not been used in a truly prospective experiment.

## Decision

1. **The observation port contract is `available_as_of(t)`, not `before(t)`.** An observation
   source returns the values that were readable from that source at instant *t*, in the revision
   they had at *t* — not the values whose phenomenon occurred before *t*.

2. **Every observation carries two timestamps.** `valid_time`, when the phenomenon happened, and
   `available_time`, when *this value in this revision* first became readable from this source.
   Both are UTC and timezone-aware, as everything in this tree is. `Provenance.retrieved_at` is
   neither of them and keeps its existing meaning: when rupture fetched the payload.

3. **A vintaged store.** Daily snapshots with revision diffs for the catalogue sources rupture
   already ingests, exposed as `catalog.as_of(t)`. A vintage is a record of what a provider served
   on a day, kept alongside the current view rather than in place of it.

4. **Per-source latency is declared, and it is data, not documentation.** Each source records its
   product tiers and their nominal lags, and a replay serves the tier a model would actually have
   had at the issue time. The figures in the Context above come from the review and are
   **untested in this repository**; the declaration records the number and its source, and it is
   corrected when measured against real snapshots rather than trusted.

5. **A CI gate, `asof`.** Any evaluation that reads a value whose `available_time` is not strictly before the
   issue time fails. The failure is an exception, never a filter, for the same reason ADR-0022
   rule 1 refuses rather than drops: a silent filter hides the bug that supplied the value.

6. **A replay report per model.** Every model in the tree publishes skill on final data minus skill
   on as-of data, with bootstrap intervals, as a first-class result. It is the measurement this
   decision exists to make, and until it has been made this ADR's premise is a hypothesis.

7. **Vintages are never synthesised.** Where no vintage exists for a source and a period, reads
   from it are labelled `vintage: unavailable`, and any claim resting on them says so in the same
   sentence. Back-filling a plausible past revision would be fabricated data (principle 5) and is
   forbidden — including the tempting version, reconstructing what a magnitude "probably was" from
   a revision history that does not record it.

## Consequences

- Rupture's existing numbers were all produced on final data, so every one of them is an upper
  bound on what the same model would have scored in real time. `RELEASE_STATUS.md` must say so, and
  no comparison against a published figure scored on final data is valid until both sides are
  replayed. The size of the correction is unknown and is the point of decision 6.
- The store accumulates **forward**. For everything before the first snapshot there is no vintage
  and there never will be unless a provider publishes its own revision history; whether ComCat,
  SCEDC, INGV or GeoNet do so at the granularity required is an open question below. This is the
  strongest practical argument for the prospective benchmark
  ([ADR-0057](0057-prospective-open-benchmark.md)), where the problem does not arise because the
  data does not exist yet.
- Latency interacts with completeness rather than being independent of it: the real-time catalogue
  is not merely a delayed archive, it is a differently-complete one, which is why
  [ADR-0060](0060-completeness-as-a-field.md) requires an Mc field with a time argument rather than
  a scalar per region.
- Cost is small for catalogues (a daily snapshot of a regional catalogue is megabytes) and is not
  small for geodesy or waveforms. No cost model has been computed and none is asserted here.
- The half-open convention is unchanged and applies on this axis too: an observation is readable
  at *t* when `available_time < t`, **strictly**, and windows stay `[from, to)`. The boundary case
  is not pedantry — a value published in the same instant as the issue is exactly the ambiguity a
  model author would resolve in their own favour — so it is written as an assertion that fires
  (`ARCHITECTURE.md` § 3.4 test 1: an observation with `available_time == as_of` must raise, not be
  quietly dropped).

## Failure criterion

If the replay report shows that as-of minus final skill is within bootstrap noise for every model
and every sequence tested, latency is not a practical leakage class in this domain, and the as-of
layer is demoted from an evaluation requirement to a data-engineering convenience. This criterion
is recorded before the measurement, and it is one of the four conditions under which the whole
re-aim was wrong ([ADR-0053](0053-rupture-targets-earthquake-prediction.md)).

## Alternatives considered

- **Keep `before(t)` and rely on contributor discipline.** Rejected for the reason ADR-0022 already
  gives about leakage generally: it is invisible in a diff and it shows up as good news, which is
  exactly when reviewers relax. Latency is worse than ordinary leakage on this axis, because the
  code that commits it looks correct — it *is* filtering on timestamps.
- **Model latency as a single per-source constant.** Rejected: the lag is a property of the product
  tier and of the event (a large event is reviewed faster than a small one), and a constant would
  give the illusion of a control while still serving the reviewed magnitude.
- **Vintage only the catalogue.** Rejected: the observables the prediction programme is aimed at
  are geodetic and continuous, and that is precisely where the lag is longest and the accuracy
  difference between tiers is largest. Catalogue-first is the *build order*, not the scope.
- **Reconstruct historical vintages from providers' revision metadata.** Not rejected, deferred and
  bounded: where a provider publishes an authoritative revision history it is ingested as a vintage
  with that provenance. Where it does not, nothing is reconstructed.
- **Trusted third-party archiving of snapshots.** Not rejected; an open question below.

## Open questions

- Which of ComCat, SCEDC, INGV and GeoNet expose a per-event revision history sufficient to
  reconstruct a past vintage, and at what granularity. Not established.
- Whether `available_time` should be the provider's publication timestamp or rupture's first
  observation of it. They differ by the polling interval, and the honest default is to record both;
  which one the gate compares against is unresolved.
- Whether the vintaged store should be mirrored somewhere rupture does not control, so that a
  vintage is not merely rupture's assertion about the past. Related to
  [ADR-0056](0056-preregistration-by-git-ancestry.md), which has the same shape of problem.
