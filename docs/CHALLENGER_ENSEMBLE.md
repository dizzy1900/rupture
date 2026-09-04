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

Read this section sceptically. The ensemble is the component of this work most likely to look good,
and in one of the two regions it does beat the baseline by the protocol's own criteria. What
follows is the evidence, the mechanism, and the checks that were run to try to make the result go
away.

**Headline: not promoted.** The ensemble meets both promotion conditions in `turkiye-eaf` and
neither of them in `nepal-himalaya`. Protocol § 10 needs both conditions in at least two of the
three test regions; one region is not two, and `california` was not run at all.

### Pass rates, 30-day horizon, 55 windows per region

| Region | Model | N | M | S | L | CL |
|---|---|---|---|---|---|---|
| `nepal-himalaya` | ETAS baseline | 51/55 (0.93) | 21/22 (0.95) | 16/22 (0.73) | 17/22 (0.77) | 19/22 (0.86) |
| `nepal-himalaya` | gridded (C1b) | 49/55 (0.89) | 21/22 (0.95) | 19/22 (0.86) | 13/22 (0.59) | 21/22 (0.95) |
| `nepal-himalaya` | **ensemble** | 50/55 (0.91) | 21/22 (0.95) | 19/22 (0.86) | 15/22 (0.68) | 21/22 (0.95) |
| `turkiye-eaf` | ETAS baseline | 50/55 (0.91) | 27/29 (0.93) | 20/29 (0.69) | 26/29 (0.90) | 25/29 (0.86) |
| `turkiye-eaf` | gridded (C1b) | 49/55 (0.89) | 28/29 (0.97) | 21/29 (0.72) | 20/29 (0.69) | 23/29 (0.79) |
| `turkiye-eaf` | **ensemble** | 54/55 (0.98) | 27/29 (0.93) | 25/29 (0.86) | 26/29 (0.90) | 27/29 (0.93) |

### Paired comparison against ETAS, pooled over the schedule

| Region | target events | information gain per event | 95 % interval | t | pooled W-test p | beats ETAS |
|---|---|---|---|---|---|---|
| `nepal-himalaya` | 66 | **-0.0789** | [-0.3461, +0.1883] | -0.590 | 0.791 | no |
| `turkiye-eaf` | 217 | **+0.3354** | [+0.2671, +0.4037] | 9.680 | 2.99e-17 | yes |

Per window, as pycsep computes it, the picture is much less decisive because most windows cannot
decide the test at all: `nepal-himalaya` 1 win and 8 losses over the 9 decidable windows,
`turkiye-eaf` 2 wins and 8 losses over 10, with the W-test winning no individual window in either
region. The pooled test is the one the promotion rule's wording asks for; the per-window counts are
here so the reader can see how thin each window is.

### Fitted weights

| Region | w_etas | w_gridded | floor_fraction | validation windows | validation target events | validation log-likelihood |
|---|---|---|---|---|---|---|
| `nepal-himalaya` | 0.41 | 0.59 | 1e-06 | 24 | **9** | -104.122 |
| `turkiye-eaf` | 0.79 | 0.21 | 1e-06 | 24 | **27** | -235.704 |

Nine target events decided that the challenger should carry the majority of the weight in
`nepal-himalaya`. That is not enough evidence for a weight, and the region where the weight was
fitted on the thinner evidence is the region where the ensemble then failed.

### Promotion decision

Protocol § 10, applied:

- `turkiye-eaf`: condition 1 **met** — N 0.98 ≥ 0.91, M 0.93 = 0.93, S 0.86 ≥ 0.69, L 0.90 = 0.90,
  over 55 consecutive windows. Condition 2 **met** — pooled information gain +0.335 per event with
  a 95 % lower bound of +0.267; the pooled W-test agrees. Promotable in this region.
- `nepal-himalaya`: condition 1 **not met** (N 0.91 < 0.93, L 0.68 < 0.77); condition 2 **not met**
  (gain -0.079, interval spans zero). Not promotable here.
