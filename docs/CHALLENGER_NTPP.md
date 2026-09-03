# Challenger C1a — a neural temporal point process

**rupture does not predict earthquakes.** This document reports how one learned model scored
against the ETAS baseline under `EVALUATION_PROTOCOL.md`. It is a record of rate forecasts and
their test outcomes, not a claim about any future event.

**Headline: the challenger is not promoted, and it could not have been.** It was scored on six
30-day windows; the promotion rule needs twelve consecutive windows in at least two of three
regions. It was also fitted on a two-year fixture catalogue rather than the protocol's regional
catalogues, which were not available in this worktree. Both facts are set out in § Data before any
score appears, because they bound what every number below can mean.

The fitted model additionally carries a **branching ratio of 1.002** — critical. See § What went
wrong.

---

## 1. What the model is

A marked spatio-temporal Hawkes process. The conditional intensity is

```
lambda(t, x, y) = mu * b(x, y)  +  sum over events i with t_i < t of  A_i * h_i(t - t_i) * g_i(r_i)
```

and the mark (magnitude) is drawn from a Gutenberg-Richter law with a fitted `beta`.

| Component | Form | Learned? |
|---|---|---|
| background rate `mu` | events per day over the whole region | yes (one scalar) |
| background density `b` | Gaussian kernel density over the **training** epicentres, bandwidth `background_sigma_km` | bandwidth is a hyperparameter; the points are fixed at fit time |
| productivity `A_i` | `exp(k0 + alpha (m_i - mc))`, the ETAS form, with `alpha >= 0` by construction | yes (two scalars) |
| temporal kernel `h_i` | convex mixture of `n_time_basis` modified-Omori densities with characteristic times spaced geometrically over 10⁻³–100 days, exponent `p = 1.15` fixed | **the mixture weights are a neural function of the event's magnitude and depth** |
| spatial kernel `g_i` | convex mixture of `n_space_basis` isotropic power-law densities with characteristic distances 0.5–50 km, exponent `s = 1.5` fixed | **as above** |
| mark law | Gutenberg-Richter, independent of time and place | yes (`beta`) |

The neural part is a two-hidden-layer tanh MLP mapping `(m - mc, depth)`, standardised on training
rows only and clipped to ±3 standard deviations, to two softmax vectors of mixture weights. It has
a few hundred parameters and trains in about twenty seconds on one CPU core.

**Why this shape.** Three properties, in order of weight. (1) Every basis element is a normalised
density, so the compensator `∫λ` is a sum of closed forms rather than a quadrature — the
likelihood is the real likelihood, and a model cannot improve its score by getting its own
normalisation wrong. (2) It is CPU-sized, which matches the amount of data actually available.
(3) It degenerates towards ETAS, so a negative result is interpretable: it says the extra
flexibility did not pay, not that the optimiser failed. ADR-0029 records the decision and the
alternatives.

**What is deliberately not neural.** An earlier version let the MLP add a bounded offset to
productivity. On 184 scored training events that produced a productivity curve oscillating by a
factor of fifty between neighbouring half-magnitude steps, and it made `alpha` non-identifiable
because the offset was itself a function of magnitude. Restricting the neural part to the kernel
*shape* — a softmax over densities, so any output is still a proper density — cost about 0.25 nats
per event on the training likelihood and bounded the model's behaviour on a magnitude larger than
anything it was trained on. Since the test period opens with a mainshock two units above the
training maximum, that was not a hypothetical concern.

## 2. EarthquakeNPP conventions

Conventions follow the EarthquakeNPP benchmark (Stockman, Lawson & Werner, *TMLR*, March 2026;
`ss15859/EarthquakeNPP`, MIT licence; arXiv:2410.08226v3) where they apply, so the numbers here sit
in the same frame as its published baselines.

### Adopted

| Convention | As used here |
|---|---|
| Time in **float days** from a fixed origin | `EventSequence.t`; the same unit the `etas` package uses |
| Locations in **projected kilometres**, not degrees | azimuthal equidistant projection about the region's bounding-box centre. Their `Datasets/README.md` directs point-process models to the projected `x, y` because ETAS works in great-circle kilometres |
| Hard magnitude cut, **no censored likelihood** below Mc | events below Mc are removed by an explicit filter before any tensor is built |
| Split boundaries are **calendar dates**, not fractions | `auxiliary_start → train_start → validation_start → test_start → test_end` |
| An explicit **auxiliary (burn-in) window** whose events condition the intensity but are not scored | `auxiliary_years`, mirroring the `etas` package's `auxiliary_start` |
| Reporting split of the log-likelihood **per test event** into temporal (`tll`) and spatial (`sll`) parts, with `nll = -(tll + sll)` | `LogLikelihood` in `models/challengers/ntpp/model.py` |
| Information gain reported as a difference in mean log-likelihood per event | via the pycsep paired T-test against ETAS |
| CSEP-style consistency tests alongside the likelihood | N/M/S/L/CL through the existing `PyCSEPEvaluator` |

