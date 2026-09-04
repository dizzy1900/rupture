# Model card — `ntpp-neural-hawkes` (challenger C1a)

**rupture does not predict earthquakes.** This model issues expected event counts per grid cell
per magnitude bin over a fixed horizon. It makes no statement about the time, place or magnitude
of any individual future earthquake, and no such statement can be derived from its output.

| | |
|---|---|
| Model id | `ntpp-neural-hawkes` |
| Version | `ntpp-0.1.0+torch-2.14.0` |
| Type | marked spatio-temporal Hawkes process with neural kernel shapes |
| Role | **challenger** to the ETAS baseline (`etas-mizrahi`), not an operational model |
| Promotion status | **not promoted** — in either region it was run on (`turkiye-eaf`, `nepal-himalaya`); `california` was never fitted. Evidence in `docs/CHALLENGER_NTPP.md` and `reports/protocol/<region>/eval/`. This row is machine-read by `make validate-challengers`, which recomputes protocol section 10 from that evidence (ADR-0040) and fails if the card and the rule disagree |
| Licence | Apache-2.0 (this repository) |
| Owner | rupture contributors |
| Written | 2026-09-03 (UTC) |

## Out of scope

- **Forecasting individual earthquakes deterministically.** Out of scope, permanently, and not a
  limitation that more data or a bigger network would remove. There is no scientifically accepted
  method for it and this model does not attempt one.
- Real-time alerting of any kind. This model has no streaming path and no alerting output;
  its shortest supported horizon is one day, and rupture is not a rapid-alert system.
- Ground motion, damage, loss, or any statement about a specific site or structure.
- Regions, magnitude thresholds, depths or grids other than those it was fitted and scored on. A
  fit is bound to one region record and refuses to load against another.
- Operational use. It is a challenger measured against a baseline; nothing in this repository
  issues its forecasts to anyone.

## What it does

Given a catalogue of past events and an issue time, it produces a `ForecastGrid`: the expected
number of earthquakes in each 0.1° cell, in each 0.1-wide magnitude bin, over the window
`[issue_time, issue_time + horizon)`. The grid and bins are the ones fixed in
`docs/EVALUATION_PROTOCOL.md`, identical to the ETAS baseline's, so the two are directly
comparable under pycsep.

The conditional intensity is a Hawkes process: a smoothed background rate plus a sum of triggering
contributions from every earlier event. What is learned rather than assumed is the *shape* of each
event's triggering kernel — a small MLP maps that event's magnitude and depth to mixture weights
over fixed Omori (temporal) and power-law (spatial) bases. Productivity keeps the ETAS exponential
form with a non-negative exponent. Magnitudes are marks drawn from a fitted Gutenberg-Richter law.

## Training data

The real homogenised regional catalogues built by `rupture catalog build`, at the protocol's own
hard cutoff of `2022-01-01T00:00:00Z`. Full detail in `docs/CHALLENGER_NTPP.md` § Data.

| Region | Catalogue events | Training events (M ≥ Mc, before the cutoff) | Mc | Target |
|---|---|---|---|---|
| `turkiye-eaf` | 7 038 | 405 | 4.3 | M ≥ 4.6 |
| `nepal-himalaya` | 2 728 | 772 | 4.4 | M ≥ 4.7 |

`california` was **not fitted**: 55 828 training events at Mc 2.7, and this implementation's
likelihood is O(targets × sources) per epoch. That is a limitation of the implementation, stated
rather than worked around, and it means the protocol's two-of-three-regions promotion condition
cannot be satisfied from this evidence even in principle.

A few hundred training events is a small set for any learned model, and every score for
`ntpp-neural-hawkes` should be read with that in front of it.

The committed fit under `tests/fixtures/models/ntpp-fit-2019-07-01/` is a separate, smaller fit of
the committed ComCat California fixture slice (`tests/fixtures/forecasting/`, USGS ComCat, public
domain); it exists so unit tests can exercise forecasting and persistence without training, and it
is not a result.

No data was synthesised. No data from after a model's cutoff reached it.

## Inputs and outputs

- **Input:** a `Catalog` of earthquakes with homogenised `mw ≥ Mc`, all with
  `origin_time < issue_time`; a `Region` record; an issue time and a horizon. Anything else is
  refused rather than filtered — a history containing a non-earthquake, an event below Mc, or an
  event at or after the issue time raises.
- **Output:** a `ForecastGrid` of non-negative expected counts, carrying the fit cutoff, the
  training catalogue hash and the parameter snapshot hash, so what the model saw is recoverable
  from the artefact.

## How it was evaluated

