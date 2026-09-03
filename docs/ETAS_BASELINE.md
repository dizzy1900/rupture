# The ETAS baseline

rupture does not predict earthquakes. Its operational baseline is the ETAS model of Mizrahi,
Nandan & Wiemer (2021), through the `etas` package pinned in ADR-0009, wrapped by
`rupture.adapters.forecasting.etas_mizrahi.MizrahiETAS` (the `ForecastModel` port). This page
says how a fit is configured, what is persisted, how a forecast is issued and what the known
limitations are. ADR-0018 records the design decisions behind issuance.

## Fit configuration per region

| Input | Source | Notes |
|---|---|---|
| Training events | `catalog.earthquakes().before(cutoff).at_least(Mc)`, then inside the region polygon and `depth_min_km ≤ depth ≤ depth_max_km` (events with unknown depth are kept) | Non-earthquake entries never reach the fit. `origin_time < cutoff` is asserted after filtering (`LeakageError`). |
| Mc | `region.mc.mc` if the region record carries a fitted estimate; else `catalog.preferred_mc()`; else an explicit `mc=` argument (`--mc`) | With none of the three the fit refuses to run. `diagnostics.mc_source` says which one was used. |
| Auxiliary window | `[training_start, training_start + auxiliary_years)`; default 2.0 years | Auxiliary events trigger but are not targets. Must leave a non-empty primary window before the cutoff. |
| Primary window | `[timewindow_start, cutoff)` | Events here are sources and targets. |
| `delta_m` | `region.magnitude_bin_width` (0.1) | Magnitudes are rounded to bin centres by the package. |
| `shape_coords` | region polygon as `[[lat, lon], ...]` | The package works in (lat, lon) order. |
| `coppersmith_multiplier` | 100 | Pairs farther apart than 100 × the Wells–Coppersmith subsurface rupture length are treated as uncorrelated. |
| `beta` | estimated (Tinti) unless `fixed_beta` is given | `b = beta / ln 10` is in the diagnostics. |
| `theta_0` | `DEFAULT_THETA_0`, a fixed EM start | Makes the fit reproducible run to run; the package would otherwise draw a random start. |