### Departed from, and why

| Departure | Reason |
|---|---|
| **Magnitude is modelled as a mark.** The benchmark's neural models drop magnitude at preprocessing and only its ETAS baseline models it | rupture's protocol scores magnitude bins (§ 2 of `EVALUATION_PROTOCOL.md`) and runs an M-test. A model that discards magnitude cannot produce the required forecast at all |
| **One global time origin**, not the benchmark's per-split re-zeroing | rupture's leakage assertions compare absolute origin times against a cutoff. Re-zeroing per split would make "before the cutoff" a per-split notion, which is precisely the ambiguity ADR-0022 exists to remove |
| **Full-history conditioning**, not a 20-event lookback | the benchmark gives ETAS the whole history and gives some of its neural models twenty prior events (and one of them none at all), then flags the asymmetry as a limitation. Giving both models the same history is the only way the paired test means anything |
| **Fitted on training only**; the benchmark fits its ETAS baseline on training plus validation | validation here is used for hyperparameter selection under ADR-0022 decision 4, and folding it into the fit would put the selection and the fit on the same data |
| **30-day protocol horizon**, not rolling 24-hour forecasts | fixed by `EVALUATION_PROTOCOL.md` § 3 before any model existed |
| **No standardisation of spatial coordinates** | coordinates stay in kilometres, so the benchmark's `log det Σ` correction for NSTPP's standardised spatial likelihood does not arise. Only the two MLP input features are standardised |
| Monte Carlo **simulation counts differ** (100–200 continuations here against their 10 000) | a CPU budget; the effect is Monte Carlo noise in the triggered component, stated rather than hidden |

## 3. Data actually used — read this before any score

`data/catalogs/<region>/` is DVC-tracked and **was not present in this worktree**. `data/raw/` and
`data/interim/` were likewise empty of catalogue content. No regional catalogue for
`california`, `nepal-himalaya` or `turkiye-eaf` was available, and none was fabricated.

Everything below was therefore fitted and scored on the **committed real fixture**:

| | |
|---|---|
| File | `tests/fixtures/forecasting/comcat-california-2018-2019-m3.geojson` |
| Source | USGS ComCat (public domain), retrieved and checksummed in `tests/fixtures/forecasting/provenance.json` |
| Extent | 2018-01-01 to 2019-12-28, M ≥ 3.0, rectangle −122…−114 °E, 32…37.5 °N, depth ≤ 30 km |
| Events | 1 433 earthquakes (no other event types) |
| Region record | `california-fixture` — a test rectangle, **not** one of the three protocol regions |
| Target threshold | M ≥ 3.95 (the RELM convention), 0.1-wide bins to 8.95 |
| Mc | 3.0, the fixture's ComCat query floor, passed explicitly. **Not a fitted Mc** |
| Magnitudes | reported ComCat preferred magnitudes used as Mw (`reported-as-mw:<type>`), the fixture loader's documented approximation |
| Grid | 4 400 cells at 0.1°, 51 magnitude bins — the protocol's construction, on the fixture polygon |

What this substitution costs, stated plainly:

- **The protocol's hard cutoff of 2022-01-01 could not be used.** The fixture ends in 2019. The
  cutoff used is **2019-07-01**, chosen because a committed ETAS fit of the same slice at the same
  cutoff already exists (`tests/fixtures/forecasting/fit-2019-07-01/`), so the challenger and the
  baseline are fitted on identical events.
- **214 training events** (M ≥ 3.0, in region, before the cutoff), of which 184 fall in the scored
  window after a three-month auxiliary period. That is a very small training set for a learned
  model, and it is the single most important caveat on everything that follows.
- **Six 30-day windows**, 2019-07-01 to 2019-12-28. The promotion rule requires twelve.
- **One region**, and not a protocol region. The rule requires two of three.
- The test period is dominated by one sequence: the 2019 Ridgecrest M6.4/M7.1 doublet, three days
  after the cutoff. 123 of the 130 target events fall in the first window.

