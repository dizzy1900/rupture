# Challenger C1a — a neural temporal point process

This document reports how one learned model scored
against the ETAS baseline under `EVALUATION_PROTOCOL.md`. It is a record of rate forecasts and
their test outcomes, not a claim about any future event.

**Headline: the challenger is not promoted, in either region it was run on.** On
`nepal-himalaya` it is worse than ETAS on every axis that matters — lower S-, L- and CL-test pass
rates, and a mean information gain of **−0.35 nats per target event**. On `turkiye-eaf` it is
mixed: it passes the N- and S-tests slightly *more* often than ETAS and the L-test clearly less,
and its mean information gain is **+0.39 nats per event** but carried by one window out of the ten
where the paired test is defined, with the W-test losing all 29. Neither region satisfies protocol
§ 10, and `california` could not be fitted at all (see § 3), so condition 3 is unreachable.

The result matches the published prior: EarthquakeNPP benchmarks five neural point processes
against this same ETAS implementation and finds none of them ahead, with the gap concentrated in
the spatial component. That is where this model loses too.

**The number the ablation exists to produce:** fitting the parameters on the whole catalogue —
target windows included — buys **+0.68 nats per target event** on `turkiye-eaf` and **+0.77** on
`nepal-himalaya`. On Nepal that **flips the sign**: a challenger that honestly loses to ETAS by
0.35 nats per event appears to beat it by 0.43, and its S-test pass rate rises from below the
baseline's to well above it. That is what the leakage rules of ADR-0022 are worth here, and it is
enough to have turned this negative result into a positive one. § 7.

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
| productivity `A_i` | `k0 exp(alpha (m_i - mc))`, the ETAS form, **constrained subcritical** (below) | yes, via (branching ratio, magnitude sensitivity) |
| temporal kernel `h_i` | convex mixture of `n_time_basis` modified-Omori densities, characteristic times spaced geometrically over 10⁻³–100 days, exponent `p = 1.15` fixed | **the mixture weights are a neural function of the event's magnitude and depth** |
| spatial kernel `g_i` | convex mixture of `n_space_basis` isotropic power-law densities, characteristic distances 0.5–50 km, exponent `s = 1.5` fixed | **as above** |
| mark law | Gutenberg-Richter, independent of time and place | yes (`beta`) |

The neural part is a two-hidden-layer tanh MLP mapping `(m - mc, depth)` — standardised on
training rows only and clipped to ±3 standard deviations — to two softmax vectors of mixture
weights. A few hundred parameters; it trains in under a minute on one CPU core.

**Why this shape.** Three properties, in order of weight. (1) Every basis element is a normalised
density, so the compensator `∫λ` is a sum of closed forms rather than a quadrature — the
likelihood is the real likelihood, and a model cannot improve its score by getting its own
normalisation wrong. (2) It is CPU-sized. (3) It degenerates towards ETAS, so a negative result is
interpretable: it says the extra flexibility did not pay, not that the optimiser failed. ADR-0029
records the decision and the alternatives.

### Subcriticality is enforced, not hoped for

The productivity law is parameterised by *(branching ratio, magnitude sensitivity)* rather than by
`(k0, alpha)`:

```
alpha = beta * max_alpha_fraction * sigmoid(alpha_raw)   ->  alpha < beta always
n     = max_branching_ratio * sigmoid(branch_raw)        ->  0 < n < 0.98 always
k0    = n * (beta - alpha) / beta
```

`n` is the branching ratio: expected direct offspring per event, integrated over the mark law
(`k0 beta / (beta - alpha)`). The diagnostics recompute it from the published scalars, so the
constraint is checked rather than asserted.

This was not a free choice. Fitted **without** the constraint, maximum likelihood drove the model
supercritical on every catalogue tried — 1.00 on a two-year California fixture, 0.96 on Nepal, and
**1.83** on Türkiye, where `alpha` had reached within nine percent of `beta` and the productivity
integral was close to diverging. A supercritical Hawkes process has cascades that never die out
and forecasts that are not merely wrong but unstable. Every operational ETAS implementation
constrains its parameters for this reason; the `etas` package has explicit inversion ranges. The
decision was made on the **training-set** branching ratio, before any test window was scored.

Worth recording alongside it: **the ETAS baseline's own `turkiye-eaf` fit has a branching ratio of
1.044**, with `a = 2.266` against `beta = 2.090` — supercritical, and not flagged by the package's
own bounds, which the fit sits inside. Near-critical fits are a property of these catalogues and
of maximum likelihood on them, not a defect peculiar to the challenger. On `nepal-himalaya` the
baseline is comfortably subcritical at 0.689.

