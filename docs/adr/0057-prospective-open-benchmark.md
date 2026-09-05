# ADR-0057 — A continuously-running prospective open benchmark

- **Status:** proposed. Downgraded from `accepted` on 2026-09-05 — see "Why this is proposed and
  not accepted" at the end. The design is not in question; the staffing is.
- **Date:** 2026-09-04 (UTC)
- **Amends:** [ADR-0015](0015-pseudo-prospective-evaluation.md) — pseudo-prospective replay remains
  valid and remains the only thing rupture can do on historical data; it is no longer the strongest
  protocol available
- **Related:** [ADR-0054](0054-latency-aware-observation-sources.md),
  [ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md),
  [ADR-0056](0056-preregistration-by-git-ancestry.md),
  [ADR-0061](0061-interoperate-with-csep-do-not-fork.md)

## Context

Every control in [ADR-0054](0054-latency-aware-observation-sources.md) and
[ADR-0056](0056-preregistration-by-git-ancestry.md) is a defence against reading the future, and
every one of them can in principle be defeated by someone determined enough or careless enough.
There is exactly one protocol in which the defence is structural rather than procedural: issue the
forecast before the data exists. Held-out data that has not happened yet cannot be leaked on,
cannot be revised into a flattering shape, and cannot be peeked at by a hyperparameter search. It
is leak-proof by construction rather than by discipline, and it is the only such thing available.

CSEP has run a version of this for two decades and it is the credential the field recognises — the
2024 Delphi elicitation of 20 experts found 74 % agree a model is ready when it has been tested by
a third party such as CSEP, and 79 % consider comparison to a benchmark model important, the only
near-consensus requirement in the survey. What CSEP's testing centres score is rate grids and
simulated catalogues. They do not score alarms, hazard functions or state estimates; they evaluate
on the archival catalogue rather than the one that existed at issue time; and the submission path
was built for institutional modelling groups rather than for someone with a Hugging Face account.

Two things changed recently enough that an open project can now operate this. floatCSEP (Iturrieta
et al., *JOSS* 11(118), 9408, February 2026, BSD-3) runs a whole prospective experiment from a YAML
file with Docker-pinned models and a `reproduce` command — registration became a day of engineering
rather than a multi-institution negotiation. And the CSEP Italy 2024 short-term experiment accepts
simulated-catalogue forecasts on an open call and publishes results continuously. The audit's
warning applies to both: the survey tagged floatCSEP `widely-used`, and a tool published in
February 2026 cannot have that property. Treat it as new, official and small — 475 commits, a
handful of stars — rather than as established.

## Decision

1. **Rupture operates a continuously-running, forward-in-real-time benchmark.** Models are
   registered as containers with a pre-registration ([ADR-0056](0056-preregistration-by-git-ancestry.md))
   before a window opens; forecasts are issued on a fixed cadence from the as-of layer
   ([ADR-0054](0054-latency-aware-observation-sources.md)); scoring runs after the window closes,
   against the vintaged catalogue as it stood at the scoring instant, with the vintage recorded.

2. **Every hypothesis arm is accepted, not only rate grids.**
   ([ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md).) This is the substantive
   difference from an existing testing centre, and it is what allows a precursor claim from outside
   rupture to be adjudicated at all instead of argued about.

3. **Reads are as-of by construction.** A registered container is served the data that was
   available at its issue instant, from the same store that serves the replay harness. A model
   cannot obtain the final-orbit solution or the reviewed magnitude, because the benchmark does not
   have it yet either.

4. **Baselines run continuously alongside the submissions**, fitted under the same protocol, from
   the same vintages ([ADR-0059](0059-reference-baseline-set.md)). The board reports paired gain
   against the baseline, never a bare score, and the baselines are visible from the first minute so
   a newcomer can see the bar.

5. **Nulls and models are owned by different people.** A submitter owns the model and declares its
   failure criterion before results exist. A review board — seismologists, statisticians — signs
   off on the null and reference for each experiment before any result is computed. Neither
   population grades its own homework, and that separation is the governance content of this ADR
   rather than a nicety.

6. **Every result is published with its statistical power and its expected time to decision.** The
   benchmark's own power is its binding constraint (see costs below) and hiding it would make the
   board a source of false confidence rather than a source of evidence.

7. **Rupture also submits to CSEP rather than only to itself.** Every model is packaged
   floatCSEP-compatible and submitted to the live Italy 2024 experiment. A board rupture operates
   and scores is not third-party adjudication, and third-party adjudication is the credential
   ([ADR-0061](0061-interoperate-with-csep-do-not-fork.md)).

8. **The scoring function ships before the first model.** The evaluation layer, the baselines and
   the board are the first release. Inverting the usual order is the clearest available signal that
   the project is not building a scoreboard it intends to win.

## What it costs to operate, honestly

- **Continuous operation is a duty roster, not a platform.** rupture already has a Docker image as
  its deployment unit (ADR-0016) and portable job manifests, so the marginal engineering is a
  scheduler, an object store and a results database. The marginal *human* cost is someone
  responding when a provider changes an endpoint or a feed stops, on a cadence measured in days,
  indefinitely. That is the cost that kills volunteer infrastructure, and no ADR can make it
  smaller. **No cost model has been computed and none is asserted here.**
- **Storage is asymmetric.** A daily vintage of a regional catalogue is megabytes; a daily vintage
  of geodetic products is larger by orders of magnitude and a continuous waveform slice is larger
  again. The catalogue-first build order is a budget decision as much as an engineering one.
