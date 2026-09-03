# C1b — the gridded spatio-temporal challenger

**rupture does not predict earthquakes.** This model issues expected counts of events per cell per
magnitude bin over a horizon, on the same lattice and the same magnitude bins as the ETAS
baseline, and it is scored under the protocol fixed in `EVALUATION_PROTOCOL.md` before any model
in this repository was fitted.

Design rationale is ADR-0031. This document says what was built, what it was trained and scored
on, how the hyperparameters were chosen, what it scored, and what it cannot do.

## 1. Architecture

One ConvLSTM layer (Shi et al. 2015) over a sequence of rasterised lookback frames, then a
two-layer convolutional head, then a **zero-initialised** output convolution whose result is
*added* to a climatological log-rate:

```
log lambda(cell) = log_prior(cell) + log_scale + head(ConvLSTM(frames, static), static)
```

`log_prior` is the smoothed historical rate of `mw >= mc` events per cell per forecast window,
computed from pre-cutoff seismicity. Because the output convolution starts at zero, an untrained
network issues exactly that climatology and training only ever learns the departure from it. The
whole model is of the order of two to sixteen thousand parameters and trains on CPU in one to four
minutes per region.

Lookback frame length (`frame_days`) is a separate hyperparameter from the forecast window
(`horizon_days`, 30 days), so the model can look back at a finer temporal resolution than it
forecasts at.

Early stopping scores the network **before any gradient step**, as epoch -1. Its head is zero, so
that state is exactly the climatological prior, and it is a legitimate candidate: if training
never improves the held-out likelihood, the model kept is the climatology and the fit says so
(`training.selected_the_untrained_climatology`).

The network's output is an expected count of `m >= mc` events per cell per window. To reach the
`ForecastGrid` contract it is scaled linearly to the horizon and multiplied by the analytic
Gutenberg-Richter bin probabilities over `Region.magnitude_bin_edges()`, using the ETAS adapter's
own `gr_bin_probabilities` and its `mc - delta_m/2` binning convention. The b-value comes from an
Aki maximum-likelihood fit on the training block.

Loss is the Poisson negative log-likelihood on cell counts, summed over in-region cells — the
quantity the CSEP likelihood tests score.

## 2. Covariates actually used

**Dynamic**, per lookback frame (`log1p`-compressed counts):

| Channel | What it is |
|---|---|
| `count_ge_mc` | events with `mw >= mc` in the cell during the frame |
| `count_ge_mc_minus_1` | events with `mw >= mc - 1` in the cell during the frame |
| `magnitude_weighted_ge_mc` | sum of `10^(mw - mc)` over those events |

**Static**, computed once from events before the training-block end and frozen:

| Channel | Source | Notes |
|---|---|---|
| `fault_density` | GEM Global Active Faults (GAF), CC-BY-SA-4.0, ADR-0007 | kilometres of mapped active-fault trace per cell. Each line segment is split into pieces no longer than a fifth of a cell and each piece's great-circle length is credited to the cell holding its midpoint — an approximation of an exact intersection, exact to within about 2 km at 0.1 degrees. |
| `historical_rate` | the region's own catalogue | `log1p` of the count of `mw >= mc` events per cell before the cut |
| `mean_depth` | the region's own catalogue | mean hypocentral depth of past events in the cell, normalised by the region depth limit; cells with no past event take the regional mean |
| `shallow_fraction` | the region's own catalogue | fraction of past events in the cell shallower than 15 km |

When the GAF GeoParquet (`data/interim/gem_active_faults.parquet`, DVC-tracked) is absent the
adapter falls back to the committed real GAF subset under `data/fixtures/gem_faults/`, and if that
does not cover the region the channel is all zeros and the fit records
`static_covariates.fault_density_available = false` with the reason. It never invents a density.

## 3. Data actually used

| Region | Catalogue | Events | Mc | Target threshold | Cells | Magnitude bins |
|---|---|---|---|---|---|---|
| `nepal-himalaya` | `data/catalogs/nepal-himalaya` (ISC + ComCat + GCMT, built 2026-09-03, event hash `98ed19af7dca`) | 2728 (2727 earthquakes), 1976-05-10 to 2026-07-21 | 4.4 | M ≥ 4.7 | 2079 | 43 |
| `turkiye-eaf` | `data/catalogs/turkiye-eaf` (ISC + ComCat + GCMT, built 2026-09-03, event hash `80649982ef4a`) | 7038 (7036 earthquakes), 1976-01-07 to 2026-07-23 | 4.3 | M ≥ 4.6 | 1409 | 44 |