**What is deliberately not neural.** An earlier version let the MLP add a bounded offset to
productivity. On a few hundred events that produced a productivity curve oscillating by a factor
of fifty between neighbouring half-magnitude steps, and it made `alpha` non-identifiable because
the offset was itself a function of magnitude. Bounding the neural part to the kernel *shape* — a
softmax over densities, so any output is still a proper density — keeps the model honest where it
extrapolates. Since the test period for both regions contains a mainshock larger than anything in
training, that was not a hypothetical concern.

## 2. EarthquakeNPP conventions

Conventions follow the EarthquakeNPP benchmark (Stockman, Lawson & Werner, *TMLR*, March 2026;
`ss15859/EarthquakeNPP`, MIT; arXiv:2410.08226v3) where they apply, so the numbers here sit in the
same frame as its published baselines. Its headline finding — that none of the five neural point
processes it benchmarks outperforms ETAS, with the gap almost entirely spatial — is the prior this
work was undertaken against.

### Adopted

| Convention | As used here |
|---|---|
| Time in **float days** from a fixed origin | `EventSequence.t`; the unit the `etas` package uses |
| Locations in **projected kilometres**, not degrees | azimuthal equidistant projection about the region's bounding-box centre. Their `Datasets/README.md` directs point-process models to the projected `x, y` because ETAS works in great-circle kilometres |
| Hard magnitude cut, **no censored likelihood** below Mc | events below Mc are removed by an explicit filter before any tensor is built |
| Split boundaries are **calendar dates**, not fractions | `auxiliary_start → train_start → validation_start → test_start → test_end` |
| An explicit **auxiliary (burn-in) window** whose events condition the intensity but are not scored | `auxiliary_years = 2.0`, the same value the ETAS baseline fits used |
| Log-likelihood reported **per test event**, split into temporal (`tll`) and spatial (`sll`) parts, `nll = -(tll + sll)` | `LogLikelihood` in `models/challengers/ntpp/model.py` |
| Information gain as a difference in mean log-likelihood per event | via the pycsep paired T-test against ETAS |
| CSEP-style consistency tests alongside the likelihood | N/M/S/L/CL through the existing `PyCSEPEvaluator` |

### What is *not* comparable, and it matters

**No number in this document can be placed beside a published EarthquakeNPP table.** The
conventions above put the two in the same *frame*; they do not make the numbers commensurable, and
saying otherwise would be the more flattering error. Three reasons, any one of which is
sufficient:

1. **Different catalogues.** The benchmark's seven datasets are all Californian (ComCat_25,
   SCEDC_20/25, White, SaltonSea, SanJac, WHITE_06). rupture fitted `turkiye-eaf` and
   `nepal-himalaya`, and **California was never fitted** (§ 8 and `reports/MODEL_CARD_ntpp.md`
   say why: the likelihood is quadratic in event count and California's training slice holds
   55,828 events). There is no shared test set anywhere.
2. **Different test windows and thresholds**, because the split dates and Mc are the benchmark's
   per-dataset ones, and rupture's are `EVALUATION_PROTOCOL.md` § 1's.
3. **Different quantities.** Their tables are per-event `nll`, `tll` and `sll` over a rolling
   24-hour horizon; the promotion rule here scores 30-day windows.

What *is* comparable is the qualitative finding, and it agrees: the challenger loses to ETAS, and
it loses on the spatial component (§ 6). That is a replication of the benchmark's conclusion on
different data, not a placement in its league table. Producing one number that could sit in that
table would mean running one of their Californian configurations, which is recorded as an
open gap rather than approximated.

### Departed from, and why

| Departure | Reason |
|---|---|
| **Magnitude is modelled as a mark.** The benchmark's neural models drop magnitude at preprocessing; only its ETAS baseline models it | rupture's protocol scores magnitude bins (§ 2) and runs an M-test. A model that discards magnitude cannot produce the required forecast at all |
| **One global time origin**, not per-split re-zeroing | rupture's leakage assertions compare absolute origin times against a cutoff. Re-zeroing per split would make "before the cutoff" a per-split notion — precisely the ambiguity ADR-0022 exists to remove |
| **Full-history conditioning**, not a 20-event lookback | the benchmark gives ETAS the whole history and some of its neural models twenty prior events (one of them none at all), then flags the asymmetry as a limitation. Giving both models the same history is the only way a paired test means anything |
| **Fitted on training only**; the benchmark fits its ETAS baseline on training plus validation | validation here selects hyperparameters under ADR-0022 decision 4; folding it into the fit would put the selection and the fit on the same data |
| **30-day protocol horizon**, not rolling 24-hour forecasts | fixed by `EVALUATION_PROTOCOL.md` § 3 before any model existed |
| **No standardisation of spatial coordinates** | coordinates stay in kilometres, so the benchmark's `log det Σ` correction for NSTPP's standardised spatial likelihood does not arise. Only the two MLP input features are standardised |
| **100 Monte Carlo continuations** per forecast, against their 10 000 | a CPU budget, applied identically to both models. It is Monte Carlo noise in the triggered component, stated rather than hidden |

