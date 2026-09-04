# Evaluation protocol

**Written 2026-09-03, before any model in this repository has been fitted or any forecast
issued.** This document fixes the regions, thresholds, grid, horizons, tests, significance levels,
schedule, leakage rules and promotion rule *in advance*, so that no choice below can be tuned to
make a result look better. Changes to any numbered rule require an ADR that states what was known
at the time of the change. rupture does not predict earthquakes; this protocol is how it scores
the rate forecasts it does issue.

The protocol follows CSEP practice for gridded rate forecasts (Schorlemmer et al. 2007;
Zechar, Gerstenberger & Rhoades 2010; Werner et al. 2011; Rhoades et al. 2011; Schorlemmer et al.
2018) as implemented in pycsep 0.8.0 (Savran et al. 2022). Vocabulary is in `GLOSSARY.md`.

## 1. Test regions and parameters

| Region id | Polygon | Cell size | Target magnitude | Depth | Notes |
|---|---|---|---|---|---|
| `california` | the pycsep RELM California region (`csep.core.regions.california_relm_region`) | 0.1° | M ≥ 3.95 | ≤ 30 km | the CSEP reference region; thresholds are the RELM conventions; magnitude policy `network-preferred-as-mw` (ADR-0019 decision 2) |
| `nepal-himalaya` | Main Himalayan Thrust corridor polygon, approx. 80–89°E, 26.5–30.5°N (exact polygon in `data/regions/nepal-himalaya/region.geojson`) | 0.1° | M ≥ 4.7 | ≤ 70 km | includes the 2015 Gorkha sequence; sparse pre-2000 catalogue; threshold raised from the provisional 4.5 to the published b-value-stability Mc (ADR-0019 decision 1) |
| `turkiye-eaf` | East Anatolian Fault polygon, approx. 35.5–41.5°E, 36–39.5°N (exact polygon in `data/regions/turkiye-eaf/region.geojson`) | 0.1° | M ≥ 4.6 | ≤ 50 km | includes the 2023 Kahramanmaraş doublet; threshold raised from the provisional 4.0 to the published b-value-stability Mc (ADR-0019 decision 1) |

Rules:

1. Magnitudes are homogenised Mw (`GLOSSARY.md` § Magnitude types). Depth is hypocentral depth
   from the winning source after homogenisation.
2. The California threshold and depth are the RELM conventions and are not expected to change.
3. The Nepal and Türkiye thresholds were **provisional** (4.5 and 4.0) until the fitted Mc for
   each region was published in `data/regions/<region>/region.json` by `rupture catalog build`.
   The rule for setting them was: target threshold ≥ published Mc (maximum-curvature +0.2 and
   b-value stability must both be at or below the threshold). **That question is now closed.**
   The published Mc came in above both provisional values, so the thresholds rose to **4.7**
   (Nepal) and **4.6** (Türkiye) under ADR-0019, before any schedule was run. The provisional
   values are historical and appear nowhere in the scoring. Thresholds are never lowered below
   Mc, and are never changed after a schedule has started without an ADR.
4. Polygons are fixed at the time the first forecast is issued and stored with the region record.

## 2. Magnitude bins

Bins are 0.1 wide, starting at the region's target threshold and ending at 8.95; the last bin
(≥ 8.95) is open. Bin edges are inclusive at the lower edge, exclusive at the upper edge. The
same binning is used for the forecast (`ForecastGrid.magnitude_bin_edges`) and the target
catalogue; both come from `Region.magnitude_bin_edges()` (`target_min_magnitude`,
`magnitude_bin_width = 0.1`, `magnitude_max = 8.95`).

## 3. Horizons

| Horizon | Use |
|---|---|
| 1 d | issued and archived; scored where the target count allows |
| 7 d | issued and archived; scored where the target count allows |
| **30 d** | **the protocol horizon**: all pass rates, schedules and promotion decisions use it |
| 365 d | issued yearly at refit boundaries; scored as a long-window check |

A forecast window is `[issue_time, issue_time + horizon)`.

## 4. Tests and significance

All tests are the pycsep Poisson-forecast implementations (`csep.core.poisson_evaluations`).

| Test | Question | Statistic | Significance |
|---|---|---|---|
| N-test | is the total forecast count consistent with the observed count? | observed count vs. forecast Poisson distribution, two-sided | α = 0.05: pass iff the observed count lies within quantiles 0.025 and 0.975 |
| M-test | is the forecast magnitude distribution consistent with observed? | log-likelihood of observed vs. simulated magnitude distributions, count-normalised | α = 0.05, one-sided (low quantile fails); 1000 simulations |
| S-test | is the forecast spatial distribution consistent with observed? | log-likelihood of observed vs. simulated spatial distributions, count-normalised | α = 0.05, one-sided; 1000 simulations |
| L-test | is the joint likelihood consistent? | log-likelihood of observed vs. simulated catalogues | α = 0.05, one-sided; 1000 simulations |
| CL-test | as L-test, conditioned on the observed count | as L-test with simulated counts fixed to observed | α = 0.05, one-sided; 1000 simulations; reported alongside L |
| Paired T-test | does forecast A beat forecast B on the same targets? | mean per-event information gain with Student-t interval | α = 0.05; used for challenger vs. ETAS (Prompt 2) |
| W-test | non-parametric companion to the T-test | Wilcoxon signed-rank | α = 0.05; reported alongside T |

