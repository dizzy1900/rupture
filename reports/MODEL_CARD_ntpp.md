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
| Status | **not promoted.** See `docs/CHALLENGER_NTPP.md` for the evidence |
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

The full detail, including the caveat that matters most, is in `docs/CHALLENGER_NTPP.md` § Data.
In short: the DVC-tracked regional catalogues (`data/catalogs/<region>/`) were **not present in
this worktree**, so the model was fitted on the committed real ComCat fixture slice
(`tests/fixtures/forecasting/comcat-california-2018-2019-m3.geojson`, USGS ComCat, public domain)
— 1 433 earthquakes, M ≥ 3.0, 2018-01-01 to 2019-12-28, in a rectangle around southern California.
Two years of catalogue is a small training set for any learned model, and every score in this
repository for `ntpp-neural-hawkes` should be read with that in front of it.

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
is a number rather than an assertion. **Ablation figures are never results** and are labelled
`ntpp-LEAKY-ABLATION` in every artefact they touch.

## Known limitations

- Small training catalogue (see above); parameter uncertainty is correspondingly wide and is not
  currently propagated into the forecast.
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