## 3. Data

Two of the three protocol regions, on the real homogenised catalogues built by
`rupture catalog build`, at the protocol's own hard cutoff.

| | `turkiye-eaf` | `nepal-himalaya` |
|---|---|---|
| Catalogue | `data/catalogs/turkiye-eaf` | `data/catalogs/nepal-himalaya` |
| Events | 7 038 | 2 728 |
| Span | 1976-01-07 → 2026-07-23 | 1976-05-10 → 2026-07-21 |
| Mc (fitted, from the region record) | 4.3 | 4.4 |
| Target threshold | M ≥ 4.6 | M ≥ 4.7 |
| Training events (`origin_time < 2022-01-01`, M ≥ Mc, in region) | 405 | 772 |
| Grid cells / magnitude bins | 1 409 / 44 | 2 079 / 43 |

`california` was **not run**: 55 828 training events at Mc 2.7, and this model's likelihood is
O(targets × sources) per epoch, so a fit is roughly three orders of magnitude more work than
Türkiye's. That is a limitation of this implementation, stated rather than worked around; the
protocol's two-of-three-regions rule therefore cannot be satisfied even in principle here.

The catalogues are DVC-tracked and were absent from this worktree at the start; they were copied
in from the repository's own checkout, unmodified, and their `catalog_event_hash` is recorded in
every schedule report so a reader can confirm the challenger and the baseline scored the same
catalogue build. No data was synthesised.

The ETAS fits used as the benchmark are the **published baseline fits**
(`baselines/etas/<region>/fit_result.json`, cutoff `2022-01-01`, the ones behind
`docs/BASELINE_RESULTS.md`), loaded unmodified. Both models therefore see the same events before
the cutoff and the same history at every issue time.

## 4. Hyperparameter protocol

ADR-0022 decision 4, with the frozen record as the evidence.

- **Grid: 4 candidates** — `hidden ∈ {8, 16}` × `weight_decay ∈ {0, 10⁻³}`, which is
  `DEFAULT_GRID` in `models/challengers/ntpp/train.py`. Deliberately small: a fold fit on these
  catalogues costs a minute or more, and a wide search on a few hundred training events buys
  variance rather than skill. Every extra trial is another chance to launder a lucky fold into a
  "chosen" configuration. `DEFAULT_GRID` previously described a sixteen-candidate space that no
  committed record could have come from, so re-running `select` would have searched somewhere else
  than the frozen configuration came from; the grid in the code is now the grid that ran, the
  frozen record carries a `grid` key saying what was searched, and `make validate-challengers`
  fails if the committed search code cannot reproduce the committed record's candidates.
- **Folds: 2 blocked time-forward** splits over the catalogue start → 2022-01-01, from
  `rupture.models.data.blocked_splits`. Every validation index is strictly later than every
  training index; the splitter API has no shuffle parameter and the module imports no random
  number generator.
- **Score:** event-weighted out-of-sample negative log-likelihood per validation event.
- `select_config` **raises** if the validation window ends after the hard cutoff.
- The chosen configuration is written to `baselines/ntpp/<region>/hyperparameters.json` with every
  trial's score, **before** any test window is scored, and `load_frozen` refuses a record whose
  stored hash does not match its stored configuration.

Both regions independently chose the same configuration — `hidden = 16`, `weight_decay = 10⁻³`,
config hash `1ef984d705c3` — which is mild evidence that the choice is not fold noise.

| Region | Fold 0 train / validate | Fold 1 train / validate | Validation events | Best mean NLL | Spread across the 4 candidates |
|---|---|---|---|---|---|
| `turkiye-eaf` | 1976-01 → 1991-05 / 1991-05 → 2006-09 | 1976-01 → 2006-09 / 2006-09 → 2022-01 | 303 | 13.553 | 13.553 – 13.638 |
| `nepal-himalaya` | 1976-05 → 1991-11 / 1991-11 → 2006-10 | 1976-05 → 2006-10 / 2006-10 → 2022-01 | 649 | 12.725 | 12.725 – 12.828 |

Every fold converged and every validation window ends at or before `2022-01-01`. The spread across
candidates is under 0.1 nats per event, i.e. the model is insensitive to the hyperparameters in
this grid — which is worth knowing before reading anything into the choice.

## 5. The fit

Fitted by maximum likelihood on events with `origin_time < 2022-01-01T00:00:00Z`, with a two-year
auxiliary window, on one CPU core.

