# ADR-0031: C1b is a small ConvLSTM over rasterised seismicity plus static covariates

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

The brief asks for a gridded spatio-temporal deep model as a challenger to the ETAS baseline: a
ConvLSTM or a small spatio-temporal transformer over rasterised seismicity history plus static
covariates, CPU-only and small enough to train in minutes on a laptop. It must satisfy the same
`ForecastModel` port as ETAS, land on the same lattice and magnitude bins, and be scored under the
same protocol.

The data decides most of the design. On the two regions whose catalogues and baseline fits exist
in this tree, a 30-day window at the regional completeness magnitude holds one or two events
spread over a few thousand cells: `nepal-himalaya` has 942 events at or above Mc = 4.4 in fifty
years over 2079 cells, `turkiye-eaf` 871 at or above Mc = 4.3 over 1409 cells. That is a few
hundred non-zero target cells in the whole training block. A model with more capacity than that
supports will fit the aftershock sequences it was shown and nothing else.

## Decision

1. **Architecture: one ConvLSTM layer (Shi et al. 2015) with 8 or 16 hidden channels, a two-layer
   convolutional head, of the order of two to five thousand parameters.** A transformer over the
   same rasters would need positional machinery and more data to pay for it. The model runs on
   CPU with a fixed thread count recorded in the configuration.
2. **The head is initialised to zero and its output is added to a climatological log-rate**
   computed from smoothed pre-cutoff seismicity. An untrained network issues exactly the smoothed
   historical rate, so training only ever learns the departure from climatology. This is the
   single choice that makes a model this small usable: it does not spend its data budget
   rediscovering where earthquakes happen.
3. **Inputs.** Dynamic: per-cell counts of `mw >= mc`, counts of `mw >= mc - 1`, and a
   magnitude-weighted sum `10^(mw - mc)`, over `n_frames` causal lookback frames of `frame_days`
   each, `log1p`-compressed. Static: mapped active-fault trace length per cell from the GEM Global
   Active Faults database (ADR-0007), historical count per cell, mean hypocentral depth, and the
   fraction of past events shallower than 15 km. **`frame_days` is independent of the forecast
   horizon** (`horizon_days`), so the model can look back at a finer temporal resolution than it
   forecasts at — which is where aftershock clustering lives.
4. **Output.** The network gives an expected count of `m >= mc` events per cell per frame. It is
   scaled linearly to the requested horizon and multiplied by the analytic Gutenberg-Richter bin
   probabilities on `Region.magnitude_bin_edges()`, using the same
   `gr_bin_probabilities` helper and the same `mc - delta_m/2` convention as the ETAS adapter, so
   the two models' grids are directly comparable by pycsep. The b-value is Aki maximum likelihood
   on the training block.
5. **Loss is the Poisson negative log-likelihood on cell counts** — the quantity the CSEP
   likelihood tests score. Nothing is trained on a surrogate.
6. **Leakage (ADR-0022).** Frames are closed-left, open-right and the last one ends exactly at the
   issue time. Any training window whose target period reaches the cutoff is an error, not a
   dropped row. The train/validation cut is blocked and time-forward with no shuffle parameter.
   Static covariates *and* normalisation statistics are computed from events before the
   **training-block end**, not merely before the cutoff, so the early-stopping decision cannot see
   the validation block either.
7. **The untrained network is a legitimate candidate.** Early stopping scores the network before
   any gradient step, as "epoch -1". Its head is zero, so that state is exactly the climatological
   prior. If no amount of training improves the held-out likelihood, the honest outcome is to keep
   the climatology *and to be able to say so*, rather than to ship whatever the first epoch
   produced. Every fit records `selected_the_untrained_climatology`.
8. **Determinism and persistence.** A fixed seed, a fixed batch order (batches are taken in time
   order and never shuffled) and a fixed thread count make a fit reproducible; the run is
   identified by the SHA-256 of its weights, which is carried into `FitResult.parameters` as two
   float-encoded digest halves so that `parameter_snapshot_hash` changes whenever a weight does.
   Fits persist to `baselines/gridded/<region>/` and archive per cutoff, mirroring the ETAS
   layout, and a non-canonical save never replaces a declared baseline.
9. **No refits inside a schedule.** The model is fitted once, at the test cutoff, and its
   time-dependence comes entirely from the lookback frames. ETAS refits yearly on the same
   schedule. This is a handicap and is reported as one.

## Consequences

- The challenger's grids are drop-in comparable with the baseline's: same lattice, same bins, same
  `ForecastGrid` contract, so `PyCSEPEvaluator.compare` runs without any adaptation.
- The magnitude distribution is not learned, so the M-test says something about Gutenberg-Richter
  and the fitted b-value, not about the network.
- The model is trained at one horizon and rescales linearly in time. That is only defensible near
  the trained horizon, and the protocol horizon is the trained one.
- Because the climatology is static and the departure is small, the model behaves like a smoothed
  time-independent rate with a modest time-dependent correction. That is exactly the sort of model
  that ETAS beats during aftershock sequences, which is the honest expectation.

## Alternatives considered

- **A spatio-temporal transformer.** Rejected for this data volume: attention over a few thousand
  cells and a handful of frames adds parameters that a few hundred target events cannot constrain.
- **Learning the magnitude distribution.** Rejected: with one or two events per window there is no
  signal to fit a per-cell magnitude distribution, and a learned one would make the M-test
  uninterpretable rather than informative.
- **A stateful ConvLSTM over the whole catalogue rather than a fixed lookback.** Attractive — it
  would be cheaper per epoch and carry unbounded memory — but it needs a full replay of the
  catalogue at every issue time and truncated backpropagation, and the complexity was not
  justified before the simple version had been scored.
- **Refitting yearly to match ETAS.** Deferred rather than rejected. It would remove the handicap
  in condition 1 of the promotion rule; it was not run for this phase and the omission is stated
  in `docs/CHALLENGER_GRIDDED.md`.