- `california`: **not run**, and — as things stand — not runnable to a pass. Condition 1 compares
  the challenger's pass rates against ETAS's *over the same schedule*, and California's published
  ETAS schedule is 6 windows, half of the 12 consecutive windows condition 1 requires (it was
  stopped deliberately; `RELEASE_STATUS.md` says why and that it is resumable). Until that
  schedule is extended, no model can pass there, whatever it scores.

**Condition 3 requires both conditions in at least two of the three regions. One of three regions
passed, one failed, and one was not evaluated. The ensemble is recorded as not promoted.**

This is the one place in the project where an unevaluated region could have mattered: one pass plus
a second from California would be two of three. It could not have happened with a 6-window
baseline, and `make validate-challengers` says so mechanically rather than leaving a reader to work
it out — it recomputes the whole rule from the committed evidence, names `california` as not
evaluated, and states whether running it could have changed the verdict.

The reading of condition 2 used here — one paired T-test pooled over the schedule — is the one
ADR-0040 settled on for every challenger, after finding that the neural challenger was being judged
under a per-window-majority reading of the same sentence. Under the per-window reading Türkiye's
2 wins in 10 decidable windows would not meet condition 2 and this region would fail as well. The
ADR argues the choice from the protocol's wording and from the power of a test on a window holding
one or two events, and records that it does not change any published verdict: with or without
Türkiye, one region is not two.

### What the ensemble is actually doing

The gridded component is, in operation, a near-static smoothed climatology: its total expected
count moves by 4.4 % over the month in which ETAS's moves by a factor of 56 (see
`CHALLENGER_GRIDDED.md` § 6). With a second component that barely moves, the log-linear pool is
close to **tempering** the baseline: raising ETAS's rate field to the power `w_etas` and
renormalising, with the climatology's spatial pattern blended in at weight `1 - w_etas`. Tempering
flattens the dynamic range of a rate field, and blending in a smoothed-seismicity field broadens
it spatially.

In `turkiye-eaf`, every window where the ensemble and the baseline disagree on a test, and the
direction:

| Issue date | Targets | ETAS expected | Ensemble expected | Test flipped |
|---|---|---|---|---|
| 2022-07-30 | 1 | 0.43 | 0.43 | S: fail → pass |
| 2023-02-25 | 12 | 25.16 | 10.79 | N and CL: fail → pass |
| 2023-03-27 | 2 | 12.61 | 6.26 | N and S: fail → pass |
| 2023-05-26 | 1 | 7.42 | 4.11 | N: fail → pass |
| 2023-06-25 | 0 | 6.24 | 3.58 | N: fail → pass |
| 2024-07-19 | 2 | 1.26 | 1.01 | S: fail → pass |
| 2024-09-17 | 1 | 1.10 | 0.90 | CL: fail → pass |
| 2025-02-14 | 1 | 0.92 | 0.78 | S: fail → pass |
| 2026-05-10 | 2 | 0.80 | 0.70 | S: fail → pass |

There is no Türkiye window in which the ensemble fails a test the baseline passes. The N-test flips
are all in the months after the 2023 Kahramanmaraş doublet, where this ETAS fit over-forecasts the
aftershock total by factors of two to six and the geometric shrinkage brings it back toward the
observed count.

`nepal-himalaya` shows the other side of the same coin: seven windows differ, and three of them go
against the ensemble. Shrinking toward a low climatology helps when the baseline over-forecasts
(2023-10-23, 2025-03-16, 2025-05-15: S and CL flip to pass) and hurts when the baseline was closer
to right (2025-02-14: 6 observed against ETAS 2.36 and ensemble 0.88, N flips to fail; 2023-12-22
and 2023-10-23: L flips to fail).

So the Türkiye gain is a **calibration correction to this baseline fit on this schedule**, not new
information about where or when earthquakes occur. It would be a mistake to read it as a deep
model contributing skill: what is in the pool is a smoothed-seismicity climatology, and hybrids of
ETAS with smoothed seismicity performing well is a long-standing CSEP finding rather than a
discovery here.