| | `turkiye-eaf` | `nepal-himalaya` |
|---|---|---|
| Training events / scored | 405 / 389 | 772 / 761 |
| Epochs, runtime | 554, 35 s | 978, 77 s |
| Converged | yes | yes |
| `log mu` (events/day over the region) | −4.329 | −3.953 |
| `k0` (productivity at Mc) | 0.204 | 0.430 |
| `alpha` (magnitude sensitivity) | 1.685 | 1.272 |
| `beta` / `b` | 2.129 / 0.924 | 2.349 / 1.020 |
| **Branching ratio** | **0.978** (pressing the 0.98 ceiling) | **0.936** |
| Training NLL per event | 13.301 (`tll` −3.772, `sll` −9.530, mark −0.270) | 12.473 (`tll` −1.893, `sll` −10.580, mark −0.149) |
| Parameter snapshot | `8d8a21fbe1e3` | `d7b92e66fd6d` |
| **ETAS on the same events**: `a` / `beta` / `b` / branching | 2.266 / 2.090 / 0.907 / **1.044** | 2.458 / 2.355 / 1.023 / 0.689 |

Three things are worth saying out loud.

**The b-values agree with ETAS to two decimal places** in both regions (0.924 vs 0.907; 1.020 vs
1.023), fitted independently from the same events by different estimators. That is a sanity check
passing, not a result, but it is the first thing that would break if the mark likelihood were
wrong.

**The magnitude sensitivity does not agree.** `alpha` comes out at 1.69 and 1.27 against ETAS's
2.27 and 2.46 — the challenger treats a large event as a substantially weaker trigger than ETAS
does. In Türkiye that is partly the subcriticality ceiling biting: `alpha` and the branching ratio
trade against each other, and the fit is pressed against the constraint.

**The Türkiye fit sits at 0.978 against a ceiling of 0.98**, and the fit record says so in its
`notes`. The likelihood wants a near-critical process on this catalogue, and so did ETAS's: the
baseline's own fit is at **1.044**, over the line. Neither model's productivity law is well
identified by 405 events, and this is the honest reading of both.

## 6. Results against ETAS

55 issue times every 30 days from `2022-01-01T00:00:00Z`, horizon 30 days, all 55 scored;
1 000 pycsep simulations per test, α = 0.05, seed 20220101; 100 Monte Carlo continuations per
forecast for **both** models; **no refits for either model** (see § 8). The catalogue build hash
matches the published baseline run exactly in both regions (`80649982ef4a`, `98ed19af7dca`), so
challenger and baseline scored the same events.

### Pass rates (passed / scored)

| Region | Model | N | M | S | L | CL |
|---|---|---|---|---|---|---|
| `turkiye-eaf` | **NTPP** | **53/55** (0.96) | 28/29 (0.97) | **18/29** (0.62) | 23/29 (0.79) | 23/29 (0.79) |
| | ETAS, this run | 50/55 (0.91) | 28/29 (0.97) | 16/29 (0.55) | **27/29** (0.93) | 23/29 (0.79) |
| | *ETAS, published* | *50/55 (0.91)* | *27/29 (0.93)* | *20/29 (0.69)* | *26/29 (0.90)* | *25/29 (0.86)* |
| `nepal-himalaya` | **NTPP** | 50/55 (0.91) | 21/22 (0.95) | 12/22 (0.55) | 15/22 (0.68) | 17/22 (0.77) |
| | ETAS, this run | 50/55 (0.91) | 21/22 (0.95) | **15/22** (0.68) | **16/22** (0.73) | **19/22** (0.86) |
| | *ETAS, published* | *51/55 (0.93)* | *21/22 (0.95)* | *16/22 (0.73)* | *17/22 (0.77)* | *19/22 (0.86)* |

The italic rows are `docs/BASELINE_RESULTS.md`: the same schedule with **yearly refits and 1 000
continuations** instead of none and 100. The gap between the two ETAS rows — up to four windows on
the Türkiye S-test — is the size of that methodological difference, and it is a useful scale
against which to read the challenger-versus-baseline gaps in the same column. A pass means *not
rejected at α*; it is not evidence of skill.

Denominators: 26 of 55 Türkiye windows and 33 of 55 Nepal windows hold no target event and are
recorded as N-test only (protocol § 5), never as passes.

### The paired comparison against ETAS

| | `turkiye-eaf` | `nepal-himalaya` |
|---|---|---|
| Windows where the T-test is defined | 10 | 9 |
| T-test won by the challenger | **1** | **1** |
| Windows with positive information gain | 5 of 10 | 4 of 9 |
| Mean information gain per event | **+0.394 nats** | **−0.346 nats** |
| W-test windows / won | 29 / **0** | 22 / **0** |

The T-test is undefined in most windows because pycsep's paired t statistic needs more than one
target event, and most windows hold zero or one. Those windows are recorded as undefined, never as
a pass.