These are the real homogenised rupture catalogues built by `rupture catalog build`, the same ones
the published ETAS baseline was fitted and scored on — the ETAS schedule reports the same
catalogue event hashes. They are DVC-tracked and were **not** present in this worktree on
checkout; they were copied in from the repository's own working tree before the run, and the run
report records the hash of what it read.

**`california` was not run.** Its ETAS fit takes about 94 minutes and its published schedule
covers one window; scoring a challenger against a one-window baseline says nothing. The promotion
rule needs two of three regions, so the result below is reported over the two regions that have a
full 55-window baseline, and the third is recorded as not run rather than as a failure.

The unit suite never touches these catalogues. It runs on the committed real ComCat slice
`tests/fixtures/forecasting/comcat-california-2018-2019-m3.geojson` over a test-only region.

## 4. Hyperparameter and weight protocol

Three cutoffs, each stage strictly before the next (ADR-0022 § 4):

| Stage | Cutoff | What it decides | What it may see |
|---|---|---|---|
| Hyperparameter search | 2020-01-01 | which configuration is frozen | events before 2020-01-01; each candidate is ranked on its own inner validation block, which ends at that cutoff |
| Weight-fitting block | 2020-01-01 fit; windows 2020-01-01 to 2022-01-01 | the ensemble weights (ADR-0032) | events before each window's issue time |
| Test | 2022-01-01 | nothing — it is scored, not tuned | events before each window's issue time |

The search grid was four configurations, varying how far back the model looks, at what temporal
resolution, and how hard it is pushed away from its initialisation:
`(n_frames, frame_days, hidden_channels, learning_rate)` in
`(6, 30 d, 8, 3e-3)`, `(8, 7.5 d, 8, 3e-3)`, `(6, 30 d, 16, 3e-4)`, `(8, 7.5 d, 8, 3e-4)`. The winner is frozen, its
configuration hash recorded, and the same configuration is refitted at the test cutoff. Candidate
fits are written under `reports/challenger/<region>/search-fits/` and never into `baselines/`.

Within a fit, the train/validation cut is blocked and time-forward: training windows are those
whose target period ends at or before `cutoff - inner_validation_years`, validation windows are
the rest. The splitter has no shuffle parameter and asserts that every validation window is later
than every training window. Static covariates and normalisation statistics are computed from
events before the **training-block end**, so the early-stopping decision cannot see the validation
block either.

Every persisted fit carries a `hyperparameters.json` next to it holding the frozen configuration,
its hash, the inner-validation window the choice was made on, and the full search table. That is
the evidence the `validate-challengers` gate reads, so the freezing claim is checked against the
artefact rather than taken from this document.

Refit policy: **none**. The gridded model is fitted once at the test cutoff and its
time-dependence comes entirely from the lookback frames. ETAS refits yearly over the same
schedule. That is a handicap to the challenger and is not corrected for.

## 5. What was scored, and how

The protocol schedule: 30-day windows every 30 days from 2022-01-01, the last closing at or before
2026-08-01 — 55 windows per region. Consistency tests N, M, S, L, CL through the existing
`PyCSEPEvaluator` (pycsep 0.8.0) at α = 0.05 with 1000 simulations and seed 20220101, exactly as
the baseline was scored. The paired T-test and the W-test are run per window against **the ETAS
baseline's own stored forecasts** — the very grids the published schedule scored, read back from
`data/forecasts/<region>/etas-mizrahi/`, not a re-issue.

The promotion rule's condition 2 asks whether the challenger beats ETAS in the paired T-test *over*
the windows, not window by window. pycsep's `paired_t_test` scores one window, and a 30-day window
with one or two target events has almost no power — most windows cannot even define the statistic.
So both are reported: the per-window pycsep results, and a **pooled** paired T-test that puts every
window's target events into one test using the same statistic (Rhoades et al. 2011, eq. 17-18) with
`N_A` and `N_B` the summed forecast counts over the schedule. The pooled test is the one the
promotion decision uses; the per-window counts are reported alongside so the reader can see how
thin each window is. The W-test is pooled the same way (Wilcoxon signed-rank on the per-event
log-rate differences, centred on `(N_A - N_B)/N`).

Per-window results, pass rates and comparisons are in
`reports/challenger/<region>/schedule-<region>-challengers.json` (untracked, like the rest of
`reports/`).

## 6. Results

**Headline: not promoted, in either region, on either condition.** The gridded challenger loses
the N-test and the L-test to the baseline in both regions, and its pooled information gain against
ETAS is negative in `nepal-himalaya` and indistinguishable from zero in `turkiye-eaf`. That is the
expected outcome and it is reported here without softening.

### Pass rates, 30-day horizon, 55 windows per region