None of these can be worked around from this worktree. They mean the run below is a **working
demonstration of the machinery on real data**, not a protocol result, and the architect should
treat it as such when assembling `reports/CHALLENGER_EVALUATION.md`.

## 4. Hyperparameter protocol

Exactly as ADR-0022 decision 4 requires, and the record is the evidence.

- Candidate grid: 16 configurations — `hidden ∈ {8, 16}`, `n_time_basis ∈ {4, 8}`,
  `background_sigma_km ∈ {5, 15}`, `weight_decay ∈ {0, 10⁻³}`. Small on purpose: with a few
  hundred training events a wide search buys variance, and every extra trial is another chance to
  launder a lucky fold into a "chosen" configuration.
- Folds: 2 blocked time-forward folds over 2018-01-01 → 2019-07-01, from
  `rupture.models.data.blocked_splits`. Every validation index is strictly later than every
  training index; the splitter API has no shuffle parameter and the module imports no random
  number generator.
- Score: event-weighted out-of-sample negative log-likelihood per validation event.
- `select_config` **raises** if the validation window ends after the hard cutoff.
- Chosen: `n_time_basis = 8`, `n_space_basis = 5`, `hidden = 8`, `background_sigma_km = 15`,
  `weight_decay = 10⁻³`, `learning_rate = 0.05`, config hash `88da7548124f`. Written to
  `hyperparameters.json` with every trial's score **before** any test window was scored.

## 5. The fit

Fitted by maximum likelihood on 214 events with `origin_time < 2019-07-01T00:00:00Z`; 184 of them
scored, the rest auxiliary. Converged in 1 105 epochs, 19.5 s on one CPU core.

| Quantity | `ntpp-neural-hawkes` | `etas-mizrahi` (same events, same cutoff) |
|---|---|---|
| Training events | 214 | 214 |
| Background rate | `log₁₀ μ` ≈ −0.60 per day over the region | `log₁₀ μ` = −6.41 per km² per day |
| Productivity exponent | `alpha` = 0.238 | `a` = 1.350 |
| Expected offspring at M3 / M5 / M7 | 0.90 / 1.44 / 2.32 | — (different parameterisation) |
| Gutenberg-Richter `b` | 0.967 | 1.020 |
| **Branching ratio** | **1.002** | **0.643** |
| Training log-likelihood per event | `nll` 10.584 (`tll` −1.538, `sll` −9.047, mark −0.201) | not exposed by the `etas` package |
| Parameter snapshot | `d3b1019770dc` | `9e9325406a90` |

Both `b`-values are plausible for California. The productivity exponent is not: 0.238 against
ETAS's 1.350 means the fitted model barely distinguishes an M3 from an M7 as a trigger. The
branching ratio is worse, and is the finding of this section.

## 6. Results against ETAS

Six 30-day windows from 2019-07-01, both models issued from the same history at each issue time,
scored by the same `PyCSEPEvaluator` on the same target slices, 1 000 simulations per test,
α = 0.05, seed 20190701, no refits.

### Pass rates (windows passed / windows scored)

| Test | `ntpp-neural-hawkes` | `etas-mizrahi` | Denominator rule |
|---|---|---|---|
| N | 4/6 (0.67) | 2/6 (0.33) | all evaluated windows |
| M | 6/6 (1.00) | 6/6 (1.00) | windows with ≥ 1 target event |
| S | 3/6 (0.50) | 3/6 (0.50) | ″ |
| L | 5/6 (0.83) | 5/6 (0.83) | ″ |
| CL | 5/6 (0.83) | 3/6 (0.50) | ″ |

A pass means *not rejected at α*. It is not evidence of skill. With six windows the standard error
on any of these rates is about 0.2, so none of the differences is distinguishable from noise.

### Per window

| Issue | Targets | NTPP expected | ETAS expected | NTPP N/M/S/L/CL | T-test | W-test |
|---|---|---|---|---|---|---|
| 2019-07-01 | 123 | 1.19 | 1.17 | ✗ ✓ ✗ ✗ ✗ | **+1.68**, pass | −9.43, fail |
| 2019-07-31 | 2 | 7.37 | 13.46 | ✗ ✓ ✓ ✓ ✓ | **+2.60**, pass | −1.34, fail |
| 2019-08-30 | 1 | 5.23 | 8.54 | ✓ ✓ ✗ ✓ ✓ | +7.17, undefined | −1.00, fail |
| 2019-09-29 | 1 | 4.27 | 6.35 | ✓ ✓ ✓ ✓ ✓ | +1.49, undefined | −1.00, fail |
| 2019-10-29 | 1 | 3.74 | 4.93 | ✓ ✓ ✗ ✓ ✓ | +2.31, undefined | −1.00, fail |
| 2019-11-28 | 2 | 3.31 | 4.37 | ✓ ✓ ✓ ✓ ✓ | −0.55, fail | −0.45, fail |