The Türkiye mean gain is positive and the challenger still loses this condition, which is the
point of reading the counts rather than the mean: **one win in ten windows**, and the W-test — the
signed-rank companion the protocol requires alongside — loses all 29 windows in which it is
defined. The T-test follows the mean per-event log-rate difference and the W-test its median, so
the pair says the challenger placed a minority of events much better than ETAS and the majority
worse. A summary quoting only "+0.39 nats information gain over ETAS" would be true and
thoroughly misleading; it is the number this document exists to not let stand alone.

### The busiest windows

`turkiye-eaf` (expected counts are for the whole grid over 30 days):

| Issue | Targets | NTPP | ETAS | NTPP N/S/L | ETAS N/S/L | T | W |
|---|---|---|---|---|---|---|---|
| 2023-01-26 | 160 | 0.28 | 0.43 | ✗ ✗ ✗ | ✗ ✗ ✗ | −0.05 | −0.81 |
| 2023-02-25 | 12 | 12.76 | 21.25 | ✓ ✗ ✓ | ✗ ✗ ✓ | −0.05 | −0.55 |
| 2023-04-26 | 7 | 3.94 | 8.40 | ✓ ✗ ✓ | ✓ ✓ ✓ | −0.56 | −0.51 |
| 2023-07-25 | 5 | 1.98 | 5.19 | ✓ ✗ ✗ | ✓ ✗ ✓ | +3.15 | −1.75 |
| 2023-11-22 | 3 | 1.31 | 3.89 | ✓ ✗ ✓ | ✓ ✗ ✓ | +0.34 | −1.60 |

`nepal-himalaya`:

| Issue | Targets | NTPP | ETAS | NTPP N/S/L | ETAS N/S/L | T | W |
|---|---|---|---|---|---|---|---|
| 2024-12-16 | 22 | 0.52 | 0.43 | ✗ ✗ ✗ | ✗ ✗ ✗ | +0.06 | −0.60 |
| 2023-09-23 | 7 | 0.47 | 0.52 | ✗ ✗ ✗ | ✗ ✗ ✗ | −0.02 | −1.18 |
| 2025-02-14 | 6 | 1.99 | 2.06 | ✗ ✓ ✗ | ✗ ✓ ✗ | +0.57 | −1.58 |
| 2022-07-30 | 4 | 0.50 | 0.65 | ✗ ✗ ✗ | ✗ ✗ ✗ | −0.23 | −0.37 |
| 2022-10-28 | 4 | 0.42 | 0.64 | ✗ ✓ ✗ | ✗ ✗ ✗ | +0.28 | −1.83 |

The 2023-01-26 Türkiye window is the Kahramanmaraş doublet: 160 target events against 0.28
expected, and every test rejects — for both models. That is the correct result. No time-dependent
seismicity model anticipates a mainshock; a model that passed that window would be evidence of
leakage, not of skill.

What the models do is visible in the windows after it, and the pattern is consistent: **the
challenger forecasts fewer aftershocks than ETAS in every decaying window** (12.8 against 21.2
observed 12; 3.9 against 8.4 observed 7; 2.0 against 5.2 observed 5). Against the observed counts
the challenger's N-test is the better calibrated of the two — which is why it passes N more often —
while ETAS's higher rates place probability better where events actually fall, which is why ETAS
wins L. Lower `alpha` is the mechanism: the challenger under-weights the M7.8 as a trigger.

### Promotion verdict

**Not promoted in either region**, applied mechanically by `promotion_verdict`:

| Condition | `turkiye-eaf` | `nepal-himalaya` |
|---|---|---|
| 1 — N/M/S/L pass rates at or above ETAS over ≥ 12 consecutive windows | **fails**: L 0.79 vs 0.93 | **fails**: S 0.55 vs 0.68, L 0.68 vs 0.73 |
| 2 — beats ETAS in the paired T-test with positive information gain | **fails**: won 1 of 10 windows | **fails**: won 1 of 9, mean gain −0.346 |
| 3 — holds in ≥ 2 of 3 regions | unreachable: `california` was not fitted | unreachable |

Against the **published** ETAS baseline of record rather than this run's matched re-run, condition
1 fails in both regions too — Türkiye on S (0.62 vs 0.69) and L (0.79 vs 0.90), Nepal on N (0.909
vs 0.927) and S (0.55 vs 0.73). The verdict does not depend on which ETAS run is used, and
`make validate-challengers` fails if it ever does.

#### How condition 2 is read, and the reading that changed (ADR-0040)

The table above records the reading in force when the run was made: *positive mean gain **and**
wins in more than half the windows where the per-window test is defined*. That reading was chosen
here because the looser one — any win plus a positive mean — passes Türkiye on one window in ten.

