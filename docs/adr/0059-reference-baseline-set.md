# ADR-0059 — The reference baseline set, and ETAS-I for any sub-completeness claim

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Extends:** [ADR-0009](0009-etas-baseline.md) (the ETAS baseline),
  [ADR-0040](0040-promotion-rule-single-encoding.md) (the promotion rule)
- **Related:** [ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md),
  [ADR-0058](0058-evidence-status-vocabulary.md),
  [ADR-0060](0060-completeness-as-a-field.md)

## Context

CLAUDE.md principle 3 says baselines are adversaries, not straw men. Under the old positioning that
was a single fact — ETAS, fitted properly, as the thing a challenger had to beat — and rupture
implemented it: ADR-0009 pins `lmizrahi/etas` at a commit, ADR-0040 encodes the promotion rule
once, and the published verdict is that no challenger beat ETAS.

The re-aim breaks the assumption underneath that arrangement, which is that there is one task and
therefore one baseline. There is not. An alarm has no ETAS to beat; a state estimate has no
likelihood; an aftershock forecast has a *weak* standard baseline and a strong one, and which is
used decides the result.

The review's diagnosis is blunt and it is the most actionable finding in the whole synthesis: **the
single most common failure in the surveyed literature is beating the weakest available baseline.**
Two instances carry the argument.

- QuakeGen (2026) beats the USGS Reasenberg–Jones baseline on 80 global mainshocks and only
  *matches* well-tuned ETAS regionally. Reported without that scope, it reads as a machine-learning
  win over the state of the art. (`single-study`; the code repository returns 404.)
- Every claimed machine-learning gain from small events is measured against **plain** ETAS, which
  was not designed for incomplete data, rather than against **ETAS-I**, which was. Mizrahi, Nandan
  & Wiemer (2021) built ETAS-I precisely to model short-term incompleteness and report that it
  outperforms plain ETAS pseudo-prospectively in California by simulating the small events plain
  ETAS cannot see; it has been MIT-licensed and available since 2021. The review found no
  machine-learning paper that has used it as a comparator. Stockman et al. (2023, *Earth's Future*
  11(9) e2023EF003777) — the cleanest of the positive results — beats ETAS at input M_cut 1.2 on an
  incomplete enhanced catalogue and ties at M3+. Read together, the honest reading of the field's
  machine-learning gains is that they are a robustness-to-incompleteness gain measured against the
  wrong baseline.

Meanwhile the null side is unusually clean. EarthquakeNPP (Stockman, Lawson & Werner, TMLR 2026)
tested five neural point processes on seven California catalogues and found that none beat ETAS on
temporal or spatial log-likelihood; ETAS wins the spatial component everywhere and has the highest
CSEP pass rates, with the neural models weakest during large sequences. (Tagged `replicated` in one
survey section and `single-study` in another; under
[ADR-0058](0058-evidence-status-vocabulary.md) the canonical tag is `single-study`.) And rupture's
own result agrees, from different data: Türkiye mean information gain +0.394 nats per event but one
paired-T win in ten windows and none in twenty-nine W-tests; Nepal −0.346 nats per event
(`reports/CHALLENGER_EVALUATION.md`).

## Decision

1. **A claim names its task, and the task fixes its mandatory reference.** The set:

   | Task | Mandatory reference | Notes |
   |---|---|---|
   | Catalogue rate forecasting at or above completeness | plain ETAS (`lmizrahi/etas`, MIT, pinned by ADR-0009) | the existing baseline of record |
   | Any claim using events below the completeness threshold | **ETAS-I, in addition to plain ETAS** | with the Mc field it needs ([ADR-0060](0060-completeness-as-a-field.md)) |
   | Aftershock sequence forecasting | tuned ETAS; USGS Reasenberg–Jones (opensha-oaf, CC0) may be reported **as the weak baseline and labelled as such** | beating R–J alone is not a result |
   | Time-independent or spatial-rate claims | Helmstetter-style smoothed seismicity | it won RELM |
   | Spatial aftershock or static-stress classification | the two-parameter logistic regression of Mignan & Broccardo (2019), and distance-plus-slip | the one-neuron baseline, shipped as a comparator |
   | Alarm-based claims (`AlarmSet`) | a clustering-aware reference — ETAS or spatially varying Poisson — **and** a random alarm set matched on alarm rate and spatial footprint | never uniform Poisson |
   | Slow-slip onset or recurrence claims | an inter-event-time baseline | |
   | `StateEstimate` claims | a persistence or climatological estimator of the same latent | the weakest row here; see below |