### Checks run to try to make the result go away

**Is it the zero-rate floor?** No. Across both regions and all 283 target events, **zero** events
fell in a cell-magnitude bin that either the ETAS floor or the ensemble's own floor had raised. In
the schedule's dominant window (`turkiye-eaf` 2023-01-26, 160 target events) every one of the 160
events sat in a cell where both components had a real rate, and the ensemble's rates there were a
geometric mean of 1.31 times ETAS's.

**Would any diffuse second component do?** Mostly not. Refitting and rescoring the pool with the
challenger's spatial field flattened to uniform — total and magnitude distribution unchanged, so
the ablation is pure tempering — gives:

| Region | w_etas | w_uniform | pooled gain per event | 95 % interval | ensemble's own gain |
|---|---|---|---|---|---|
| `nepal-himalaya` | 0.43 | 0.57 | -0.198 | [-0.460, +0.064] | -0.079 |
| `turkiye-eaf` | 0.99 | 0.01 | +0.032 | [+0.028, +0.036] | +0.335 |

In `turkiye-eaf` the uniform field is worth about a tenth of the real ensemble's gain, and the
weight fitting on the validation block rejects it outright (`w_uniform = 0.01`). The spatial
pattern of the smoothed climatology, not the pooling arithmetic, carries most of the gain.

**Is it one sequence?** Partly, and the number is:

| Region | total gain (nats) | largest window | its share | its targets | pooled gain per event without it |
|---|---|---|---|---|---|
| `nepal-himalaya` | -5.2 | 2025-02-14 | 1.21x | 6 | +0.019 [-0.236, +0.272] |
| `turkiye-eaf` | +72.8 | 2023-01-26 | 0.59x | 160 | +0.528 [+0.357, +0.699] |

The Kahramanmaraş window contributes 59 % of the Türkiye total. Removing it entirely *raises* the
pooled gain per event rather than removing it, because the ensemble also wins in the aftershock
windows through the count correction. So the Türkiye result is not one window — but it is one
region, and that region's schedule is dominated by one sequence.

**Are the target events independent?** No, and this is the weakest part of the evidence. The pooled
Student-t interval treats 217 target events as independent when most of them belong to one
aftershock sequence. The interval is therefore narrower than the evidence warrants and the p-value
is not a p-value in any defensible sense; read the pooled test for the sign and rough size of the
gain and nothing more. pycsep's own per-window paired test has the same problem at smaller scale,
and it is the test the protocol names.

**Is it the same targets?** Yes. The 55 scored windows have identical issue times and identical
target counts to the published ETAS schedule in both regions. The baseline used five parameter
snapshots over the schedule (four yearly refits); the challenger used one.

**How does the honest gain compare with what leakage would buy?** The leaky ablation in
`CHALLENGER_GRIDDED.md` § 6 buys 2.16 nats per event of apparent skill in `turkiye-eaf` — about six
and a half times the ensemble's honest +0.335. That is the scale of the thing the leakage
discipline is protecting against.

## 6. Limitations

- **The weights rest on very little.** They are fitted on 24 windows containing 27 target events in
  `turkiye-eaf` and **9** in `nepal-himalaya`. Nine events decided that the challenger should carry
  0.59 of the weight in Nepal, and Nepal is where the ensemble then failed. A weight fitted on that
  evidence is not a statement about which model is better.
- **One region is not a result.** The ensemble met both promotion conditions in `turkiye-eaf` and
  neither in `nepal-himalaya`, and the Türkiye schedule is dominated by one sequence. Two regions
  disagreeing is the most likely single explanation of the Türkiye number, and the protocol's
  two-of-three rule exists precisely so that one region cannot promote a model.
- **The pooled test overstates its own confidence.** Its Student-t interval assumes independent
  target events; most of Türkiye's 217 are one aftershock sequence. Read the sign and the rough
  size, never the p-value.
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
