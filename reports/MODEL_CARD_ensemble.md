# Model card — the log-linear ensemble

**Version:** 0.1.0 (Prompt 2, challenger models)
**Model id:** `ensemble-loglinear`
**Date:** 2026-09-03
**Repository:** `github.com/dizzy1900/rupture`
**Full documentation:** [`docs/CHALLENGER_ENSEMBLE.md`](../docs/CHALLENGER_ENSEMBLE.md).
Decisions: [ADR-0032](../docs/adr/0032-log-linear-ensemble.md),
[ADR-0022](../docs/adr/0022-leakage-engineering-for-learned-models.md).

---

## What this is

A weighted geometric (log-linear) pool of the ETAS baseline and one or more challengers,
`log lambda_ens = sum_k w_k log lambda_k`, normalised, producing **expected counts of earthquakes
per 0.1-degree cell per 0.1-magnitude bin over a 30-day window** on the components' own lattice and
bins. The weights are fitted on a validation window strictly before the test period and on nothing
else. It is scored under the pre-registered protocol in `docs/EVALUATION_PROTOCOL.md`.

## Out of scope

- **Forecasting individual earthquakes deterministically.** rupture does not do this anywhere and
  this model does not either. It issues rates over cells and windows and has no statement to make
  about any single future earthquake.
- Any warning, alerting or notification function.
- Combining forecasts on different lattices or magnitude binnings. A mismatch between components is
  refused, never reconciled.
- Combining models whose fits reach past their issue time. That is refused too.
- Extrapolating the fitted weights to another region, another horizon or another component set.
  The weights are fitted per region on 24 validation windows and mean nothing outside that setting.

## Components in this run

| Component | Model | Fitted for the weight block | Used in the test period |
|---|---|---|---|
| `etas` | `etas-mizrahi` (Mizrahi et al., ADR-0009) | cutoff 2020-01-01, 1000 continuations | the declared protocol baseline, cutoff 2022-01-01 with yearly refits, read back from its own stored forecasts |
| `gridded` | `gridded-convlstm` (C1b, ADR-0031) | cutoff 2020-01-01 | cutoff 2022-01-01, no refits |

The NTPP challenger (C1a) is built on a sibling branch and is **not** in this pool; the component
list is a constructor argument, so adding it later changes one line.

## Inputs and outputs

Inputs are the components' `ForecastGrid`s plus, for weight fitting only, the observed target
catalogue slices of the validation windows. Output is a `ForecastGrid` carrying the weight fit's
`parameter_snapshot_hash` and naming every component's own snapshot hash in its notes.

## The two choices that change the numbers

- **Zero-rate floor.** Each component's rates are floored at
  `1e-6 * total / (n_cells * n_bins)` before the logarithm — relative to that component's own mean
  rate, so it means the same thing across regions and thresholds, and bounded, so it adds at most
  a millionth of that component's total. Fixed in advance; **not** tuned on any window.
- **Normalisation.** The pool is rescaled so the total is the weighted geometric mean of the
  components' totals. Without it a geometric pool of rate fields is not a rate forecast.

Both are argued in ADR-0032 and covered by unit tests.

## Scores

See `docs/CHALLENGER_ENSEMBLE.md` § 5 for the full tables, and
`reports/challenger/<region>/schedule-<region>-challengers.json` for every window.

**Not promoted.** Both promotion conditions are met in `turkiye-eaf` and neither in
`nepal-himalaya`; protocol § 10 requires two of three regions, and `california` was not run.

| Region | N | M | S | L | CL | pooled information gain per event vs ETAS | conditions met |
|---|---|---|---|---|---|---|---|
| `nepal-himalaya` | 0.91 (ETAS 0.93) | 0.95 (0.95) | 0.86 (0.73) | 0.68 (0.77) | 0.95 (0.86) | **-0.08** [-0.35, +0.19] | neither |
| `turkiye-eaf` | 0.98 (0.91) | 0.93 (0.93) | 0.86 (0.69) | 0.90 (0.90) | 0.93 (0.86) | **+0.34** [+0.27, +0.40] | both |

Fitted weights: `nepal-himalaya` 0.41 ETAS / 0.59 gridded on **9** validation target events;
`turkiye-eaf` 0.79 / 0.21 on **27**. The region whose weight rested on the thinner evidence is the
region where the ensemble failed.

**What the Türkiye gain is.** With a near-static second component the pool is close to tempering
the baseline, and the flips are all post-mainshock windows where this ETAS fit over-forecasts the
aftershock total by factors of two to six. It is a calibration correction to this baseline fit on
this schedule, not new information about where or when earthquakes occur, and what is in the pool
is a smoothed-seismicity climatology rather than anything the deep model learned.

**Checks:** the zero-rate floor raised no cell any of the 283 target events fell in; flattening the
challenger's spatial field to uniform drops the Türkiye gain from +0.335 to +0.032; removing the
dominant window raises rather than removes the gain; the pooled Student-t interval assumes
independent target events, which aftershocks are not, so read the sign and size and not the
p-value.

## Leakage controls

Weights are fitted only on windows that close at or before the test cutoff; a window that reaches
past it raises rather than warns. Every component forecast used for weight fitting must come from a
fit whose own cutoff is at or before its issue time; this is asserted per window. The test period
never touches the weights.

## Known limitations

Listed in full in `docs/CHALLENGER_ENSEMBLE.md` § 6. The load-bearing ones: the weights rest on 24
windows and a handful of target events per region; a geometric pool is intolerant of disagreement
by construction, which is what the floor bounds; and where the ensemble improves on the baseline's
count forecast it is doing so by shrinking the baseline toward a near-static climatology, which is
a calibration correction rather than new information.

## Ethical and operational notes

Research code scored against a baseline. Not an operational product; no statement about any
individual earthquake; nothing in its output is a warning. Under-claim: if a number is not in the
run report, it was not measured.