Each outcome is an `EvaluationResult`: one-sided tests fill `quantile`, the N-test fills
`quantile_low`/`quantile_high`, comparisons fill `p_value` and `benchmark_model_id`; `alpha`,
`n_simulations` and the seed are recorded so that the run is reproducible; the seed is recorded in `notes` as `{"seed": N}` (the domain model has no seed field). Passing a consistency test means "not rejected at α"; it is not evidence of skill.
Skill is only ever claimed from the paired comparison against ETAS.

## 5. Minimum target events

- The S-test and M-test require **at least one** target event in the window; with zero targets
  the count-normalised likelihoods are undefined.
- A window with zero target events records the **N-test only**: its M/S/L/CL results are written
  with `passed = null` and `n_target_events = 0` (never as a pass), the schedule report flags the
  window `n_only`, and it is excluded from S/M/L pass-rate denominators (it still counts in the
  N-test denominator).
- Pass rates are reported with their denominators (windows scored), never as bare percentages.

## 6. Pseudo-prospective schedule

| Item | Value |
|---|---|
| Training cutoff (first issue time) | `2022-01-01T00:00:00Z` |
| Issue cadence | every 30 days from the cutoff |
| Last issue time | the last issue time whose 30-day window closes at or before `2026-08-01T00:00:00Z` |
| Fit catalogue | events with `origin_time < cutoff` (or `< refit boundary`, see below) |
| Parameters within a window | fixed |
| Refits | only at declared boundaries; default **yearly on 1 January 00:00:00Z** (2023, 2024, 2025, 2026). A refit uses only events with `origin_time < boundary`. Every refit is logged (`refit` entry in the run log with the boundary, the new `parameter_snapshot_hash` and the fit catalogue hash). |
| Command | `rupture evaluate schedule --region <r> --model etas --from 2022-01-01T00:00:00Z --to 2026-08-01T00:00:00Z --step 30d` |

The schedule may also be run for 1 d and 7 d horizons at the same issue times; only the 30 d
results enter the pass-rate table used for promotion.

## 7. Leakage rules

Each rule is asserted by a test on real catalogue timestamps (`tests/unit`, fixtures cut from
real catalogues) and re-checked by `make validate-eval`. A negative test that injects a
post-cutoff event and expects failure is committed alongside.

1. Model input consists only of events with `origin_time < issue_time`.
2. The target slice is exactly `[issue_time, issue_time + horizon)` on `origin_time`.
3. The fit catalogue's maximum `origin_time` is strictly less than the cutoff (or refit boundary)
   it was fitted for.
4. `parameter_snapshot_hash` is constant across every window of a schedule unless a `refit`
   entry is logged at a declared boundary; any other change fails the schedule.
5. Mc, magnitude conversion relations and region polygons are fixed before the first issue and
   are not re-estimated using data from any target window.
6. **Random k-fold cross-validation is forbidden.** Earthquake catalogues are clustered in space
   and time; splitting them at random puts aftershocks of a training-fold mainshock in the test
   fold and vice versa, so the model is scored on events it has effectively already seen.
   Only time-forward splits with a hard cut are admissible.

## 8. Target catalogue

- Targets are drawn from the homogenised rupture catalogue for the region
  (`data/catalogs/<region>/`), produced by `rupture catalog build` with the documented source
  precedence and conversions.
- **Earthquakes only.** Entries with `event_type != earthquake` (for example ComCat
  `type=landslide`, such as `us7000tbwb`) are retained in the catalogue but excluded from targets.
  The number of excluded entries in each window is reported in the schedule output.
- Magnitude filter: homogenised Mw ≥ region threshold; depth filter as in § 1; spatial filter:
  epicentre inside the region polygon.

## 9. Catalogue revisions after issuance

Agencies revise magnitudes, locations and event types for months after an event. To keep results
reproducible:

- The target slice is **frozen at evaluation time**: its hash (`Catalog.event_hash()`, the
  SHA-256 over sorted event ids and origin times) is stored as `target_catalog_hash` on every
  `EvaluationResult`, together with `target_window_start`/`target_window_end`, and the slice
  itself is archived under `reports/eval/<forecast_id>/<hash12>/target.parquet`, where
  `hash12` is the first 12 characters of `target_catalog_hash`; the results for that slice are
  `reports/eval/<forecast_id>/results-<hash12>.json` and `latest.json` points at the newest.