The T-test is *undefined* in three windows because pycsep's paired t statistic needs more than one
target event; those windows are recorded as undefined, never as a pass.

### The paired comparison

- Windows where the T-test is defined: **3**. Won by the challenger: **2**.
- Mean information gain per event across those windows: **+1.246 nats**.
- Windows where the W-test is defined: **6**. Won by the challenger: **0**.
- **T/W disagreements: 2**, and the protocol says to flag them. This one matters.

The T-test compares *mean* per-event log-rate; the W-test is a signed-rank test on the same
per-event differences, so it follows the *median*. In the Ridgecrest window the challenger wins on
the mean (+1.68) and loses heavily on the median (z = −9.43 over 123 events). Read together, that
says the challenger placed a minority of events much better than ETAS and the majority of them
worse. A mean-based reading of that window alone would have been the single most misleading number
available, and it is exactly the number a careless summary would quote.

### Promotion verdict

**Not promoted**, and the machinery says so mechanically (`promotion_verdict`):

1. **Condition 1 (pass rates ≥ ETAS over ≥ 12 consecutive windows): fails.** Only 6 windows were
   scored. The rates themselves are at or above ETAS's on all five tests, but the window count
   alone is disqualifying.
2. **Condition 2 (beats ETAS in the paired T-test with positive information gain): not
   demonstrated.** The T-test is defined in three windows out of six; the W-test contradicts it in
   both windows where both are defined and the challenger "wins".
3. **Condition 3 (holds in ≥ 2 of 3 regions): fails.** One region was available, and it is not one
   of the three protocol regions.

There is no route to promotion from this evidence and none is claimed.

## 7. What went wrong, honestly

**The fitted process is critical.** Branching ratio 1.002 against ETAS's 0.643. Every event
triggers, on average, one further event; the cascade does not die out on its own. Two hundred
events, most of them from one swarm, is not enough to constrain `k0` and `alpha` separately, and
the likelihood is happy to trade a low magnitude sensitivity (`alpha` = 0.24) against a high base
productivity (`k0` = 0.90) and sit on the critical boundary. `FitResult.notes` says so on the
record, and the diagnostic is published so a reader does not have to derive it.

That single number explains most of the rest:

- The challenger forecasts *fewer* events than ETAS in every aftershock window (7.4 against 13.5,
  then 5.2 against 8.5, and so on) because its weak magnitude sensitivity under-weights the M7.1
  as a trigger — while its near-critical base rate keeps a long, flat tail going. It passes more
  N-tests than ETAS in this run for the wrong reason: ETAS over-forecast the decay and the
  challenger under-forecast the trigger, and the second error happened to land closer to two
  observed events.
- Both models fail every test in the Ridgecrest window, which is correct. Neither anticipates a
  mainshock, and a model that had passed that window would be evidence of leakage rather than of
  skill.
- The spatial test is where the challenger does not improve on ETAS at all (3/6 each). This is the
  same place EarthquakeNPP finds every neural point process losing, and for a recognisable reason:
  the triggering kernel here is isotropic, and a Ridgecrest aftershock cloud is a lineament.

**What would have to change** for this to be worth rerunning: a real regional catalogue (tens of
thousands of events rather than two hundred), a penalty or reparameterisation keeping the
branching ratio subcritical, and an anisotropic spatial kernel. In that order.

## 8. The leaky ablation

Required by ADR-0022 decision 6, and the whole point of it is to make the discipline's value a
number. **Nothing in this section is a result.** Every artefact carries the model id
`ntpp-LEAKY-ABLATION` in its forecast ids, its run-log records and its report file name.

Two variants, leaking in different places:

- **`tuning_leak`** — the configuration is chosen by scoring all 16 candidates **on the test
  window** instead of on a validation window before the cutoff. The fit still uses only pre-cutoff
  events. This isolates the subtle leak: the one that survives code review because the training
  code looks impeccable.
- **`fit_leak`** — the parameters are fitted on the **whole catalogue**, test period included, and
  then used to "forecast" windows inside the fitting period. The conditioning history at each
  issue time is still strictly before it. This isolates the gross leak, and its size is what an
  unguarded pipeline could have claimed.