Through the same `PyCSEPEvaluator` and the same schedule machinery as the baseline: N-, M-, S-, L-
and CL-tests per window at α = 0.05, and the paired T- and W-tests against ETAS on identical
targets. The promotion rule is § 10 of the protocol and is applied mechanically by
`promotion_verdict`; passing a consistency test means "not rejected", never "skilful".

## Leakage controls

Every one is an assertion that raises, not a filter that hides:

- dataset builders refuse any event at or after the cutoff;
- feature windows are closed-left and open-right, so simultaneous events never trigger each other;
- cross-validation is blocked and time-forward, and the splitter API has no shuffle parameter;
- normalisation statistics are fitted on training rows only and travel with the model;
- hyperparameters are chosen on a validation window ending at or before the hard cutoff, and the
  chosen configuration is frozen with its hash before any test window is scored;
- the trained weights are hashed into `parameter_snapshot_hash`, so the schedule's existing
  snapshot-constancy check catches a silent retrain.

A deliberately leaky ablation is run and reported separately, so that the value of these controls
is a number rather than an assertion. On the two regions run, fitting the parameters on the whole
catalogue — target windows included — buys **+0.68 and +0.77 nats per target event** of apparent
information gain over ETAS, which on `nepal-himalaya` flips a clearly losing model into an
apparently winning one. **Ablation figures are never results** and are labelled
`ntpp-LEAKY-ABLATION-tuning` / `-fit` in every artefact they touch.

## Known limitations

- Small training catalogue (see above); parameter uncertainty is correspondingly wide and is not
  currently propagated into the forecast.
- **The productivity law presses its subcriticality constraint.** The model is parameterised so
  its branching ratio is always below 1 — unconstrained, maximum likelihood drove it supercritical
  on every catalogue tried — but the fitted value sits close to the ceiling, which means the
  productivity law is only weakly identified by these catalogues. The ETAS baseline's own
  `turkiye-eaf` fit is itself supercritical (1.044), so this is a property of the data as much as
  of the model.
- The triggering kernel is isotropic. Real aftershock clouds follow the ruptured fault, and this
  model has no way to express that; it is the most likely reason for its spatial scores.
- No finite-fault geometry, no anisotropy, no time-varying completeness, no magnitude dependence
  in the mark distribution.
- Edge effects are ignored: the spatial kernel's mass outside the region polygon is not
  redistributed in the likelihood. The background law is renormalised over the lattice at forecast
  time, so the two are consistent but both approximate near the boundary.
- The basis exponents are fixed, not learned, because they are not identifiable alongside the
  mixture weights at this sample size.
- Depth is used as a feature but the model is two-dimensional; it forecasts on a map, not in a
  volume.
- Behaviour for a mainshock larger than anything in training is bounded by feature clipping rather
  than learned. That is a deliberate safety property, and it means the model has nothing
  informative to say about such an event beyond the ETAS-form productivity law.
- **`california` was never fitted**, so this model was evaluated in two regions of the protocol's
  three. The likelihood is quadratic in event count and California's pre-cutoff slice holds 55,828
  events; the run was not attempted rather than approximated. It is recorded as an open gap in
  `RELEASE_STATUS.md`, and it is why condition 3 of the promotion rule was unreachable here — the
  verdict rests on two regions, both of which the model lost.
- **No number in this card is comparable to a published EarthquakeNPP figure.** The benchmark's
  conventions were followed where they apply (`docs/CHALLENGER_NTPP.md` § 2), but its seven
  datasets are all Californian, its horizon is rolling 24 hours against this protocol's 30 days,
  and its thresholds and split dates are its own. What agrees is the *finding* — a neural point
  process losing to ETAS, and losing on the spatial component. Nothing here belongs in its table,
  and a reader should not place it there.

## Ethical and practical considerations

This model must not be presented to any public, civil-protection or insurance audience as a
statement about individual earthquakes. Rate forecasts over cells and windows are useful for
comparing models and for aggregate planning; they are routinely misread as event-level
statements, and the misreading is the harm. Any downstream use should carry the horizon, the
magnitude threshold, the region, and the fact that the forecast was not rejected rather than shown
to be skilful.

## Reproducing it

```
uv run python -m rupture.commands.challenger ntpp select --region <r> \
    --from <utc> --validation-end <utc> --cutoff <utc>
uv run python -m rupture.commands.challenger ntpp fit --region <r> --cutoff <utc>
uv run python -m rupture.commands.challenger ntpp schedule --region <r> --from <utc> --to <utc>
```

(`rupture challenger ...` once `src/rupture/cli.py` registers the sub-app.) Fits are deterministic:
torch and numpy are seeded from the configuration, and a rerun reproduces the parameter snapshot
hash. The committed fixture fit is regenerated, never edited, by
`tests/fixtures/models/make_ntpp_fixture.py`.