- **Targets arrive at the earthquake rate.** This is the real cost and it is statistical, not
  financial. A next-day California experiment at the RELM threshold accumulates a handful of target
  events a year; Khawaja et al. (2023, `single-study`) show the S-test needs about 32,000 M ≥ 5.95
  events on a 0.1° global grid to reject a uniform forecast, and about 8 on a data-driven quadtree.
  A prospective board can therefore take years to distinguish two models, and saying so on the
  board is decision 6. rupture's own experience is the local version of this: 33 of 55 Nepal
  windows held no target event at all, leaving four of the five consistency tests undecidable
  (`RELEASE_STATUS.md`).
- **A benchmark is a commitment that cannot be quietly abandoned.** Stopping a prospective
  experiment after a bad quarter is indistinguishable from stopping it because of the quarter, so
  the stopping rule is declared at the start: the benchmark runs for a fixed initial term, and the
  decision to continue or stop is made on the criterion below rather than on the results.

## What happens if nobody submits

The most likely outcome in the first year, and it has to be worth doing anyway or the board should
not be built.

If no external model is registered, the benchmark still issues and scores the baselines against
each other, and the deliverable becomes a published prospective baseline record — the shape of
Serafini et al. (2025, *Scientific Data* 12, 1501, doi 10.1038/s41597-025-05766-3), the ten-year
archive of prospective next-day California forecasts that the review calls the closest thing to a
real prospective track record in the whole bibliography. A second such record, latency-honest and
covering arms CSEP does not score, is a contribution on its own.

**Failure criterion.** If after twelve months of operation there has been no external submission
and no external group or testing centre has adopted the as-of API, the board is a private
scoreboard. In that case rupture folds its models into the CSEP experiments, keeps the as-of layer
as internal infrastructure, publishes the operating experience as a negative result about open
benchmark design, and stops operating a separate board. This is one of the four conditions under
which the re-aim was wrong ([ADR-0053](0053-rupture-targets-earthquake-prediction.md)).

## Consequences

- ADR-0015's pseudo-prospective replay is unchanged and remains the protocol for historical data;
  what changes is that it is no longer the best rupture can offer, and results carry which protocol
  produced them.
- From the first archived forecast onward, rupture accumulates genuinely prospective results.
  ADR-0015 anticipated this and said nothing in the design changes when it happens; that is still
  true of the replay path and is not true of the infrastructure, which this ADR is.
- The benchmark is the only place where [ADR-0056](0056-preregistration-by-git-ancestry.md)'s
  weakest failure mode — data that existed before the registration — cannot occur, so a result
  earned here is categorically stronger than the same result earned on a replay, and the board says
  so per row.
- Operating a public board on earthquake forecasts carries a communication risk that a repository
  does not. Every artefact states in its metadata that it is research and not an alert
  ([ADR-0053](0053-rupture-targets-earthquake-prediction.md) decision 7), and the board carries the
  same statement on its face. The L'Aquila convictions were about communication, not about failing
  to predict.

## Alternatives considered

- **Submit only to CSEP and operate nothing.** Rejected, though it is the cheapest option and
  rupture does it as well (decision 7): CSEP's testing centres score rate grids, so the alarm and
  state-estimate arms — the arms that let rupture adjudicate other people's claims — would have
  nowhere to go.
- **A hidden test set with quarterly releases.** Kept as a complement for the retrospective corpus
  and rejected as a substitute. A hidden set is leak-proof only while the holder is honest and
  competent; the future is leak-proof against everyone, including the operator.
- **Wait until rupture has a model worth submitting.** Rejected. It inverts the order that makes
  the project credible, and it means the first prospective result arrives years after the first
  claim.
- **Fork pyCSEP into a rupture benchmark.** Rejected; see
  [ADR-0061](0061-interoperate-with-csep-do-not-fork.md).


## Why this is proposed and not accepted (2026-09-05)

Decision 1 commits rupture to operating a board on a cadence measured in days, indefinitely, and
decision 5 commits a standing review board of seismologists and statisticians to sign off on every
null before results are computed. `docs/ROADMAP.md` runs nine tracks (T1-T9) and **none of them
schedules, staffs or costs that operation**. An accepted ADR carrying an indefinite operational
commitment that no track owns is precisely the overclaiming CLAUDE.md principle 7 exists to stop,
and it would be the first thing a hostile reviewer found.

What is *not* downgraded, because it is already owned:

- **Decision 2 — every hypothesis arm is accepted, not only rate grids.** This is the substantive
  contribution and the reason this ADR is not redundant with an existing testing centre: CSEP was
  never designed to adjudicate an alarm-based or precursor claim, so today such a claim can only be
  argued about. That capability is [ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md) and
  the roadmap's T3, both of which stand.
- **Decision 3 — as-of reads** ([ADR-0054](0054-latency-aware-observation-sources.md), T1) and
  **decision 4 — continuous baselines** ([ADR-0059](0059-reference-baseline-set.md)) likewise.

So the scoring apparatus is being built; what is deferred is rupture *running its own board* rather
than registering into one that already runs. [ADR-0061](0061-interoperate-with-csep-do-not-fork.md)
makes that the cheaper path in the meantime: CSEP Italy 2024 is live and accepting submissions, and
floatCSEP makes registration roughly a day of engineering, so prospective testing — the actual
scientific requirement — is available without operating anything.

**What moves this back to accepted:** a named owner for the duty roster, a costed estimate for
continuous operation, and a roadmap track that carries both. Until then the ambition is preserved in
the harness rather than asserted in the ADR.