<!-- ABLATION-NUMBERS -->

## 9. Limitations

Beyond § 3 (the data) and § 7 (the branching ratio):

- **Isotropic triggering.** No fault geometry, no anisotropy, no finite-rupture extent.
- **Fixed basis exponents.** `p` and `s` are hyperparameters, not learned, because they are badly
  non-identifiable alongside the mixture weights at this sample size.
- **Stationary mark law.** The Gutenberg-Richter `beta` does not vary in time or space, and the
  productivity law is exponential in magnitude by construction.
- **Edge effects ignored in the likelihood.** The spatial kernel's mass outside the region polygon
  is not redistributed. The background law *is* renormalised over the lattice at forecast time, so
  the two are internally consistent, but both are approximate near the boundary.
- **Monte Carlo noise.** 100 continuations per forecast in this run. The background is analytic
  (ADR-0018's convention, adopted verbatim), so no cell has zero rate, but the triggered component
  carries sampling noise in sparsely populated cells.
- **No uncertainty on the parameters.** A single maximum-likelihood point estimate is used; the
  forecast carries Monte Carlo spread but not parameter uncertainty, which on 214 events is the
  larger of the two.
- **Depth is a feature, not a dimension.** The model forecasts on a map.
- **Two-year training span.** Any seasonal or decadal structure is invisible to it, and its
  background law is a kernel density over 214 points.
- **Cascades in simulation are capped** at 50 generations and 200 000 events per simulation. With
  a branching ratio of 1.002 that cap is not decorative; the diagnostics report when it is hit.

## 10. Reproducing this

```
uv run python -m rupture.commands.challenger ntpp select --region <r> \
    --from 2018-01-01T00:00:00Z --validation-end 2019-07-01T00:00:00Z \
    --cutoff 2019-07-01T00:00:00Z
uv run python -m rupture.commands.challenger ntpp fit --region <r> --cutoff 2019-07-01T00:00:00Z
uv run python -m rupture.commands.challenger ntpp schedule --region <r> \
    --from 2019-07-01T00:00:00Z --to 2019-12-28T00:00:00Z --step 30d --horizon 30d
uv run python -m rupture.commands.challenger ntpp ablate --region <r> \
    --from 2019-07-01T00:00:00Z --to 2019-12-28T00:00:00Z \
    --honest-report reports/eval/schedule-<r>-ntpp.json
```

(`rupture challenger ...` once `src/rupture/cli.py` registers the sub-app; see the note at the top
of `src/rupture/commands/challenger.py`.)

One trap worth knowing: `evaluate_forecast` is idempotent per *target slice hash*, and the
evaluation bundle is keyed by the forecast id, which is built from the **model id**. Re-running a
schedule reuses the stored results rather than re-scoring, which is what you want for a rerun and
emphatically not what you want for a variant. Any variant of this model must therefore carry its
own model id — which is why the two ablations are `ntpp-LEAKY-ABLATION-tuning` and
`ntpp-LEAKY-ABLATION-fit` rather than sharing one. A first version of the tuning ablation did
share the honest id, and silently reported the honest results as its own.

Fits are deterministic — torch and numpy are seeded from the configuration — and a rerun
reproduces `parameter_snapshot_hash`. The committed fixture fit under
`tests/fixtures/models/ntpp-fit-2019-07-01/` is regenerated, never hand-edited, by
`uv run python -m tests.fixtures.models.make_ntpp_fixture`.

## References

- Stockman, S., Lawson, D. J. & Werner, M. J. (2026). *EarthquakeNPP: A Benchmark for Earthquake
  Forecasting with Neural Point Processes.* Transactions on Machine Learning Research, March 2026.
  arXiv:2410.08226v3. Code: `github.com/ss15859/EarthquakeNPP` (MIT).
- Mizrahi, L., Nandan, S. & Wiemer, S. (2021). The effect of declustering on the size distribution
  of mainshocks. *SRL*; and the `etas` package (`github.com/lmizrahi/etas`, MIT), rupture's
  baseline (ADR-0009).
- Savran, W. et al. (2022). pyCSEP: A Python toolkit for earthquake forecast developers. *SRL*.
- `docs/EVALUATION_PROTOCOL.md`, `docs/ETAS_BASELINE.md`, `docs/BASELINE_RESULTS.md`,
  ADR-0018, ADR-0022, ADR-0029.
