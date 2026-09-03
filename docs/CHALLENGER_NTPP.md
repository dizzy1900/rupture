# Challenger C1a — a neural temporal point process

**rupture does not predict earthquakes.** This document reports how one learned model scored
against the ETAS baseline under `EVALUATION_PROTOCOL.md`. It is a record of rate forecasts and
their test outcomes, not a claim about any future event.

**Headline: the challenger is not promoted.** <!-- HEADLINE -->

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

- **Grid: 4 candidates** — `hidden ∈ {8, 16}` × `weight_decay ∈ {0, 10⁻³}`. Deliberately small: a
  fold fit on these catalogues costs a minute or more, and a wide search on a few hundred training
  events buys variance rather than skill. Every extra trial is another chance to launder a lucky
  fold into a "chosen" configuration.
- **Folds: 2 blocked time-forward** splits over the catalogue start → 2022-01-01, from
  `rupture.models.data.blocked_splits`. Every validation index is strictly later than every
  training index; the splitter API has no shuffle parameter and the module imports no random
  number generator.
- **Score:** event-weighted out-of-sample negative log-likelihood per validation event.
- `select_config` **raises** if the validation window ends after the hard cutoff.
- The chosen configuration is written to `baselines/ntpp/<region>/hyperparameters.json` with every
  trial's score, **before** any test window is scored, and `load_frozen` refuses a record whose
  stored hash does not match its stored configuration.

<!-- SELECTION -->

## 5. The fit

<!-- FIT -->

## 6. Results against ETAS

<!-- RESULTS -->

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

<!-- ABLATION -->

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

## 9. Reproducing this

```
uv run python -m rupture.commands.challenger ntpp select --region <r> \
    --from <catalogue start> --validation-end 2022-01-01T00:00:00Z \
    --cutoff 2022-01-01T00:00:00Z --auxiliary-years 2.0
uv run python -m rupture.commands.challenger ntpp fit --region <r> \
    --cutoff 2022-01-01T00:00:00Z --auxiliary-years 2.0
uv run python -m rupture.commands.challenger ntpp schedule --region <r> \
    --from 2022-01-01T00:00:00Z --to 2026-08-01T00:00:00Z --step 30d --horizon 30d
uv run python -m rupture.commands.challenger ntpp ablate --region <r> \
    --from 2022-01-01T00:00:00Z --to 2026-08-01T00:00:00Z \
    --honest-report reports/eval/schedule-<r>-ntpp.json
```

(`rupture challenger ...` once `src/rupture/cli.py` registers the sub-app; see the note at the top
of `src/rupture/commands/challenger.py`.)

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

## References

- Stockman, S., Lawson, D. J. & Werner, M. J. (2026). *EarthquakeNPP: A Benchmark for Earthquake
  Forecasting with Neural Point Processes.* Transactions on Machine Learning Research, March 2026.
  arXiv:2410.08226v3. Code: `github.com/ss15859/EarthquakeNPP` (MIT).
- Mizrahi, L., Nandan, S. & Wiemer, S. (2021). *SRL/JGR*; and the `etas` package
  (`github.com/lmizrahi/etas`, MIT), rupture's baseline (ADR-0009).
- Savran, W. et al. (2022). pyCSEP: A Python toolkit for earthquake forecast developers. *SRL*.
- `docs/EVALUATION_PROTOCOL.md`, `docs/ETAS_BASELINE.md`, `docs/BASELINE_RESULTS.md`,
  ADR-0018, ADR-0022, ADR-0029.
