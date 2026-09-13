# Model card — `one-neuron-logistic` (mandatory spatial aftershock comparator)

**implemented; not scored on the 116 CSEP windows in this PR.**

DeVries et al. 2018 Nature doi 10.1038/s41586-018-0438-y reported AUC 0.849 on aftershock
location — `rebutted`; Mignan & Broccardo 2019 Nature 574 E1–E3 doi 10.1038/s41586-019-1582-8
matched it with two-parameter logistic AUC 0.85 — `contested`, and Meade et al. Reply Nature 574
E4–E5 doi 10.1038/s41586-019-1583-7 is on the record. Independently, a three-parameter logistic
on log distance-to-rupture and log mean slip reached 0.86. Those figures are not a win for
DeVries and are not recomputed here.

| | |
|---|---|
| Model id | `one-neuron-logistic` (sibling `distance-slip-logistic`) |
| Version | `0.1.0` |
| Type | two-parameter logistic occupancy on log10 distance-to-nearest `mw >= m_main` event; optional third parameter on log10 mean slip when a finite-fault field is supplied |
| Role | **mandatory comparator** for spatial aftershock / static-stress classification claims (ADR-0059), not a challenger and not an operational model |
| Promotion status | **not scored** — no protocol windows, no area skill, no information gain. This card is not machine-read by `make validate-challengers` |
| Licence | Apache-2.0 (this repository) |
| Owner | rupture contributors |
| Written | 2026-09-13 (UTC) |
| Documentation | `docs/COMPARATOR_ONE_NEURON.md` |

## Out of scope

- **Forecasting individual earthquakes deterministically.** Out of scope, permanently.
- Reporting AUC or accuracy. There is no `auc` method. Use `rupture.scoring.refusals`.
- Real-time alerting of any kind.
- A result on the 116 CSEP windows, the three protocol regions, or any published schedule. That
  comparison has not been run.

## What it does

Given a catalogue and a hard cutoff, it fits a Bernoulli logistic on the region's lattice:
positives are cells that hosted an event with `origin_time < cutoff` and `mw` at or above the
target threshold. It then issues a `ForecastGrid` of **expected counts**, converting occupancy
`P` by the training-only rule

`expected_count = P * (n_events / n_positive_cells) * (horizon_days / training_days)`.

The AlarmSet helper `alarm_from_logistic` turns a fitted logistic and a declared alarm fraction
`tau` into an `AlarmSet` of the highest-P cells whose **clustering-aware** reference mass equals
`tau`. A uniform Poisson reference is refused.

## Training data

Unit tests fit on the committed ComCat California fixture
(`tests/fixtures/forecasting/comcat-california-2018-2019-m3.geojson`, USGS, public domain) in a
Ridgecrest box after the M7.1, and on the committed Gorkha 30-day slice paired with the USGS NEIC
finite-fault table (`tests/fixtures/risk/scenarios/gorkha2015/complete_inversion.fsp`). Those fits
exist so the leakage assertions fire on real timestamps. They are not results.

No data was synthesised. No data from after a model's cutoff reached it.

## How it should be evaluated (not yet run)

AlarmSet arm: Molchan trajectory, area skill score, probability gain `G` at a pre-declared `tau`,
against a clustering-aware ETAS reference and a random alarm set matched on alarm rate and
spatial footprint. See `docs/COMPARATOR_ONE_NEURON.md`.

A spatial ML model that has not been scored against this comparator has not been scored.
