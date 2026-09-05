# ADR-0055 — A hypothesis is a sum type, and every arm has a registered scorer

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Related:** [ADR-0010](0010-pycsep-evaluation.md) (pycsep, which becomes the scorer for one
  arm), [ADR-0053](0053-rupture-targets-earthquake-prediction.md),
  [ADR-0054](0054-latency-aware-observation-sources.md),
  [ADR-0059](0059-reference-baseline-set.md),
  [ADR-0061](0061-interoperate-with-csep-do-not-fork.md)

## Context

Rupture's evaluation spine is one shape, and it is the CSEP shape:

```
ForecastModel.fit(Catalog, Region, cutoff) -> FitResult
ForecastModel.forecast(history, issue_time, horizon) -> ForecastGrid
Evaluator.evaluate(ForecastGrid, target, tests) -> [EvaluationResult]
```

`ForecastGrid` is an expected rate per (cell, magnitude bin, window). It is a good object and the
tests that score it — N, M, S, L, CL, paired T and W — are the ones a reviewer recognises. It is
also the *only* object rupture can express, and several of the claims a prediction project must
adjudicate are not that object at all:

- An **alarm**: a region, a window, and a declaration. It has no rate. Asking it for a likelihood
  requires inventing a probability model, and the invented model is then the thing under test
  rather than the alarm.
- A **hazard function**: instantaneous rate as a continuous function of time from now. Quantising
  it into 30-day windows discards the quantity of interest, which is the shape of skill against
  lead time.
- A **state estimate**: this patch is at X % of failure stress, with uncertainty. The laboratory
  literature the review rates most highly identifies exactly this as the predicted quantity —
  Norisugi, Kaneko & Rouet-Leduc (2025, *Nature Communications*, `single-study`) pair a
  metre-scale rock-fault experiment (34 events, time-to-failure R² = 0.84 from catalogue-network
  features) with a rate-and-state simulation identifying the predicted quantity as shear stress on
  velocity-strengthening creeping patches. There is no rate grid in that sentence.

CSEP's consistency tests score the rate-grid form and were explicitly not designed to adjudicate
alarm-based or precursor claims. The machinery for those exists and is mature — Molchan diagrams
and the area skill score (Zechar & Jordan 2008, `widely-used`), Luen–Stark conditional nulls
(2008, `widely-used`) — but it lives outside pyCSEP, which the review notes has no alarm-forecast
class at all.

So the scoring gap is an architecture gap. A project that can only represent rate grids can only
make CSEP-shaped claims, and the reason to fix it is not tidiness: it is that the alarm arm is the
only place a non-catalogue precursor claim from outside rupture can be adjudicated, and
adjudicating other people's claims is the review's strongest recommendation for how this project
earns standing.

Two further facts shape the arm-by-arm scoring rules.

**A test can be silently powerless.** Khawaja et al. (2023, `single-study`) show the S-test cannot
reject a uniform, non-informative global forecast on a 0.1° grid — roughly 32,000 M ≥ 5.95 events,
about three centuries, would be needed — while a data-driven multi-resolution quadtree restores the
same discrimination with about 8. A pass is not evidence unless the test could have failed.

**Reference choice manufactures alarm skill.** Zhang et al. (2024, *JGR: Solid Earth*, doi
10.1029/2023JB028037, `single-study`) show an LSTM alarm for M ≥ 5 in mainland China looks skilful
on a Molchan diagram against a spatially uniform Poisson reference and loses its skill against a
spatially varying Poisson one. Luen & Stark make the same point from the other direction: a trivial
rule keyed to recent large events reaches high significance purely from clustering. Nakatani (2020)
sets the effect size an experiment must be powered for: every non-triggering precursor phenomenon
reviewed sits at probability gain G < 20, mostly around 2, while clustering alone gives G in the
hundreds to thousands.

## Decision