It is **no longer the rule**. The ensemble was being judged under a different reading of the same
sentence (a single paired test pooled over the schedule), and one sentence cannot mean two things
and still be a pre-registered rule. ADR-0040 settled it on the pooled test, for reasons argued
there from the protocol's wording and from statistical power rather than from any outcome — and it
does not change this verdict, because **condition 1 fails in both regions** under either baseline,
which is enough on its own.

What the change does cost here is honesty about what can be recomputed: the committed NTPP
schedule reports record per-window comparisons but not the per-event log rates a pooled test needs,
so **condition 2 is not recomputable from them**. `make validate-challengers` prints that in as
many words rather than assuming either answer. `run_ntpp_schedule` now records the pooling terms,
so the next run of the command in § 10 is decidable; the committed
`promotion-<region>-ntpp.json` files are left as the pre-ADR-0040 record of what was run.

## 7. The leaky ablation

Required by ADR-0022 decision 6, and the point of it is to make the discipline's value a number.
**Nothing in this section is a result.** Every artefact carries a leaky model id in its forecast
ids, its run-log records and its report file name, and no leaky fit is written to `baselines/`.

Two variants, leaking in different places:

- **`tuning_leak`** (`ntpp-LEAKY-ABLATION-tuning`) — the configuration is chosen by scoring all
  candidates **on the test window** instead of on a validation window before the cutoff. The fit
  still uses only pre-cutoff events. This isolates the subtle leak: the one that survives code
  review because the training code looks impeccable.
- **`fit_leak`** (`ntpp-LEAKY-ABLATION-fit`) — the parameters are fitted on the **whole
  catalogue**, test period included, and then used to "forecast" windows inside the fitting
  period. The conditioning history at each issue time is still strictly before it. This isolates
  the gross leak, and its size is what an unguarded pipeline could have claimed.

Both are compared against the **identical** ETAS grids the honest run produced (the benchmark grid
cache), so a reported difference carries the leak and not the benchmark's Monte Carlo noise.

### What the leaks bought

`turkiye-eaf` (55 windows, 219 target events):

| | honest | `tuning_leak` | `fit_leak` |
|---|---|---|---|
| Training events | 405 (< 2022-01-01) | 405 (< 2022-01-01) | **871** (whole catalogue) |
| Configuration | `1ef984d705c3` (validation) | `e3f156486823` (**test window**) | `1ef984d705c3` |
| **Mean information gain per event vs ETAS** | **+0.394** | **+0.430** (+0.037) | **+1.074** (**+0.681**) |
| Windows with positive gain (of 10) | 5 | 6 | 8 |
| T-test wins (of 10) / W-test wins (of 29) | 1 / 0 | 2 / 0 | 2 / 0 |
| N | 53/55 | 54/55 (+0.02) | 54/55 (+0.02) |
| M | 28/29 | 28/29 (0.00) | 27/29 (−0.03) |
| S | 18/29 | 18/29 (0.00) | 16/29 (−0.07) |
| L | 23/29 | 21/29 (−0.07) | 25/29 (+0.07) |
| CL | 23/29 | 20/29 (−0.10) | 22/29 (−0.03) |

`nepal-himalaya` (55 windows, 66 target events):

| | honest | `tuning_leak` | `fit_leak` |
|---|---|---|---|
| Training events | 772 (< 2022-01-01) | 772 (< 2022-01-01) | **942** (whole catalogue) |
| Configuration | `1ef984d705c3` (validation) | `9c03e31f2015` (**test window**) | `1ef984d705c3` |
| **Mean information gain per event vs ETAS** | **−0.346** | **−0.195** (+0.151) | **+0.429** (**+0.774**) |
| Windows with positive gain (of 9) | 4 | 5 | 7 |
| T-test wins (of 9) / W-test wins (of 22) | 1 / 0 | 1 / 0 | 3 / 0 |
| N | 50/55 | 50/55 (0.00) | 50/55 (0.00) |
| M | 21/22 | 21/22 (0.00) | 21/22 (0.00) |
| S | 12/22 | 15/22 (+0.14) | **18/22** (+0.27) |
| L | 15/22 | 15/22 (0.00) | 16/22 (+0.05) |
| CL | 17/22 | 18/22 (+0.05) | 19/22 (+0.09) |

**The headline is +0.68 and +0.77 nats per target event**, and on Nepal it flips the sign of the
result. The honest challenger loses to ETAS there by 0.35 nats per event; having seen the target
windows it appears to beat ETAS by 0.43, wins three T-test windows instead of one, and lifts its
S-test pass rate from 12/22 — clearly below the baseline's 15/22 — to **18/22, clearly above it**.
Condition 1 of the promotion rule would have been satisfied on S, L and CL, and only the W-test
would still have dissented. This is not a subtle degradation of a negative result; it is a
different conclusion.

Three further things are worth more than the numbers themselves.

