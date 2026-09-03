# Model card — C1b gridded spatio-temporal challenger

**Version:** 0.1.0 (Prompt 2, challenger models)
**Model id:** `gridded-convlstm`
**Date:** 2026-09-03
**Repository:** `github.com/dizzy1900/rupture`
**Full documentation:** [`docs/CHALLENGER_GRIDDED.md`](../docs/CHALLENGER_GRIDDED.md).
Decisions: [ADR-0031](../docs/adr/0031-gridded-spatio-temporal-challenger.md),
[ADR-0022](../docs/adr/0022-leakage-engineering-for-learned-models.md).

---

## What this is

A small ConvLSTM over rasterised seismicity history and static covariates, producing **expected
counts of earthquakes per 0.1-degree cell per 0.1-magnitude bin over a 30-day window**, on the same
lattice and bins as the ETAS baseline. It is a challenger, scored under the pre-registered protocol
in `docs/EVALUATION_PROTOCOL.md`, and it is **not** promoted.

## Out of scope

- **Forecasting individual earthquakes deterministically.** rupture does not do this anywhere and
  this model does not either. It issues rates over cells and windows and has no statement to make
  about any single future earthquake — not its time, not its place, not its magnitude.
- Any warning, alerting or notification function.
- Horizons far from the 30 days it was trained at. Other horizons are a linear rescaling in time
  and are not scored.
- Regions other than the two it was fitted for. There is no transfer: the climatological prior,
  the normalisation statistics and the b-value are all region-specific.
- Magnitudes below the region's target threshold, or events outside the region polygon or its
  depth range.

## Inputs

**Sourced.** The homogenised rupture catalogues `data/catalogs/nepal-himalaya` and
`data/catalogs/turkiye-eaf` (ISC + ComCat + GCMT, built by `rupture catalog build` on 2026-09-03),
and the GEM Global Active Faults database (`data/interim/gem_active_faults.parquet`,
CC-BY-SA-4.0). Both are DVC-tracked. The catalogue event hash the run actually read is recorded in
every run report.

**Not sourced.** Nothing was substituted for a missing input. If the GAF file is absent and the
committed GAF fixture does not cover the region, the fault-density channel is zero and the fit
records `fault_density_available: false` with the reason.

## Outputs

A `ForecastGrid` (`contracts/forecast-grid.v0.json`): expected counts per cell per magnitude bin,
with `fit_cutoff`, `training_catalog_hash` and `parameter_snapshot_hash` pinned. The snapshot hash
is derived in part from the SHA-256 of the trained weights, so it changes whenever a weight does.

## Training and evaluation data

| | |
|---|---|
| Trained on | `nepal-himalaya` and `turkiye-eaf`, events before the fit cutoff only |
| Hyperparameters chosen on | a validation block ending 2020-01-01 |
| Ensemble weights fitted on | 2020-01-01 to 2022-01-01 (see the ensemble card) |
| Scored on | 55 pseudo-prospective 30-day windows, 2022-01-01 to 2026-08-01 |
| Not run | `california` — its ETAS baseline schedule covers one window, so there is nothing to compare against |

## Scores

See `docs/CHALLENGER_GRIDDED.md` § 6 for the full tables, and
`reports/challenger/<region>/schedule-<region>-challengers.json` for every window.

<!-- CARD:GRIDDED -->

## Leakage controls

Asserted in code and covered by tests that inject post-cutoff data and expect a `LeakageError`:
dataset builders refuse rather than filter; feature frames are closed-left, open-right and end
exactly at the issue time; the train/validation split is blocked and time-forward with no shuffle
parameter; static covariates and normalisation statistics come from before the training-block end;
`forecast` refuses a history containing an event at or after the issue time, and refuses an issue
time before its own fit cutoff.

A deliberately leaky ablation is run and labelled (ADR-0022 § 6). It is a measurement of what the
discipline is worth, never a result.

## Known limitations

Listed in full in `docs/CHALLENGER_GRIDDED.md` § 7. The load-bearing ones: the magnitude
distribution is Gutenberg-Richter and not learned; the model does not refit inside the schedule
while the baseline does; and the training signal is a few hundred target events, which is the
reason the fitted model stays close to its climatological initialisation.

## Ethical and operational notes

This model is research code scored against a baseline. It is not an operational product, it makes
no statement about any individual earthquake, and nothing in its output should be read as a
warning. Under-claim: if a number is not in the run report, it was not measured.