Parameters are the package's (`log10_mu, log10_k0, a, log10_c, omega, log10_tau, log10_d,
gamma, rho`) plus `beta`; see `GLOSSARY.md` § ETAS for their roles. They are recorded as stored,
never re-parametrised.

## What is persisted

`save_fit` writes `baselines/etas/<region_id>/`:

- `fit_result.json` — the full `FitResult` (`contracts/fit-result.v0.json`);
- `parameters.json` — the parameter dictionary with `parameter_snapshot_hash`, `fit_cutoff`
  and model version, for humans;
- `diagnostics.json` — `iterations`, `n_target_events`, `n_source_events`, `n_hat_background`,
  `branching_ratio` (`etas.inversion.branching_ratio`; `null` with a note when undefined),
  `b_value`, `mc`, `mc_source`, window bounds, `training_max_origin_time`, `area_km2`,
  `runtime_s`, `at_bound` (parameters sitting on an inversion bound), the package `ranges`,
  `theta_0`, the etas commit.

`log_likelihood` is `null`: the package does not expose the full point-process log-likelihood at
convergence (its optimiser minimises the expected complete-data negative log-likelihood of the
EM step, which is not the same quantity). The diagnostics say so. `converged` is `true` when the
EM loop exited on its own tolerance with finite parameters; a non-converged fit is persisted but
`forecast()` refuses to use it.

### The snapshot hash

`parameter_snapshot_hash = rupture.domain.snapshot_hash(parameters)` — SHA-256 over
`key=repr(value)` lines sorted by key. `FitResult` validates it on construction, every
`ForecastGrid` carries it, and the schedule runner fails (`LeakageError`) if it changes between
windows without a logged refit at a declared boundary.

## Issuance semantics

`forecast(history, issue_time, horizon, *, n_simulations=100, seed=None)`:

1. Requires a loaded fit with `fit_cutoff ≤ issue_time` (otherwise `LeakageError`: the parameters
   would have seen data after the issue time).
2. `history` must be earthquakes only, every event with `mw ≥ Mc` and `origin_time < issue_time`.
   Violations raise; nothing is filtered silently. Events outside the polygon or depth range are
   dropped because the region defines the process.
3. The package state is rebuilt at `issue_time` with the stored parameters (no `invert()`;
   ADR-0018). The simulation's source catalogue is asserted to end before `issue_time`.
4. `n_simulations` continuations of the history over `[issue_time, issue_time + horizon)` are
   simulated with numpy's global generator seeded from `seed`.
5. Expected counts per cell and magnitude bin are formed as in ADR-0018: simulated triggered
   counts + analytic background term, times the analytic Gutenberg–Richter bin probabilities
   above the region threshold.

The grid's cells are the 0.1° lattice anchored at the polygon's bounding box, keeping cells whose
centre lies inside the polygon; magnitude bins come from `Region.magnitude_bin_edges()` (last bin
open). `ForecastGrid.id = <model>-<region>-<issue>-<horizon>`.

### Simulation count guidance

Only the triggered component is simulated. For a cell with triggered expectation λ per
continuation, the estimate after `n` continuations has relative standard error ≈ 1/√(nλ). With
the fixture (quiet California year, 30-day horizon) 100 continuations produce ~800 simulated
events above Mc and a total expected count of ~1.2 events at M ≥ 3.95, i.e. the *total* is known
to a few per cent but individual cells far from recent activity rest on 0–3 simulated events.
Guidance:

- gates and unit tests: 5–50 continuations (they check plumbing, not precision);
- protocol schedules: ≥ 1 000 continuations per issue time (minutes per window on a laptop for
  California-sized histories); record `n_simulations` and `seed` (both are on the grid and in
  the run log);
- when a cell's expected count matters (S-, L-tests on sparse regions), report the simulated
  event count from `ForecastGrid.notes` alongside.

Zero-rate cells: cells with no simulated triggered event and negligible background mass have
expected count 0. An observed event in such a cell makes the M/S/L/CL log-likelihood −∞; the
evaluator records that as a rejection (statistic = most negative finite float, `passed=false`)
rather than hiding it. More continuations shrink but do not remove this; it is the model's own
statement about far-field cells.

## Determinism and seeds

`seed` seeds `numpy.random` (the legacy global generator the package uses). Reproducibility holds
for the same history, parameters, `n_simulations`, region and package version; it does not hold
across the package's own entry points (`ETASSimulation.simulate` reseeds from OS entropy), which
rupture therefore does not use. Fits are reproducible through the fixed `theta_0`.

## Known limitations

- **Uniform background in the fit, smoothed in the forecast.** The inversion estimates a spatially
  constant μ; the package's forecast (and rupture's analytic form of it) places background near
  past background events. flETAS (`free_background`) would fit a spatially varying μ and is not
  enabled in Prompt 1.
- **Constant Mc.** `mc` is one number per fit. Time- or space-varying completeness (`mc='var'`)
  is supported by the package and not wired here; the protocol's regions assume the published
  regional Mc.
- **Sparse regions.** With few primary-window targets the background-location law rests on a
  handful of points and the branching ratio carries wide uncertainty; the diagnostics report
  `n_target_events` and `at_bound` so a reviewer can see it. A fit with zero primary-window
  targets cannot issue (the background law is undefined) and says so.
- **Parameters fixed within windows** (protocol § 6): a large sequence inside a window is
  forecast with pre-sequence parameters. The fixture shows this: fitted to mid-2019, the model
  puts ~1.2 events at M ≥ 3.95 on the 30 days that contain Ridgecrest (123 observed); the N-test
  fails, as it should.
- **No log-likelihood** (see above).
- **Optional dependency shim** for `etas.simulation` (`_etas_compat.py`, ADR-0018).
- **Test fixture magnitudes are reported, not homogenised Mw.** `tests/fixtures/forecasting/`
  labels them `reported-as-mw:<type>`; production goes through `rupture catalog build`.