**On the busier region the leak hides in the likelihood, not in the pass rates.** On Türkiye the
gross leak moves N up by one window, L by two, and S, M and CL each down by one — nothing a
reviewer checking "does it pass the CSEP tests more often?" would notice — while nearly tripling
the information gain. On Nepal it shows up in both. Where the leak becomes visible depends on the
region, so neither view is a sufficient check on its own.

**The subtle leak is not negligible, and its size depends on how much there is to exploit.** On
Türkiye it bought +0.037 nats and made three pass rates worse; on Nepal it bought +0.151 nats and
three percentage points of S-test pass rate. Both used the same four-point grid over a model whose
validation candidates differ by under 0.1 nats per event (§ 4), which is about as little room to
overfit as a tuning leak can have. On a wider search over a more flexible model it would buy more.
The honest reading of the Türkiye row is "the discipline cost little here because the search was
small", not "tuning leaks do not matter".

**The gross leak still does not clear the promotion bar on Türkiye.** Even having seen every
target event the leaky variant wins 2 of 10 T-test windows, loses all 29 W-test windows, and its
S-test pass rate falls. On Nepal it would have cleared condition 1 and half of condition 2. The
difference between "the leak was not enough" and "the leak was decisive" turned on the region, not
on anything about the model — which is the argument for running the ablation per region rather
than once.

## 8. Limitations

- **Isotropic triggering.** No fault geometry, no anisotropy, no finite-rupture extent. This is
  the most likely reason for the spatial scores, and it is where EarthquakeNPP finds every neural
  point process losing to ETAS too.
- **`california` was not run** (see § 3). The protocol's two-of-three-regions condition is
  therefore unreachable from this evidence.
- **No refits.** The protocol allows yearly refits at declared boundaries and the published ETAS
  baseline used four per region. This run refits **neither** model, so the comparison is
  symmetric; refitting the challenger and not the benchmark would have biased it in the
  challenger's favour. The consequence is that these ETAS pass rates are not the published ones,
  and both are given below.
- **Fixed basis exponents.** `p` and `s` are hyperparameters, not learned, because they are badly
  non-identifiable alongside the mixture weights at this sample size.
- **Stationary mark law.** `beta` does not vary in time or space; productivity is exponential in
  magnitude by construction.
- **Edge effects ignored in the likelihood.** The spatial kernel's mass outside the region polygon
  is not redistributed. The background law *is* renormalised over the lattice at forecast time, so
  the two are internally consistent, but both are approximate near the boundary.
