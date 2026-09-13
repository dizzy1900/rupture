# The one-neuron spatial aftershock comparator

This is the field's mandatory straw-man for any spatial aftershock or static-stress
classification claim. It is a `ForecastModel` implementation, not a challenger, and it is not
scored on the protocol windows in the pull request that added it.

DeVries et al. 2018 Nature doi 10.1038/s41586-018-0438-y reported AUC 0.849 on aftershock
location — `rebutted`; Mignan & Broccardo 2019 Nature 574 E1–E3 doi 10.1038/s41586-019-1582-8
matched it with two-parameter logistic AUC 0.85 — `contested`, and Meade et al. Reply Nature 574
E4–E5 doi 10.1038/s41586-019-1583-7 is on the record. Independently, a three-parameter logistic
on log distance-to-rupture and log mean slip reached 0.86. Those numbers are historical, and
this repository will not recompute them.

Code: `src/rupture/models/comparators/`. Model card:
`reports/MODEL_CARD_one_neuron.md`. The baseline table is ADR-0059.

## What it is

A Bernoulli logistic on the region's forecast lattice.

```
P_i = 1 / (1 + exp(-(a + b * x_i [+ c * z_i])))
```

- `x_i = log10(distance_km)` from cell *i*'s centre to the nearest training event with
  `mw >= m_main`, clipped to a documented floor (0.1 km). That is the two-parameter Mignan &
  Broccardo shape. The implementation lives in `OneNeuronAftershockModel`
  (`model_id = one-neuron-logistic`, version `0.1.0`).
- `z_i = log10(mean slip proxy)` only when a finite-fault / `SlipField` is supplied, sampled at
  the cell. Without it the model is the single-feature distance logistic and says so in
  `FitResult.notes`. The sibling `DistanceSlipAftershockModel`
  (`model_id = distance-slip-logistic`) **requires** the slip field and raises
  `MissingSlipFieldError` naming what is missing rather than silently dropping the feature.

On a pooled set of ruptures, Mignan & Broccardo's third parameter was the source's mean slip,
which varies by mainshock. On a single sequence that scalar is absorbed into the intercept. This
implementation therefore samples a spatially varying finite-fault table onto the lattice; a
spatially constant field is refused.

`fit` estimates `a`, `b` (and `c` when slip is present) by maximum likelihood on the training
window. Positives are cells that hosted an event with `origin_time < cutoff` and
`mw >=` the target threshold; negatives are the rest of the region grid. Only events with
`origin_time < cutoff` enter. The adapter calls
`rupture.adapters.forecasting.leakage.assert_all_before`.

There is no `auc` method. Calling `rupture.scoring.refusals.auc` is the response if anyone asks.

## Expected counts, not probabilities

A `ForecastGrid` holds expected **counts**. Occupancy `P_i` is an intermediate. The conversion,
using only training quantities:

```
mean_events_per_positive_cell = n_training_events / n_positive_cells
expected_count_i = P_i * mean_events_per_positive_cell * (horizon_days / training_days)
```

The product is then split across the region's magnitude bins with a Gutenberg–Richter law fitted
on the training magnitudes. Reading `P_i` as a count is a misuse of the artefact; the grid's
`notes` record the conversion.

`forecast` recomputes distances from the history strictly before `issue_time` (falling back to
the training mainshock anchors if the history has none). Productivity is never refit from the
issue window.

## How to score it

Not AUC. Not accuracy. Not a random split over cells.

The repository scores this comparator on the **AlarmSet arm**:

1. Fit `OneNeuronAftershockModel` on `origin_time < cutoff`.
2. Build a **clustering-aware** reference on the same lattice — a fitted ETAS `ForecastGrid`
   converted with `rupture.scoring.reference.from_forecast_grid`. A spatially uniform Poisson
   reference raises `UniformReferenceRefusedError`.
3. Choose an alarm fraction `tau` **before** seeing the targets.
4. Call `rupture.models.comparators.alarm_from_logistic` to emit an `AlarmSet` of the highest-P
   cells whose reference mass equals `tau`.
5. Score with `rupture.scoring.alarm.score_alarm_set`: Molchan trajectory, area skill score,
   probability gain `G` at the declared operating point, matched-random control, and the
   minimum detectable gain.

Area skill weights by events on one axis and by the reference measure on the other. That is the
fix for the class imbalance that let AUC 0.849 conceal a 5.4 % precision.

## What would count as beating it

A spatial machine-learning aftershock model beats this comparator when, on a pre-registered
pseudo-prospective schedule, on the same lattice, cutoff, magnitude threshold and as-of vintage,
it records a higher area skill score against the **same clustering-aware reference**, at a
declared `tau` chosen before the targets, with a positive information-gain or probability-gain
interval that does not rest on independent-event assumptions the aftershocks violate.

Matching that published AUC, or beating Coulomb failure stress, is not a result. Beating this
logistic, and distance-plus-slip when a slip field exists, on the AlarmSet arm, might be.

This PR does not run that comparison. The model card says so.

## Wiring the orchestrator must do

The CLI, the model registry and `RELEASE_STATUS.md` are intentionally untouched here. A later
change that scores spatial claims needs to:

- instantiate `OneNeuronAftershockModel` (and `DistanceSlipAftershockModel` when a finite-fault
  table exists) alongside the challenger;
- call `fit(catalog, region, cutoff)` then `forecast(history, issue_time, horizon)` on the same
  lattice the challenger uses;
- persist `FitResult.parameters` (floats) and `parameter_snapshot()` (floats plus the three
  citation DOIs);
- for the AlarmSet arm, pass a clustering-aware ETAS reference into `alarm_from_logistic`;
- refuse to emit a spatial aftershock score whose baseline table does not include this
  comparator (ADR-0059).
