# ADR-0018 — Issuing ETAS forecasts from a stored fit without refitting

- **Status:** accepted
- **Date:** 2026-09-03

## Context

The evaluation protocol (§ 6, ADR-0015) fixes ETAS parameters within a window and refits only at
declared boundaries. The `etas` package (ADR-0009) was written around a different workflow: its
`ETASSimulation` takes an `ETASParameterCalculation` that has just run `invert()` on a catalogue
ending at the forecast start, and its `runnable_code/simulate_catalog_continuation.py` reloads
such a calculation with `load_calculation` from the files `store_results` wrote. Neither path
covers "parameters fitted with cutoff *C*, history extended to a later issue time *T*, no refit".
Three further properties of the package at the pinned commit matter here:

1. `ETASSimulation.simulate` calls `np.random.seed()` with no argument, and so does
   `simulate_background_location`, reseeding numpy's global generator from OS entropy on every
   call. A forecast issued through those entry points cannot be reproduced from a recorded seed.
2. `etas/simulation.py` imports `seismostats` at module import time although the package
   declares it only in its optional `hermes` extra, so the module is unimportable in rupture's
   locked environment as shipped.
3. The inversion assumes a spatially uniform background rate μ (`optimize_parameters` sets
   `mu_hat = n_hat / (area · T)`), while the simulation places new background events by sampling
   past events weighted by their background probability with Gaussian jitter (`gaussian_scale`).

## Decision

**Fixed-parameter issuance.** `MizrahiETAS.forecast(history, issue_time, horizon)` rebuilds the
package state at `issue_time` without calling `invert()`:

- construct `ETASParameterCalculation` with `catalog` = the history (earthquakes, `mw ≥ Mc`,
  inside the region, `origin_time < issue_time` — asserted, never filtered), the fit's
  `auxiliary_start`/`timewindow_start`, `timewindow_end = issue_time`, the fit's `beta` as a
  fixed value and the fit's θ as `theta_0`;
- call `prepare()` (distances, source and target tables), set `theta` to the stored θ, and run a
  single `expectation_step` with it, which yields each target event's background probability
  and the source table the simulation needs; mark `inversion_done`;
- the simulation's source catalogue is then the history joined to that source table, and the
  adapter asserts its latest `time` is before `issue_time` (`LeakageError` otherwise). A unit
  test proves this with an issue time inside the Ridgecrest sequence.

**Simulation loop and seed.** rupture drives `etas.simulation.simulate_catalog_continuation`
directly, once per continuation, with the same arguments `ETASSimulation.simulate` would pass,
after seeding numpy's global generator with the caller's `seed`. Background locations are drawn
uniformly in the polygon (`background_probs=None`) so the reseeding path in
`simulate_background_location` is never entered. Same seed, same history, same parameters ⇒
identical grid (asserted by `validate-etas`).

**Expected counts = expectation under the fitted model, analytic where possible.** For cell *c*
and magnitude bin *j*:

```
E[N_cj] = ( T_c + B_c ) · p_j
T_c = mean over continuations of simulated *triggered* events (is_background == False, all
      magnitudes ≥ Mc − δ/2) falling in c during [issue, issue + horizon)
B_c = 10^log10_mu · A_region · horizon_days · m_c
m_c = mass over cell c of the package's background-location law: past background events weighted
      by P_background · ζ, each smeared by N(0, gaussian_scale²) in latitude and longitude,
      renormalised over the region's cells
p_j = P(binned magnitude in bin j | m ≥ Mc − δ/2) under the fitted Gutenberg–Richter law
      (exponential with rate beta, rounded to bin centres; last bin open; truncated if m_max set)
```

`T_c` is simulated because the triggered process has no closed form; `B_c` and `p_j` are computed
analytically because the fitted model gives them in closed form (ETAS magnitudes are i.i.d. and
independent of location; the package's background placement is a Gaussian mixture). This is a
variance reduction of the same estimator, not a different model: the simulation's own background
events are dropped from the count (their expectation is `B_c`) and their aftershocks are kept.
The single approximation is that those aftershocks descend from uniformly placed parents rather
than smoothed-law parents; over horizons of days to a month this is second order.

**Compat shim.** `adapters/forecasting/_etas_compat.py` registers a stand-in `seismostats`
module (whose `ForecastCatalog` refuses to be instantiated) only when the real package is absent,
so `etas.simulation` imports. rupture never calls `simulate_to_df`, the sole user of that name.

**Reproducible fits.** The EM starts from a fixed `theta_0` (`DEFAULT_THETA_0`) instead of the
package's random draw, so a refit on the same data reproduces `parameter_snapshot_hash`.

## Consequences

- Issuance costs one `prepare()` + one expectation step on the history (O(pairs within the
  Coppersmith radius)) plus the continuations; no EM.
- Forecast grids are reproducible from `(training_catalog_hash, parameter_snapshot_hash,
  history hash, seed, n_simulations)`, all of which are logged.
- Cells far (many `gaussian_scale`) from any past background event and with no simulated
  triggered event have expected count 0 (floating-point underflow of the Gaussian tail); the
  evaluator records an observed event there as a rejection with the most negative finite
  statistic, and the fixture window that contains Ridgecrest is such a case.
- The shim is an interim; the durable fix is upstream (guard the import) or a `seismostats`
  dependency in `pyproject.toml`, either of which is an architect decision.
- Moving the etas pin (ADR-0009) must re-check the three properties listed under Context.

## Alternatives considered

- **`load_calculation` from `store_results` files.** Rejected: it fixes `timewindow_end` at the
  fit cutoff, so history after the cutoff never becomes a source; it also reads CSVs the adapter
  would have to synthesise.
- **`ETASSimulation.prepare()` + `simulate_to_df`.** Rejected: unseeded reseeding (no
  reproducibility), the `seismostats` import, and an `assert_allclose(min magnitude, m_ref)` that
  fails on any history slice lacking an event exactly at Mc.
- **Pure simulation counts with a uniform floor.** Rejected: the floor would be an invented model
  component; the analytic background term is the fitted model's own.
- **Refit before every window.** Not rejected as a variant (ADR-0015) but not the default.
