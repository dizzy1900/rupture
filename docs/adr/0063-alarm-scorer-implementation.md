# ADR-0063 — The alarm scorer: reference-first, powered, and written to be upstreamed

- **Status:** accepted
- **Date:** 2026-09-10 (UTC)
- **Implements:** [ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md) (the `AlarmSet` arm
  of the hypothesis sum type, decisions 1–6)
- **Related:** [ADR-0059](0059-reference-baseline-set.md) (the reference baseline set),
  [ADR-0061](0061-interoperate-with-csep-do-not-fork.md) (upstream rather than fork),
  [ADR-0054](0054-latency-aware-observation-sources.md) (as-of vintage, still not built),
  [ADR-0010](0010-pycsep-evaluation.md) (the pycsep path, which this does not touch)

## Context

ADR-0055 declared five hypothesis arms and registered a scorer for none of them. The README's
scoring table listed alarm scoring — Molchan trajectory, area skill score, probability gain at a
declared alarm fraction — as **not built**, and RELEASE_STATUS recorded that no result in the
repository reported its statistical power even though ADR-0055 decision 4 made that mandatory. The
alarm arm is the one place a non-catalogue precursor claim from outside rupture can be adjudicated
at all, and adjudicating other people's claims is the strongest available route to standing for an
open project.

The decision here is not *whether* to build it — ADR-0055 settled that — but the handful of
choices the mathematics does not make for you, each of which is a way the result can be wrong.

## Decision

1. **The horizontal axis of every trajectory is reference mass, not area.** `tau` at a threshold
   is the share of the events the *reference model* expects to fall inside the alarm. Scoring
   against area credits an alarm for knowing that earthquakes happen on faults, which is not a
   prediction. `ReferenceKind` carries which reference a score used, and a spatially uniform one
   raises `UniformReferenceRefusedError` unless the caller passes `as_contrast=True`, which
   stamps `CONTRAST ONLY` into the score's own notes.

2. **The schedule is the unit of evidence, not the window.** `rupture.scoring.schedule` pools every
   window of an experiment into one trajectory over `(window, cell)` bins, each window weighted by
   the events its own reference expects there. A single 30-day window carries too few targets to
   reject anything, and averaging windows normalised to one apiece would let a quiet month
   outweigh an aftershock sequence.

3. **Power travels with every p-value and every null states an upper bound.** Under the null, hits
   in an alarm of mass `tau` are `Binomial(N, tau)`; under the alternative "this alarm has true
   probability gain G" they are `Binomial(N, min(G·tau, 1))`. Both are exact, so the power and the
   minimum detectable gain are computed rather than simulated. Where *no* gain is detectable — the
   test has no rejection region at all — the scorer says so and reports the unattained bound
   `G < 1/tau`, which is the honest description of an experiment that could not have failed.

4. **The default alternative is G = 2.** Nakatani (2020) puts every non-triggering precursor
   phenomenon he reviews below G = 20 and most near 2, while clustering alone reaches the hundreds.
   An experiment powered only against G = 20 has decided its answer before it starts.

5. **A gain read off the best point of a swept trajectory is never the result.** It is a maximum
   over thresholds and is biased upward. A gain is quoted only at an operating point the author
   declared in advance; without one, the claim is the whole trajectory, and the best point appears
   in the notes labelled "for orientation only".

6. **The mathematics lives in an array-only module.** `rupture.scoring.molchan` takes numpy arrays
   and returns numbers, and an import-linter contract stops `rupture.scoring` importing anything
   outside `rupture.domain`. ADR-0061 commits rupture to interoperating with CSEP rather than
   forking it; pyCSEP has no alarm-forecast class; code that has not entangled itself with this
   repository's domain types is code that can be offered to another.

7. **Decision 6 of ADR-0055 is enforced by functions, not by prose.** `rupture.scoring.refusals`
   raises on `auc`, `accuracy`, `rmse`, `mae`, `parimutuel` and `random_split`, and hands back the
   citation. A cross-referencing entry resolves its pointer before raising, because a refusal that
   says only "see the other one" is one somebody will override.

8. **The area skill score is not the AUC that decision 6 bans.** Cell-level AUC ranks cells and
   drowns in the 99.99 % that hold no event. The area skill score weights by *events* on one axis
   and by the *reference measure* on the other, which is the fix for that imbalance rather than an
   instance of it. The distinction is recorded here because the two are one substitution apart in
   code.

## Consequences

- `validate-alarm` is the tenth gate and runs in CI. It takes about 40 s — the slowest offline
  gate, because it fits ETAS on the fixture and issues six windows — and it measures a result
  rather than only exercising machinery.
- **The reference effect is now measured in this repository rather than cited from elsewhere.**
  On the committed California fixture, the trivial "declare near whatever just broke" rule
  (Luen & Stark 2008) scores an area skill of **0.996 (p = 0.0004)** and a probability gain of
  **G = 4.91 (p = 0.042)** against a spatially uniform reference, and **0.354 (p = 0.75)** and
  **G = 1.09 (p = 0.85)** against a fitted ETAS reference on the same window with the same targets.
  That is Zhang et al. (2024) reproduced from scratch, and it is now a regression test.
- **Pooled over the full six-window schedule the same rule scores G = 0.049 — worse than the
  reference.** The first window is issued three days before the Ridgecrest M6.4 and holds 123 of
  the schedule's 130 targets, and a rule that can only react has nothing to say there. The single
  window and the schedule are both true, and reporting only the flattering one would be the
  failure this arm exists to catch.
- **ETAS scored as an alarm against itself pools to an area skill of 0.029, not 0.5.** The 0.5
  identity holds when targets are drawn *from* the reference, which is what the unit tests assert;
  on real targets the figure measures how well the model's own allocation of its expected events
  matched where they fell, across windows as well as in space, and ETAS put its mass in the month
  after the mainshock rather than the month of it. That is a property of ETAS, not of the scorer.
- The `RateForecast` arm is **still scored outside the registry**, through the pycsep adapter.
  Moving it in would rescore committed results, which is a separate change with its own evidence
  burden; `registry_table()` says so by name rather than implying the registry is complete.
- **Vintage is still not enforced.** ADR-0054's as-of layer does not exist, so every alarm score
  carries a note saying that a revised magnitude is indistinguishable here from a timely one. The
  scorer refuses a reference fitted *after* the issue time, which is the leakage class that can be
  detected without a vintage store; the one that cannot is stated rather than papered over.
- `HazardFunction` and `StateEstimate` remain unimplemented and now refuse by name with their
  mandatory reference quoted, rather than by absence.

## Alternatives considered

- **Score each window separately and average the gains.** Rejected: a gain is a ratio, its
  sampling distribution on a handful of targets is wild, and averaging ratios across windows with
  different expected counts weights the quiet months equally with the sequences. Pooling the bins
  and sweeping one global threshold is the same experiment done once.
- **Take the null distribution of the area skill score from an asymptotic form.** Rejected in
  favour of a Monte Carlo over catalogues drawn from the reference. The asymptotic form assumes
  away exactly the small-N regime where alarm claims are usually made, and the simulation costs
  milliseconds.
- **Let the scorer pick the best operating point when none was declared.** Rejected. That is the
  bias this arm exists to expose, and a scorer that offers the option will have it used.
- **Bin the reference by magnitude as well as space.** Deferred, not rejected. An alarm declares a
  magnitude threshold rather than a magnitude distribution, so the spatial marginal above that
  threshold is the matching object; a magnitude-resolved alarm would need its own arm.
