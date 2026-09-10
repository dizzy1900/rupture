# ADR-0064 — Data vintage is a property of every observation, and it is measured before it is enforced

- **Status:** accepted
- **Date:** 2026-09-10 (UTC)
- **Implements (partly):** [ADR-0054](0054-latency-aware-observation-sources.md) (latency-aware
  observation sources)
- **Related:** [ADR-0022](0022-leakage-engineering-for-learned-models.md) (leakage engineering),
  [ADR-0010](0010-pycsep-evaluation.md), [ADR-0063](0063-alarm-scorer-implementation.md)

## Context

Rupture's evaluation has been time-forward on `origin_time` since the protocol was written, and
the leakage assertions in `adapters/forecasting/leakage.py` prove it on real timestamps rather
than in prose. That is necessary and it is not sufficient, and the README has said so from the
re-aim onward: **the value at time *t* may not have existed at time *t*.** Catalogues are revised,
GNSS orbits lag, and the first hours after a mainshock are incomplete in real time in a way the
archive never is.

ADR-0054 proposed an as-of layer and RELEASE_STATUS recorded two things about it. First, that none
of it exists — `Provenance.retrieved_at` is rupture's fetch time, not the value's publication
time, and `leakage.py` compares only `origin_time`, "so every existing leakage assertion would
pass on a model reading a 2026-revised magnitude at a 2019 issue time". Second, and more
awkwardly, that the claim underwriting the whole layer is itself untested: *nobody has measured
(final-data skill − as-of skill) for a set of published models, and if that difference sits inside
bootstrap noise everywhere then the as-of layer should be demoted from an evaluation requirement
to a data-engineering convenience.*

Building an enforcement layer for an effect nobody has measured is how a project acquires
machinery it cannot justify. So this ADR does the measurement first, with what is already in the
tree, and enforces nothing yet.

**The measurement.** ComCat's GeoJSON carries `updated` on every feature — the last time the
record changed. The committed California fixture, 1,433 events, 2018–2019:

| | |
|---|---|
| records carrying a vintage | 1,433 of 1,433 |
| median `updated − origin` | **191.6 days** (p90 1,069 d, max 2,759 d) |
| events a 2019-07-01 fit would train on | 217 |
| …whose record was last modified **after** that cutoff | **69 (32 %)** |
| targets scored across the six 30-day windows | 130 |
| …whose record was last modified **after** the window they were scored in | **130 (100 %)** |

Every one of those events passes `assert_all_before`. The existing assertions are not weak; they
are answering a different question.

## Decision

1. **An observation carries two times.** `Event.available_time` is the earliest instant at which
   the record, *in the form held here*, can be shown to have existed upstream. `origin_time` stays
   what it was. The ComCat adapter populates `available_time` from `updated`; ISC and GCMT do not
   carry one yet and get `None`.

2. **`None` means unknown, and unknown is not "available immediately."** `VintagePolicy` makes the
   choice explicit at every call site: `EXCLUDE_UNKNOWN` is the provable view and empties a
   catalogue with no vintage at all; `INCLUDE_UNKNOWN` is what every result in this repository
   already assumes. Naming it makes an ambient assumption into a recorded one.

3. **`Catalog.as_of(t, policy)` is a different filter from `Catalog.before(t)`,** and a fit at *t*
   composes both. They are kept separate rather than merged because an event can fail either
   independently and a caller should have to say which it meant.

4. **`assert_available_before` is rule 4, and it is not wired into the existing pipelines.**
   Turning it on would change every number in the ledger in one commit, with the cause and the
   effect entangled. It is used by the `asof` gate to measure the exposure, and enforcement is a
   separate decision taken on the evidence.

5. **`ports/observation_source.py` declares `available_as_of` and nothing implements it.** The
   catalogue adapters fetch the present and stamp the vintage the provider reports, which is
   enough to measure exposure and not enough to reconstruct a past state. Declaring the port
   without an adapter is deliberate: it stops the next person encoding a vintage query as a
   `retrieved_at` filter, which is what `Provenance` invites.

6. **`validate-asof` reports exposure as a measurement and the ablations as bounds,** and says in
   its own output which is which.

## Consequences

- **The first evidence on the question that underwrites the layer.** Restricting the 2019-07-01
  ETAS fit to provably-available records drops it from 214 to 145 events, moves `gamma` from 1.544
  to 1.069, and moves the window's total expected count from 1.089 to 0.653 — a 40 % change in the
  headline rate. **No consistency-test verdict flipped.** N, S, L and CL reject both ways; M passes
  both ways. On this window, revision cannot reach the result through the training path.
- That is *one window, one region, one fixture*, and it is evidence for demoting the as-of layer
  only if it holds across many. It is recorded as a first data point, not as a finding.
- **The ablation bounds one direction only.** Dropping the records of unproven vintage is not the
  same as restoring their old values: the events were in the catalogue at the time, with values
  nobody kept, so the ablation fits a *smaller, different* catalogue. If the score does not move,
  revision cannot reach it through that path; if it moves, revision only *might*. The gate says so
  in its output rather than in a footnote here.
- **The skill difference is still not computed, and cannot be from a single vintage.** It needs
  archived vintages: periodic ComCat snapshots taken forward from now, or a provider that serves
  as-of queries. That is the next step and it is a data-engineering task with a lead time measured
  in months, which is itself a reason to have started the clock.
- `Event` gained an optional field, so every existing catalogue, fixture and Parquet round-trip
  keeps working with `available_time = None` and reports coverage 0 % rather than silently
  claiming provenance it does not have.
- **100 % target exposure is partly an artefact of when the fixture was fetched.** It was
  retrieved in 2026 for events in 2019, and ComCat re-touches records for reasons that have
  nothing to do with the magnitude. The figure bounds what is *provable*, not what *changed*, and
  the distinction is the reason this ADR reports exposure rather than error.

## Alternatives considered

- **Wire `assert_available_before` into the pipelines now.** Rejected. Every scored window in the
  ledger would move at once and the commit would carry both the mechanism and its consequences.
  Measure, then decide, then enforce.
- **Treat `Provenance.retrieved_at` as the vintage.** Rejected, and it is the trap this ADR
  exists to close: `retrieved_at` is when *rupture* fetched the payload, which for the fixture is
  2026-09-03 for every one of its 1,433 events. It carries no information about the record.
- **Reconstruct as-of values by interpolating between vintages.** Rejected: there is one vintage.
  Inventing intermediate values would manufacture exactly the kind of plausible number this
  repository refuses elsewhere.
- **Drop `available_time` and filter on ComCat's `status` field instead.** Rejected as
  insufficient — `automatic` versus `reviewed` is a coarse two-state proxy for the same thing and
  loses the timing entirely — but it is a useful cross-check and is worth adding later.
