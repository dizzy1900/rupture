# Baseline results — the ETAS pseudo-prospective schedule

**These are scores, not skill claims.** A "pass" means a CSEP-style consistency test did not
reject the forecast at α = 0.05. rupture does not predict earthquakes; it issues rate forecasts
and reports how they scored. The protocol that fixed every choice below — regions, thresholds,
grid, horizons, tests, significance levels, schedule and leakage rules — was written before any
model in this repository was fitted (`EVALUATION_PROTOCOL.md`, 2026-09-03) and is unchanged by
these results.

Run on 2026-09-03 with `rupture evaluate schedule`: one forecast every 30 days from
`2022-01-01T00:00:00Z` to `2026-08-01T00:00:00Z`, horizon 30 days, 1000 ETAS continuations per
forecast, 1000 simulations per test, seed 20220101, refits yearly on 1 January (4 per region,
each logged). California is reported separately below: its schedule was stopped after six windows for a
stated reason, not abandoned quietly.

All three leakage rules held in every window: the model saw only events before the issue time,
each target slice lay inside its window, and the parameter snapshot hash changed only across a
logged refit boundary.

## Pass rates

| Region | Issued | Scored | Refits | N | M | S | L | CL |
|---|---|---|---|---|---|---|---|---|
| `nepal-himalaya` | 55 | 55 | 4 | 51/55 (0.93) | 21/22 (0.95) | 16/22 (0.73) | 17/22 (0.77) | 19/22 (0.86) |
| `turkiye-eaf` | 55 | 55 | 4 | 50/55 (0.91) | 27/29 (0.93) | 20/29 (0.69) | 26/29 (0.90) | 25/29 (0.86) |

The N-test denominator is every evaluated window. M, S, L and CL are decided only where the window
held at least one target event (protocol § 5); those windows are recorded as N-test only, never
silently dropped. The spatial test is the weakest in both regions, which is the expected place for
a uniform-background ETAS fit to lose: it distributes background seismicity by a smoothed law
rather than by mapped faults.

## `nepal-himalaya` — M ≥ 4.7

66 target events over 55 windows; 33 windows held none. The five busiest windows:

| Issue date | Targets | Expected | N | M | S | L | CL |
|---|---|---|---|---|---|---|---|
| 2024-12-16 | 22 | 0.61 | **fail** | **fail** | **fail** | **fail** | **fail** |
| 2023-09-23 | 7 | 0.59 | **fail** | pass | pass | **fail** | pass |
| 2025-02-14 | 6 | 2.36 | pass | pass | pass | **fail** | pass |
| 2022-07-30 | 4 | 0.57 | **fail** | pass | pass | **fail** | pass |
| 2022-10-28 | 4 | 0.63 | **fail** | pass | pass | **fail** | pass |

## `turkiye-eaf` — M ≥ 4.6

217 target events over 55 windows; 26 windows held none. The five busiest windows:

| Issue date | Targets | Expected | N | M | S | L | CL |
|---|---|---|---|---|---|---|---|
| 2023-01-26 | 160 | 0.45 | **fail** | **fail** | **fail** | **fail** | **fail** |
| 2023-02-25 | 12 | 25.16 | **fail** | pass | **fail** | pass | **fail** |
| 2023-04-26 | 7 | 9.05 | pass | pass | pass | pass | pass |
| 2023-07-25 | 5 | 5.34 | pass | pass | **fail** | pass | **fail** |
| 2023-11-22 | 3 | 3.39 | pass | pass | pass | pass | pass |

## `california` — M ≥ 3.95, six windows of a planned 55

California's fit converged (55,828 events at Mc 2.70; 94 minutes of EM) and its schedule ran the
first six 30-day windows at full protocol settings before being stopped:

| Issue date | Targets | N | M | S | L | CL |
|---|---|---|---|---|---|---|
| 2022-01-01 | 4 | pass | pass | pass | pass | pass |
| 2022-01-31 | 1 | pass | pass | pass | pass | pass |
| 2022-03-02 | 2 | pass | pass | pass | pass | pass |
| 2022-04-01 | 2 | pass | pass | pass | pass | pass |
| 2022-05-01 | 1 | pass | pass | pass | pass | pass |
| 2022-05-31 | 2 | pass | pass | pass | pass | pass |

Thirty of thirty tests passed. Six quiet windows are not evidence of skill and must not be read as
such; they are consistent with a well-calibrated background rate over a quiet half-year, and the
test that matters is a window containing a sequence, which these do not.

**Why it stopped.** Issuance cost grows with the conditioning history, and California's is
55,828 events above Mc 2.70 against Nepal's 772. The first window took 12 minutes; by the sixth it
was over an hour, putting the remaining 49 windows at an estimated **35–60 hours of one core**.
That was judged not worth the machine time when the acceptance criterion is one closed window per
region and the six completed windows already characterise the quiet-period behaviour. The run is
resumable: the schedule is idempotent per window (results are keyed by target-catalogue hash), so
restarting it re-uses these six and continues.

### What the busiest windows show

The Türkiye row for 2023-01-26 is the 2023 Kahramanmaraş doublet: 160 target events against 0.45
expected, and every test rejects. That is the correct result, not a defect. The forecast for that
window was issued on 2023-01-26 from parameters fitted to data ending 2023-01-01, and no
time-dependent seismicity model claims to anticipate a mainshock; ETAS forecasts the *rate* of
events given the history, and the history held no such sequence. A model that had passed this
window would be evidence of leakage, not of skill.

What the model does do is visible in the windows that follow it: 12 observed against 25.2
expected, then 7 against 9.1, then 5 against 5.3 — the aftershock decay tracked to
ratios of 2.1, 1.3 and 1.1 against observation, which is what the ETAS baseline is for and what any challenger in Prompt 2 has to beat.

Nepal's busiest window (2024-12-16, 22 targets against 0.6 expected) is the same story on a
smaller sequence.
