# The log-linear ensemble

**rupture does not predict earthquakes.** The ensemble pools the expected-count grids of the ETAS
baseline and one or more challengers into a single expected-count grid on the same lattice and
magnitude bins, and is scored under the same protocol as its components.

Design rationale is ADR-0032. This document says what was built, what the weights were fitted on,
what it scored, and where it is fragile.

## 1. The pool

```
log lambda_ens(cell, bin) = sum_k w_k log max(lambda_k(cell, bin), floor_k)     w_k >= 0, sum w_k = 1
```

rescaled so that the total is the weighted geometric mean of the components' totals,
`log N_ens = sum_k w_k log N_k`.

**The floor.** `floor_k = floor_fraction * total_k / (n_cells * n_bins)` with
`floor_fraction = 1e-6`. It is relative to each component's own mean rate per cell-bin, not
absolute, so it means the same thing in a region with two target events a year as in one with a
hundred and does not change with the magnitude threshold. It is bounded: raising every cell-bin to
the floor adds at most `floor_fraction` of that component's total, so the floor cannot move the
count forecast. What it does move is the far tail — an ETAS grid on `nepal-himalaya` has cell-bins
at 1e-23 expected events, which is an extrapolated analytic background law rather than an estimate
— and there it is doing exactly the job it is for: without a floor, one observed event in one such
cell sends the pooled log-likelihood to minus infinity and the ensemble is rejected on a single
cell's worth of extrapolation. The value was fixed in advance and **not** tuned on any window.

**The normalisation.** The geometric mean of two rate fields does not integrate to anything in
particular, so an unnormalised pool is not a rate forecast. Rescaling to the weighted geometric
mean of the totals makes the ensemble's N-test behaviour an interpolation between its components'
rather than an artefact of the pooling.

At `w_k = 1` the ensemble is component *k* with its own floor applied and renormalised — very
close to, but not bit-identical with, that component. The unit tests state that rather than hide
it.

## 2. Components

The component list is a constructor argument: `LogLinearEnsemble({name: provider, ...})`, where a
provider is `(history, issue_time, horizon) -> ForecastGrid`. Components must agree on cells and
magnitude bins, and a component whose fit cutoff is after its issue time is refused. Any mismatch
is an error, never something the ensemble reconciles quietly.

**In this run the components are ETAS and the gridded challenger (C1b), and only those.** The NTPP
challenger (C1a) is built on a sibling branch and does not exist in this worktree, so it is not in
the pool. Adding it is a one-line change to the component mapping; no other code changes.

## 3. Weight fitting

Weights are fitted by maximising the summed Poisson log-likelihood of the observed cell-magnitude
counts over the **validation windows only**:

| | |
|---|---|
| Validation windows | 30-day windows every 30 days from 2020-01-01, the last closing exactly at 2022-01-01 — 24 windows |
| ETAS component there | fitted at cutoff 2020-01-01, 1000 continuations per forecast, seed 20220101 |
| Gridded component there | the frozen configuration fitted at cutoff 2020-01-01 |
| Search | deterministic grid over the simplex: coarse pass at 0.05, refinement at 0.01 inside the winning cell. No gradient optimiser, no random restart, so the weights are reproducible to 0.01 |
| Assertion | every validation window closes at or before the test cutoff, and each component's fit cutoff is at or before its issue time; both raise rather than warn |

The test schedule then uses the ETAS baseline declared for the protocol (fitted 2022-01-01,
refitting yearly) and the gridded model fitted at 2022-01-01, with the weights frozen from the
validation block. Nothing in the test period touches the weights.

## 4. What was scored, and how

Identical to the gridded challenger: 55 windows of 30 days from 2022-01-01, N/M/S/L/CL through
`PyCSEPEvaluator` at α = 0.05 with 1000 simulations and seed 20220101, plus the paired T-test and
the W-test per window against the ETAS baseline's own stored forecasts.

The promotion rule's condition 2 asks whether the challenger beats ETAS in the paired T-test *over*
the windows, not window by window. pycsep's `paired_t_test` scores one window, and a 30-day window
with one or two target events has almost no power — most windows cannot even define the statistic.
So both are reported: the per-window pycsep results, and a **pooled** paired T-test that puts every
window's target events into one test using the same statistic (Rhoades et al. 2011, eq. 17-18) with
`N_A` and `N_B` the summed forecast counts over the schedule. The pooled test is the one the
promotion decision uses; the per-window counts are reported alongside so the reader can see how
thin each window is. The W-test is pooled the same way (Wilcoxon signed-rank on the per-event
log-rate differences, centred on `(N_A - N_B)/N`).

An **ablation** runs alongside: the same pool refitted and rescored with the challenger's spatial
field flattened to uniform (total and magnitude distribution unchanged). With a near-static second
component a log-linear pool is close to *tempering* the baseline — raising its rate field to a
power below one and renormalising — and the ablation is exactly that and nothing else, so the two
numbers say how much of any gain is pooling arithmetic and how much is the challenger's field.

Per-window results are in `reports/challenger/<region>/schedule-<region>-challengers.json`.

## 5. Results

<!-- RESULTS:ENSEMBLE -->

## 6. Limitations

- **The weights rest on very little.** They are fitted on 24 windows containing a handful of
  target events per region. The number of validation target events is reported next to every
  fitted weight for that reason. A weight of 0.6 versus 0.4 on that evidence is not a strong
  statement about which model is better.
- **A geometric pool is intolerant of disagreement by construction.** Where one component says
  "almost nothing here" the pool says almost nothing, whatever the other says. That is the reason
  for the floor, and the floor is a choice, not a derivation.
- **The ensemble inherits its components' handicaps.** In particular the gridded component does not
  refit inside the schedule while the ETAS component does.
- **The ETAS component in the weight-fitting block is not the declared baseline.** It is a separate
  fit at the 2020-01-01 cutoff, because the declared baseline is fitted to 2022-01-01 and cannot
  legally issue a 2020 forecast. Its parameters therefore differ slightly from the ones used in the
  test period.
- **Two regions only.** `california` was not run; see `CHALLENGER_GRIDDED.md` § 3.
- **`floor_fraction` was not tuned.** Tuning it on the validation block would be legal under
  ADR-0022 and was deliberately not done, so that the floor can be neither blamed for nor credited
  with the result. That also means it may not be the best value.