- Re-evaluating an old forecast against a revised catalogue produces a new `EvaluationResult`
  with a new hash; the old one is not overwritten. Both are kept, and the schedule report names
  which catalogue build (by hash) each result used.

## 10. Promotion rule for challengers (Prompt 2)

A challenger model is promoted to "candidate operational" only if, on the 30 d protocol horizon,
over the same schedule and targets as the ETAS baseline:

1. it passes the N-, M-, S- and L-tests at a rate **≥ the ETAS pass rate** for each test over
   **≥ 12 consecutive 30-day windows**;
2. it beats ETAS in the paired T-test at α = 0.05 with **positive information gain per event**
   over those windows (the W-test is reported alongside and disagreement is flagged);
3. conditions 1 and 2 hold in **at least 2 of the 3** test regions.

Failing any condition means the challenger is recorded, with its results, as "not promoted".
There is no other route to promotion. The baseline's own pass rates are published in
`RELEASE_STATUS.md` whether or not they are flattering.

## 11. Reporting format

- `rupture evaluate run --forecast <id>` writes one `EvaluationResult` record per test (JSON,
  schema `contracts/evaluation-result.v0.json`) and a plot bundle (pycsep consistency and
  comparison plots as PNG) under `reports/eval/<forecast_id>/`, together with `target.parquet`.
- `rupture evaluate schedule ...` writes `reports/eval/schedule-<region>-<model>.json`: per window, the
  issue time, horizon, target count, excluded non-earthquake count, `parameter_snapshot_hash`,
  each test's statistic/quantile/pass, and the `n_only` flag; plus aggregates: pass rate per test
  with denominator, refit log, catalogue build hash, pycsep version, seed.
- `reports/` is ignored by default, but **the evidence behind published claims is committed**:
  `reports/protocol/<region>/eval/schedule-*.json` (the protocol runs, written with
  `--out reports/protocol/<region>`), `reports/challenger/<region>/` (the challenger schedules and
  the figures drawn from them), `reports/aftershock/` and the model cards. The per-forecast plot
  bundles and target slices under `reports/protocol/<region>/eval/<forecast_id>/` are committed
  too — 688 PNGs and 116 parquet slices — so a reader can check any single window rather than only
  the aggregate. What is *not* committed is anything regenerable that nothing published points at.

## 12. What this protocol cannot tell you

- **Short windows.** With 30-day windows and thresholds of M ≥ 4.6 (Türkiye) and M ≥ 4.7 (Nepal),
  many windows contain a handful of events or none — 33 of Nepal's 55 held no target event at all.
  Consistency tests on such windows have little power; a high pass rate there is weak evidence, and
  a window with no target event decides nothing and is excluded from the denominator rather than
  scored as a pass.
- **Sparse regions.** Pass rates for `nepal-himalaya` and `turkiye-eaf` are dominated by the
  aftershock sequences of Gorkha (2015, before the cutoff) and Kahramanmaraş (2023, inside the
  schedule). The schedule tells you how ETAS behaved in and around one large sequence per region,
  not how it behaves in general.
- **Nepal completeness.** The Nepal catalogue is thin before about 2000 and its completeness
  varies with network changes; that is why the threshold sits where it does. The published
  estimates are Mc 4.40 by maximum curvature (+0.2) and **4.70 by b-value stability**, against a
  4.7 target — the target is *at* the completeness limit, not comfortably above it. A further 596
  Nepal events are reported only as ML or Md, carry `mw = None` under the `strict` magnitude
  policy, and enter neither the Mc estimate nor any fit. ETAS parameters fitted there carry wide
  uncertainty, which the fit diagnostics report. See `docs/CATALOG_BUILD.md`.
- **No skill claim from consistency alone.** Passing N/M/S/L means the forecast is not rejected;
  it does not mean the forecast is useful. Only the paired comparison speaks to skill. The
  challengers now exist and have been scored under this protocol; none was promoted
  (`reports/CHALLENGER_EVALUATION.md`).
- **Nothing about individual events.** The protocol scores rates over cells and windows. It has
  no statement to make about any single future earthquake.

## References

See `GLOSSARY.md` § References for full entries: Schorlemmer et al. 2007 (SRL); Schorlemmer et
al. 2018 (SRL); Zechar, Gerstenberger & Rhoades 2010 (BSSA); Werner et al. 2011 (BSSA);
Rhoades et al. 2011 (Acta Geophysica); Savran et al. 2022 (SRL); Mizrahi et al. 2021 (SRL, JGR);
Wiemer & Wyss 2000 (BSSA); Woessner & Wiemer 2005 (BSSA); Cao & Gao 2002 (GRL).
