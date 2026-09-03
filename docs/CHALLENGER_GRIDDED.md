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

<!-- RESULTS:GRIDDED -->

## 7. Limitations

- **The magnitude distribution is not learned.** It is Gutenberg-Richter with a b-value fitted by
  Aki maximum likelihood on the training block. The M-test therefore tests that assumption and
  that b-value, not the network.
- **One trained horizon.** The model is trained at 30 days and rescales linearly in time. The
  protocol horizon is the trained one; a 1-day or 365-day forecast from this model is an
  extrapolation and is not scored here.
- **No refits.** See § 4. The baseline refits yearly and the challenger does not.
- **A static climatology with a small learned correction.** Because the head starts at zero and the
  training signal is a few hundred target events, the fitted model stays close to the smoothed
  historical rate. That is the right thing for the data volume and it is also the reason the model
  cannot track an aftershock sequence the way ETAS does.
- **Two regions, and one of those dominated by one sequence.** `turkiye-eaf`'s schedule contains
  the 2023 Kahramanmaraş doublet and its aftershocks; `nepal-himalaya` contains one moderate
  sequence. Pass rates over 55 windows with 22 and 29 decided windows respectively are weak
  evidence, as § 12 of the protocol says.
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