| Region | Model | N | M | S | L | CL |
|---|---|---|---|---|---|---|
| `nepal-himalaya` | ETAS baseline | 51/55 (0.93) | 21/22 (0.95) | 16/22 (0.73) | 17/22 (0.77) | 19/22 (0.86) |
| `nepal-himalaya` | **gridded (C1b)** | 49/55 (0.89) | 21/22 (0.95) | 19/22 (0.86) | 13/22 (0.59) | 21/22 (0.95) |
| `turkiye-eaf` | ETAS baseline | 50/55 (0.91) | 27/29 (0.93) | 20/29 (0.69) | 26/29 (0.90) | 25/29 (0.86) |
| `turkiye-eaf` | **gridded (C1b)** | 49/55 (0.89) | 28/29 (0.97) | 21/29 (0.72) | 20/29 (0.69) | 23/29 (0.79) |

The N-test denominator is every evaluated window; M, S, L and CL are decided only where the window
held at least one target event (protocol § 5). The ETAS rows are the published baseline
(`docs/BASELINE_RESULTS.md`), not a re-run.

The shape is consistent across both regions: the challenger **wins the spatial test** — a smoothed
historical field is a better guess at where the next month's events fall than a smoothed ETAS
background — and **loses the likelihood test**, because it has no way to raise the rate where a
sequence is already running.

### Paired comparison against ETAS

Per window, as pycsep computes it:

| Region | windows the T-test could decide | T-test wins | losses | windows with positive gain | W-test wins |
|---|---|---|---|---|---|
| `nepal-himalaya` | 9 | 0 | 9 | 3/22 | 0/22 |
| `turkiye-eaf` | 10 | 1 | 9 | 5/29 | 0/29 |

A 30-day window with one or two target events cannot decide a paired t-test at all, which is why
only 9 and 10 of 55 windows are decidable. Pooled over the whole schedule (see
`§ 5` for how, and read the interval with the caveat there):

| Region | target events | information gain per event | 95 % interval | t | pooled W-test p | beats ETAS |
|---|---|---|---|---|---|---|
| `nepal-himalaya` | 66 | **-0.6215** | [-1.1049, -0.1382] | -2.568 | 0.108 | no |
| `turkiye-eaf` | 217 | **+0.0587** | [-0.3011, +0.4185] | 0.322 | 0.020 | no |

The Türkiye figure is worth taking apart, because a naive reading of "+0.06" is that the challenger
is level with the baseline. It is not. The whole of that number, and more, comes from the single
window containing the 2023 Kahramanmaraş doublet, where a diffuse climatology beats a baseline
that had assigned a very low rate to the cells the sequence started in. Remove that one window and
the challenger's gain is **-1.19 per event** [-2.07, -0.31]. In the aftershock windows that
follow, where ETAS is doing the thing ETAS is for, the challenger loses heavily.

| Region | total gain (nats) | largest window | its share | its targets | pooled gain per event without it |
|---|---|---|---|---|---|
| `nepal-himalaya` | -41.0 | 2025-01-15 | 0.40x | 4 | -0.395 [-0.822, +0.032] |
| `turkiye-eaf` | +12.7 | 2023-01-26 | 6.32x | 160 | -1.190 [-2.065, -0.315] |

### Promotion decision

Protocol § 10, applied:

- `nepal-himalaya`: condition 1 **not met** (N 0.89 < 0.93, L 0.59 < 0.77); condition 2 **not met**
  (gain -0.62, upper bound below zero). Not promotable here.
- `turkiye-eaf`: condition 1 **not met** (N 0.89 < 0.91, L 0.69 < 0.90); condition 2 **not met**
  (interval spans zero). Not promotable here.
- `california`: not run.

**The gridded challenger is recorded as not promoted.** There is no route to promotion that this
result leaves open.

### What the fit actually produced

| Region | frozen config | weights | trained on | inner validation | Mc | b | GAF trace in region |
|---|---|---|---|---|---|---|---|
| `nepal-himalaya` | 6 frames of 30 d, 8 hidden, lr 3e-3, hash `86617c8cd1d4` | 5234, sha256 `8fc20071b7ab`, snapshot `e0bf8c78be79` | 206 windows, 558 target events | 37 windows, 28 events | 4.4 | 1.100 | 51 features, 2313 km |
| `turkiye-eaf` | same config | 5234, sha256 `c8b4d877ac64`, snapshot `85f622aae6f7` | 206 windows, 175 target events | 37 windows, 71 events | 4.3 | 0.939 | 65 features, 2542 km |

Training of the fits that were actually scored, against their own untrained (climatological) state:

| Region | untrained validation NLL | best | at epoch | epochs run | improvement | kept the climatology |
|---|---|---|---|---|---|---|
| `nepal-himalaya` | 6.39765 | 6.16073 | 6 | 22 | 3.7 % | no |
| `turkiye-eaf` | 12.92477 | 11.49398 | 4 | 20 | 11.1 % | no |

The GEM fault-density channel was available and non-zero in both regions. Every fit is persisted to
`baselines/gridded/<region>/` with its weights, its normalisation state and a `hyperparameters.json`
recording the frozen configuration, its hash and the window it was chosen on, and is archived under
`fits/<cutoff>/`.

### The hyperparameter search, and what it says

| Region | n_frames | frame days | hidden | lr | weights | epochs run | best epoch | validation NLL | untrained NLL | kept the climatology |
|---|---|---|---|---|---|---|---|---|---|---|
| `nepal-himalaya` | 6 | 30 | 8 | 3e-3 | 5234 | 21 | 5 | 7.90464 **(frozen)** | 7.93824 | no |
| `nepal-himalaya` | 8 | 7.5 | 8 | 3e-3 | 5234 | 16 | 0 | 7.91826 | 7.93824 | no |
| `nepal-himalaya` | 6 | 30 | 16 | 3e-4 | 16226 | 16 | 0 | 7.93578 | 7.93824 | no |
| `nepal-himalaya` | 8 | 7.5 | 8 | 3e-4 | 5234 | 16 | 0 | 7.93654 | 7.93824 | no |
| `turkiye-eaf` | 6 | 30 | 8 | 3e-3 | 5234 | 15 | -1 | 4.00049 **(frozen)** | 4.00049 | yes |
| `turkiye-eaf` | 8 | 7.5 | 8 | 3e-3 | 5234 | 15 | -1 | 4.00049 | 4.00049 | yes |
| `turkiye-eaf` | 6 | 30 | 16 | 3e-4 | 16226 | 15 | -1 | 4.00049 | 4.00049 | yes |
| `turkiye-eaf` | 8 | 7.5 | 8 | 3e-4 | 5234 | 15 | -1 | 4.00049 | 4.00049 | yes |

**This is the most informative table in the document, and it needs reading carefully: it is the
*search* at the 2020-01-01 cutoff, not the fits that were scored.** In `turkiye-eaf` every
candidate's held-out likelihood was best *before any gradient step* and got monotonically worse
from the first epoch onward, at every learning rate and every frame length tried, so early stopping
kept the untrained network — whose zero head makes it exactly the smoothed historical rate. All
four candidates therefore score identically and the tie is broken toward the smallest model with
the shortest lookback. In `nepal-himalaya` training helped, by 0.4 % of the held-out negative
log-likelihood.

The **test fits**, refitted with the frozen configuration at the 2022-01-01 cutoff, did train: their
inner validation block is 2019-2022 rather than 2017-2020, and against their own untrained state
they improve the held-out negative log-likelihood by 11.1 % in `turkiye-eaf` (12.925 to 11.494,
best at epoch 4) and 3.7 % in `nepal-himalaya` (6.398 to 6.161, best at epoch 6). So the network
does learn something — the question is what.

**What it learns is a mostly-spatial refinement with a very weak temporal response.** The direct
test is the month after the 2023 Kahramanmaraş doublet: given a history containing 160 target
events in the previous 30 days, the fitted `turkiye-eaf` model raises its busiest cell by a factor
of 2.3 and changes 373 of 1409 cells by more than 10 % — it has noticed — but its **total** expected
count rises only 4.4 %, from 0.427 to 0.446. ETAS's total over the same step rises from 0.45 to
25.16, a factor of 56. The challenger's time-dependence is real and roughly two orders of magnitude
too weak, which is exactly what the L-test then says: 20/29 against the baseline's 26/29.

The mechanism behind the weakness is visible in the data. The two regions have opposite activity
imbalances between the training block and the inner validation block that follows it: 0.85 target
events per window rising to 1.92 in `turkiye-eaf`, and 2.71 falling to 0.76 in `nepal-himalaya`
(the training block there contains the 2015 Gorkha sequence). A global calibration learned on
either training block is wrong for the block after it by a factor of two to three before any
spatial or temporal structure is considered, and a model with a few thousand parameters and a few
hundred target events spends what it has on that rather than on clustering.

In operation the challenger is therefore very close to a smoothed time-independent rate model with
a Gutenberg-Richter magnitude distribution: its total expected count varies by under 9 % across the
55 windows in both regions (0.419 to 0.453 in `nepal-himalaya`, 0.425 to 0.448 in `turkiye-eaf`).
That is a respectable CSEP baseline in its own right — it wins the S-test in both regions — and it
is not, in any useful sense, a time-dependent forecast.