- **Monte Carlo noise.** 100 continuations per forecast, for both models. The background is
  analytic (ADR-0018's convention, adopted verbatim), so no cell has zero rate and no likelihood
  is undefined, but the triggered component carries sampling noise in sparse cells.
- **No parameter uncertainty.** A single maximum-likelihood point estimate; the forecast carries
  Monte Carlo spread but not parameter uncertainty, which on a few hundred events is the larger of
  the two.
- **Depth is a feature, not a dimension.** The model forecasts on a map.
- **The likelihood is O(targets × sources).** Fine to a few thousand events, hopeless at 10⁵.

## 9. The evidence, as files

Committed under `reports/protocol/<region>/eval/` alongside the baseline's own schedule report:

| File | What it is |
|---|---|
| `schedule-<region>-ntpp.json` | the honest run: every window's tests, the benchmark's tests on the same slices, the paired comparison, the pass rates, the leakage checks, the catalogue build hash |
| `schedule-<region>-ntpp-ABLATION-tuning-leak.json` | the tuning ablation, **not a result** |
| `schedule-<region>-ntpp-ABLATION-fit-leak.json` | the fit ablation, **not a result** |
| `ablations-<region>-ntpp.json` | the two ablations' deltas against the honest run |
| `promotion-<region>-ntpp.json` | § 10 applied mechanically, with the reasons |
| `schedule-<region>-etas-mizrahi.json` | the published ETAS baseline (yearly refits, 1 000 continuations) — the forecast-engineer's file, unmodified |

The fit itself is written to `baselines/ntpp/<region>/` (`fit_result.json`, `parameters.json`,
`diagnostics.json`, `weights.json` as plain lists, plus `hyperparameters.json` — the frozen
selection record) and archived per cutoff under `fits/<cutoff>/`, mirroring the ETAS layout.

**One inconsistency for the architect to settle.** `.gitignore` excludes `/baselines/etas/`, so
the ETAS fits are DVC-tracked and not in git. `/baselines/ntpp/` has no such line, so these fits
*are* committed — 304 KB of JSON, no pickles, and the weights are plain lists. Either treat that
as the better default and leave it, or add `/baselines/ntpp/` to `.gitignore` and `git rm --cached`
them; `.gitignore` is a shared root file and was not this agent's to edit. Nothing in this document
depends on the choice: every parameter it cites is printed here, and a fit is deterministic from
the committed catalogue build and the frozen configuration.

## 10. Reproducing this

```
uv run python -m rupture.commands.challenger ntpp select --region <r> \
    --from <catalogue start> --validation-end 2022-01-01T00:00:00Z \
    --cutoff 2022-01-01T00:00:00Z --auxiliary-years 2.0
uv run python -m rupture.commands.challenger ntpp fit --region <r> \
    --cutoff 2022-01-01T00:00:00Z --auxiliary-years 2.0
uv run python -m rupture.commands.challenger ntpp schedule --region <r> \
    --from 2022-01-01T00:00:00Z --to 2026-08-01T00:00:00Z --step 30d --horizon 30d \
    --simulations 100 --eval-simulations 1000 --reports-dir reports/protocol/<r>
uv run python -m rupture.commands.challenger ntpp ablate --region <r> \
    --from 2022-01-01T00:00:00Z --to 2026-08-01T00:00:00Z \
    --simulations 100 --eval-simulations 1000 --reports-dir reports/protocol/<r> \
    --honest-report reports/protocol/<r>/eval/schedule-<r>-ntpp.json
```

(`rupture challenger ...` once `src/rupture/cli.py` registers the sub-app; see the note at the top
of `src/rupture/commands/challenger.py`.)

The options are the ones the committed evidence was produced with, and three of them used not to
be reachable from these verbs at all:

- `--reports-dir reports/protocol/<r>` puts the schedule JSON where the committed one is. The
  default would write `reports/eval/`.
- `--simulations 100` is what was run — a CPU budget, applied to the challenger and to the ETAS
  benchmark alike (`--benchmark-simulations` defaults to it, and a differing budget would make
  the paired comparison asymmetric).
- `--evaluate-benchmark` is **on by default** and is what produces the `benchmark_pass_rates`
  block the committed reports carry. Condition 1 of the promotion rule is a comparison of pass
  rates; without that block there is nothing to compare against from the same run. It was
  previously not passed by the verb at all, so re-running the documented command produced a
  report shaped differently from the committed one — the gap this section now closes.
- `ablate` now loads the ETAS baseline itself, shares one benchmark cache between the two leaky
  runs, and writes `reports/protocol/<r>/eval/ablations-<r>-ntpp.json` in the shape that is
  committed. Without the benchmark the ablation has no `information_gain_vs_etas` to report, which
  is most of what an ablation is for.

A caveat that belongs here rather than in a footnote: the ETAS rows *inside* the NTPP reports are
this matched 100-continuation re-run, not the published baseline of record (yearly refits, 1000
continuations) in `docs/BASELINE_RESULTS.md`. `make validate-challengers` recomputes condition 1
under **both** and fails if they disagree; on the committed evidence they do not — the challenger
falls short of ETAS under either (ADR-0040 decision 6).

One trap worth knowing: `evaluate_forecast` is idempotent per *target slice hash*, and the
evaluation bundle is keyed by the forecast id, which is built from the **model id**. Re-running a
schedule reuses stored results rather than re-scoring — what you want for a rerun, and emphatically
not what you want for a variant. Any variant must therefore carry its own model id, which is why
the two ablations are `ntpp-LEAKY-ABLATION-tuning` and `ntpp-LEAKY-ABLATION-fit` rather than
sharing one. A first version of the tuning ablation shared the honest id and silently reported the
honest results as its own.

Fits are deterministic — torch and numpy are seeded from the configuration — and a rerun
reproduces `parameter_snapshot_hash`. The committed fixture fit under
`tests/fixtures/models/ntpp-fit-2019-07-01/` (a real fit of the committed ComCat California slice,
used so unit tests never train) is regenerated, never hand-edited, by
`uv run python -m tests.fixtures.models.make_ntpp_fixture`.

## 11. References

- Stockman, S., Lawson, D. J. & Werner, M. J. (2026). *EarthquakeNPP: A Benchmark for Earthquake
  Forecasting with Neural Point Processes.* Transactions on Machine Learning Research, March 2026.
  arXiv:2410.08226v3. Code: `github.com/ss15859/EarthquakeNPP` (MIT).
- Mizrahi, L., Nandan, S. & Wiemer, S. (2021). *SRL/JGR*; and the `etas` package
  (`github.com/lmizrahi/etas`, MIT), rupture's baseline (ADR-0009).
- Savran, W. et al. (2022). pyCSEP: A Python toolkit for earthquake forecast developers. *SRL*.
- `docs/EVALUATION_PROTOCOL.md`, `docs/ETAS_BASELINE.md`, `docs/BASELINE_RESULTS.md`,
  ADR-0018, ADR-0022, ADR-0029.