1. **`Hypothesis` is a discriminated union.** Five arms, each a distinct domain type with its own
   contract, its own scorer and its own mandatory reference:

   | Arm | What it asserts | Scored by | Mandatory reference |
   |---|---|---|---|
   | `RateForecast` | expected rate per cell, magnitude bin and window (today's `ForecastGrid`) | CSEP N/M/S/L/CL, paired T and W on information gain per earthquake, via pycsep | ETAS; ETAS-I where sub-completeness events are used |
   | `SimulatedCatalogues` | an ensemble of synthetic catalogues for the window | catalogue-based (non-Poissonian) number, spatial, magnitude, pseudo-likelihood and calibration tests | as above |
   | `AlarmSet` | region × window × declare/do not declare | Molchan trajectory, area skill score, probability gain G reported with alarm fraction | a clustering-aware reference (ETAS or spatially varying Poisson) **and** a random alarm set matched on alarm rate and spatial footprint |
   | `HazardFunction` | instantaneous rate as a continuous function of time from the issue instant | continuous-time log-likelihood under a proper scoring rule | the same reference expressed as a hazard function |
   | `StateEstimate` | a latent (stress, slip rate, coupling, time-to-failure) with uncertainty | calibration against later-observed outcomes; interval coverage | a persistence or climatological estimator of the same latent |

2. **Scorers live in a registry keyed by arm, and the registry is the only way to obtain a score.**
   There is no generic `evaluate(anything)`. Adding an arm means registering a scorer and a
   reference; a hypothesis whose arm has no registered scorer cannot be scored, and that is
   reported as `NOT_IMPLEMENTED` rather than approximated by the nearest available test.

3. **The harness refuses to emit a score without its reference**, computed on the same targets, the
   same as-of vintage ([ADR-0054](0054-latency-aware-observation-sources.md)) and the same
   completeness field ([ADR-0060](0060-completeness-as-a-field.md)). The reference set is
   [ADR-0059](0059-reference-baseline-set.md). This is the single rule that stops the commonest
   way a published result turns out to be nothing.

4. **Every test result ships its statistical power.** A consistency test reports the power it had
   against a named informed alternative on the grid it was run on, and rate-grid claims default to
   data-driven quadtree grids rather than fixed 0.1° cells. A p-value without a power figure is not
   a finding.

5. **Every null result states an upper bound.** Not "we saw nothing" but the minimum effect
   detectable at the achieved sensitivity. The template the review rates most highly is Hirose,
   Kato & Kimura (2024, *GRL*, `negative-result`), which bounds pre-Tohoku preslip below 5 × 10¹⁸
   N m — about M_w 6.4 — rather than reporting an absence.

6. **Metrics the registry refuses to compute**, because they have manufactured results in this
   field and refusing is cheaper than reviewing:
   - accuracy or AUC on imbalanced grid cells. Jover-Alfaro et al. (2026, `negative-result`)
     replicated a published Random Forest at 97.97 % accuracy and watched it fall to 21–24 % under
     walk-forward validation against a 27.69 % baseline, and to 16 % cross-region. DeVries et al.
     (2018, *Nature*, doi 10.1038/s41586-018-0438-y) reported AUC 0.849 and was matched by a
     two-parameter logistic regression at AUC 0.85 and beaten by distance-plus-slip at 0.86 (Mignan
     & Broccardo 2019, doi 10.1038/s41586-019-1582-8; Meade et al. reply doi
     10.1038/s41586-019-1583-7) — the DeVries entry is `rebutted` and is never cited here without
     that rebuttal in the same sentence;
   - RMSE or MAE on power-law targets;
   - any split that is not chronological (already ADR-0022 rule 3, restated here because it is a
     property of the scorer, not only of the splitter);
   - the parimutuel gambling score, which is improper.

7. **The existing ports become one arm, not the spine.** `ForecastModel` and `Evaluator` keep their
   shape and their pycsep adapter (ADR-0010) as the `RateForecast` implementation. Nothing already
   scored is rescored differently by this ADR.

## Consequences

- pyCSEP has no alarm-forecast class, so rupture writes one. Under
  [ADR-0061](0061-interoperate-with-csep-do-not-fork.md) it is written to be upstreamed, because
  an alarm scorer inside pyCSEP adjudicates the whole field's claims and the same code inside
  rupture adjudicates rupture's.
- `StateEstimate` has no community-standard scorer. Calibration against later-observed outcomes is
  the obvious construction and it is *not* a settled protocol in this field; **citation needed**.
  It is registered as the weakest arm and every claim on it says so.
- Comparability across arms is not claimed and is not available. An information gain in nats per
  event and an area skill score are different quantities; a model that wins one has not won the
  other. The review's fourth scoring layer — reporting gain as a fraction of an estimated
  predictability budget — is the only candidate for a common denominator, and it rests on Zhuang &
  Sornette's July 2026 preprint, which the audit downgraded from `widely-used` to a five-week-old
  unreviewed `single-study`. Adoptable as a framework; its specific claims are untested.
- The union has five arms and every one is a maintenance surface. An arm with no live experiment is
  a liability, so an arm is added when an experiment needs it, and `HazardFunction` and
  `StateEstimate` are declared before they are implemented precisely so that nobody encodes them as
  degenerate rate grids in the meantime.
- None of the new arms exists in code today. `src/rupture/ports/` holds `forecast_model.py` and
  `evaluator.py` and nothing else of this shape; this ADR records the contract, not a delivery.

## Alternatives considered

- **Encode an alarm as a degenerate rate grid.** Rejected. A Molchan trajectory needs an alarm
  threshold and a spatial footprint that a rate grid does not carry, and the CSEP consistency tests
  do not score the object you get. It also quietly imposes a probability model on a claim whose
  author did not make one — which is how a precursor community's claim gets scored against a
  strawman version of itself.
- **One universal scorer, everything in nats.** Rejected: proper scoring rules are defined relative
  to the object being forecast, and an alarm has no likelihood without an assumed probability
  model.
- **Keep the rate grid and adjudicate alarms by hand, in prose.** Rejected: a hand adjudication is
  not reproducible, and the review's record of alarm disputes — RTP significant only if contentious
  alarms are counted as successes — is a record of what hand adjudication produces.
- **Adopt pyCSEP's class hierarchy directly as rupture's domain types.** Rejected on the standing
  rule that adapters never expose third-party types to the domain (ADR-0010), and because the arms
  rupture needs do not exist there.