2. **The scorer registry refuses to emit a score without its reference**, computed on the same
   targets, the same as-of vintage, the same completeness field and the same protocol
   ([ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md) decision 3). "The baseline was run
   elsewhere" is not admissible; a number from a paper is not a baseline.

3. **Every baseline is published with its fit diagnostics**, as ETAS already is. An undiagnosed
   baseline is a straw man wearing a name, and the reader cannot tell the difference from the
   result alone.

4. **Where the baseline wins, that is the published result.** Unchanged from principle 3, restated
   because the re-aim increases the pressure on it.

5. **The weak baseline may be reported, never alone.** Reasenberg–Jones and uniform Poisson have a
   place — they are what the operational world and the older literature used — but a table
   containing them contains the strong reference in the adjacent column, in the same units.

6. **Alarm claims report probability gain G with the alarm fraction, and are powered for G < 20.**
   Nakatani (2020) puts every non-triggering precursor phenomenon reviewed at G < 20, mostly around
   2, while foreshock and aftershock clustering alone gives G in the hundreds to thousands. An
   experiment powered only to detect a large gain will find nothing and will have proved nothing.

## Consequences

- ETAS-I becomes a dependency rupture does not currently have and has never run. Nothing in this
  tree has been scored against it; every existing number is a comparison against plain ETAS only,
  and `RELEASE_STATUS.md` should say so.
- Compute per claim rises, in some cases by a factor equal to the number of references. rupture's
  Californian ETAS schedule is already 6 of 55 windows and stopped for cost
  (`RELEASE_STATUS.md`); adding a second reference makes that constraint tighter, not looser, and
  the honest consequence is fewer scored claims rather than the same number scored more cheaply.
- Some published comparisons become uncitable as support for a rupture claim, because their
  baseline is not in this table. They remain citable as *findings*, with their scope attached
  ([ADR-0058](0058-evidence-status-vocabulary.md) decision 6).
- The `StateEstimate` row is the weakest and is written as such. There is no community-standard
  reference for a fault-state estimate and rupture is not in a position to declare one;
  **citation needed**. Persistence is the honest default and any claim on that arm says that its
  reference is a placeholder.
- ADR-0040's single encoding of the promotion rule extends rather than changes: the rule still
  compares a challenger against the baseline of record over the same schedule; what this ADR
  changes is which baseline "of record" means for a given task.

## Failure criterion

If gains over plain ETAS are fully absorbed by ETAS-I on every dataset tested, the small-event
machine-learning result is an artefact of baseline choice. rupture publishes that as a definitive
negative and stops work on catalogue-only forecasting — which is a large fraction of what this
repository currently does. Recorded here before the comparison is run, and it is one of the four
conditions under which the re-aim was wrong
([ADR-0053](0053-rupture-targets-earthquake-prediction.md)).

## Alternatives considered

- **Let each experiment choose its own baseline and justify it in prose.** Rejected: baseline
  choice is where results are manufactured, and a justification written after the comparison is not
  a control. Fixing the table centrally is the same argument ADR-0040 makes for encoding the
  promotion rule once.
- **One universal baseline.** Rejected: ETAS is not defined for an alarm set or a state estimate,
  and forcing it to be would impose a probability model on a claim whose author did not make one.
- **Add ETAS-I later, once a challenger beats plain ETAS.** Rejected, and this is the crux: adding
  the harder baseline only when the easy one has been beaten is exactly the procedure that
  generated the literature this ADR is a response to.
- **Report against the weak baseline because it is what agencies operate.** Rejected as a
  *primary* comparison, accepted as a reported column: operational relevance and scientific
  novelty are different claims, and conflating them is how "beats the USGS baseline" becomes a
  headline.