### The leaky ablation (ADR-0022 § 6) — not a result

A gridded fit whose cutoff is the schedule end, so its training windows, its static covariates and
its normalisation statistics all contain the windows it is then scored on, with the `fit_cutoff`
rewritten so the guard that exists to stop this can be stepped over deliberately:

| Region | target events | leaky log-likelihood | honest | ETAS | apparent gain per event from leaking |
|---|---|---|---|---|---|
| `nepal-himalaya` | 66 | -685.96 | -706.66 | -665.64 | **+0.314** |
| `turkiye-eaf` | 217 | -1991.21 | -2459.99 | -2472.73 | **+2.160** |

In `turkiye-eaf` leakage buys 2.16 nats per event of apparent skill — about six times the largest
honest gain anything in this work achieved. That is the number to hold in mind when reading any
challenger result, here or elsewhere, whose leakage discipline is not stated.

### Cross-check

The 55 scored windows have identical issue times and identical target counts to the published ETAS
schedule in both regions, so the comparison is on exactly the same targets. The baseline used five
parameter snapshots over the schedule (four yearly refits); the challenger used one.

## 7. Limitations

- **The magnitude distribution is not learned.** It is Gutenberg-Richter with a b-value fitted by
  Aki maximum likelihood on the training block. The M-test therefore tests that assumption and
  that b-value, not the network.
- **One trained horizon.** The model is trained at 30 days and rescales linearly in time. The
  protocol horizon is the trained one; a 1-day or 365-day forecast from this model is an
  extrapolation and is not scored here.
- **No refits.** See § 4. The baseline refits yearly and the challenger does not.
- **The fitted model is nearly a climatology.** This is the finding, not a caveat about it. The
  network does train — 11.1 % and 3.7 % improvements in held-out negative log-likelihood over its
  own untrained state — and what it learns is close to a static spatial correction: after a month
  containing 160 target events its total expected count moves by 4.4 % where ETAS's moves by a
  factor of 56. The delivered model cannot track an aftershock sequence, and that is what loses it
  the L-test in both regions. Anyone reading this as a deep-learning success should read it as the
  opposite: on catalogues of this size, under a blocked time-forward protocol, the ConvLSTM bought
  a small spatial refinement over smoothed seismicity and no useful time dependence.
- **The climatological prior is a long-term average over a period of changing completeness.** It is
  the count of `mw >= mc` events per cell divided by the number of frames the catalogue spans, from
  1976 onward, and network coverage in the 1970s and 1980s is not that of the 2020s. The prior is
  therefore biased low for recent decades, and it shows: summed over the 55 test windows the
  challenger expects 23.6 events against 66 observed in `nepal-himalaya` and 23.6 against 217 in
  `turkiye-eaf` (against 57 once the Kahramanmaraş window is set aside). The N-test still passes in
  49 of 55 windows in both regions because most windows hold no target event at all, which is
  itself a statement about how little power these windows have.
- **Two regions, and one of those dominated by one sequence.** `turkiye-eaf`'s schedule contains
  the 2023 Kahramanmaraş doublet and its aftershocks; `nepal-himalaya` contains one moderate
  sequence. Pass rates over 55 windows of which only 22 (`nepal-himalaya`) and 29 (`turkiye-eaf`)
  hold a target event at all are weak evidence, as § 12 of the protocol says.
- **The fault-density covariate is coarse.** Trace length per cell says nothing about slip rate,
  dip, or which fault is loaded. GAF carries slip-type and quality attributes that this model does
  not use.
- **`rupture.models.data` seam.** Until the shared dataset machinery lands, the causal-window,
  blocked-split, cutoff-assertion and train-only-normalisation helpers come from a local fallback
  in `src/rupture/models/challengers/gridded/_data.py`. Which side was live is recorded in every
  fit's `diagnostics.seam_source`.

## References

Shi, X., Chen, Z., Wang, H., Yeung, D.-Y., Wong, W.-K. & Woo, W.-C. (2015). Convolutional LSTM
network: a machine learning approach for precipitation nowcasting. *NeurIPS 28*.
Aki, K. (1965). Maximum likelihood estimate of b in the formula log N = a - bM. *Bull. Earthq. Res.
Inst.* 43. Styron, R. & Pagani, M. (2020). The GEM Global Active Faults Database. *Earthquake
Spectra* 36(1_suppl). Savran, W. et al. (2022). pycsep. *SRL* 93(5). Mizrahi, L., Nandan, S. &
Wiemer, S. (2021). *SRL/JGR*.
