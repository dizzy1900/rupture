# Glossary

rupture does not predict earthquakes. This glossary fixes the vocabulary used in the code, the
contracts and the documentation. Where a term has a settled meaning in the CSEP or engineering
seismology literature, rupture uses that meaning; the references at the end are the sources.

CSEP's full name contains a word this repository bans; it is referred to by acronym throughout.
It is the international collaboratory that runs prospective, likelihood-based tests of earthquake
forecasts in independent testing centres (Schorlemmer et al. 2007, 2018).

## Forecast, and what rupture is not

**Forecast** — A statement of the *rate* (expected number) or *probability* of events of a given
magnitude class in a given space–time cell, issued at a stated *issue time* for a stated
*horizon*, computed only from information available before the issue time. Forecasts are
probabilistic and are scored against what subsequently happened. rupture issues forecasts.

**Prediction** — A deterministic statement that a specific event (time, place, magnitude) is
going to happen.
Deterministic prediction of the time, place and magnitude of individual earthquakes has no scientifically accepted method.
rupture makes no statement of this kind, its outputs carry no such field, and
`make validate-language` fails the build if the word appears outside the allowlisted sentences.

**Early warning** — Alerting people in the seconds between rupture onset (detected by
seismometers) and the arrival of strong shaking at their location. It is an engineering
capability of real-time seismic networks (EEW systems), not a forecast. rupture is not an EEW
system, ingests no real-time waveform data and issues nothing on a seconds timescale.

## Catalogues and completeness

**Catalogue** — A list of seismic events with origin time, hypocentre, magnitude(s) and source
agency. In rupture a `Catalog` also carries completeness metadata, spatial/temporal bounds and a
per-event homogenisation log.

**Magnitude of completeness (Mc)** — The lowest magnitude above which (essentially) all events in
a space–time volume are detected and catalogued. Below Mc the catalogue is incomplete and a
Gutenberg–Richter fit is biased. rupture estimates Mc per region with two methods and reports both
in `CompletenessEstimate`:

- **Maximum curvature (MAXC)** — the magnitude bin with the highest event count in the
  non-cumulative frequency–magnitude distribution (Wiemer & Wyss 2000). MAXC tends to
  underestimate Mc, so rupture applies the +0.2 correction recommended by Woessner & Wiemer
  (2005) and records that it did so.
- **b-value stability** — the lowest cut-off magnitude from which the b-value estimated on
  successively higher cut-offs stays within its uncertainty over a run of bins (Cao & Gao 2002;
  operationalised in Woessner & Wiemer 2005).
- **mc_ks (cross-check)** — a Kolmogorov–Smirnov goodness-of-fit test of the sample above a
  candidate Mc against a discrete Gutenberg–Richter distribution, accepting the lowest candidate
  whose p-value exceeds a threshold (Mizrahi et al. 2021; `etas.mc_b_est.estimate_mc`). Used as
  a third opinion, not as the published Mc.

Each estimate is a `CompletenessEstimate` (`mc`, `method` from `McMethod`
`{maximum_curvature, b_value_stability, mc_ks}`, `b_value` and its uncertainty, `n_events`, the
window, and the additive `correction` applied, e.g. `0.2`). The two published methods should agree
to within about one bin; if they do not, the disagreement is reported, not averaged away. Mc can
vary in time (network upgrades) and space (station density); a single regional Mc is a
simplification the `Region` record makes explicit (`Region.mc` is `null` until a catalogue has
been built).

**Region** — A named polygon (exterior ring of longitude/latitude pairs) with a depth range, a
tectonic setting tag, the forecasting grid definition (`cell_size_deg`, default 0.1), the
protocol target threshold (`target_min_magnitude`), the magnitude binning
(`magnitude_bin_width` 0.1 up to `magnitude_max` 8.95) and the fitted `mc`. Stored under
`data/regions/<id>/`.

**Gutenberg–Richter (GR) relation** — log10 N(≥M) = a − bM: the number of events with magnitude
≥ M falls off exponentially with M. The a-value measures productivity of the volume; the
**b-value** is the slope (globally near 1, so ten times as many M ≥ 4 as M ≥ 5). rupture fits
b above Mc by maximum likelihood (Aki–Utsu, with the binning correction of Tinti & Mulargia as
implemented in the `etas` package).

**Declustering** — Removing dependent events (aftershocks, swarms) from a catalogue to leave an
approximately Poissonian "background" set. rupture does **not** decluster before an ETAS fit:
ETAS models the clustering explicitly and estimates the background rate μ as part of the fit, so
removing clusters first would bias every triggering parameter. Declustering *may* be used as a
diagnostic when estimating Mc or a long-term background rate for PSHA input, and if used it is
logged as a homogenisation step.

**Homogenisation** — Bringing events from several source catalogues onto one magnitude scale
(Mw), one hypocentre convention and one identity (removing duplicates that different agencies
report for the same event). Every homogenisation step is logged per event
(`HomogenisationLogEntry`): which source won, which duplicates were merged and with which time
and distance window (Weatherill, Pagani & Garcia 2016), which magnitude conversion was applied
and its citation.

**Magnitude types** —

| Code | Meaning | rupture treatment |
|---|---|---|
| Mw | Moment magnitude | the target scale |
| mww, mwc, mwb, mwr | Mw from W-phase, centroid moment tensor, body-wave or regional moment tensor inversion (USGS codes) | accepted as Mw, type retained |
| mb | Short-period body-wave magnitude (saturates ≈ 6–6.5) | converted to Mw (Scordilis 2006; Di Giacomo et al. 2015 as the ISC-GEM option) |
| Ms | Surface-wave magnitude (saturates ≈ 8) | converted to Mw (Scordilis 2006; Di Giacomo et al. 2015) |
| ML | Local (Richter) magnitude | converted with a region-flagged relation; method reference stored on the event |
| Md | Duration magnitude | converted with a region-flagged relation, or left as `mw_homogenised = null` if no relation is available |

`MagnitudeType` also carries `mlv` and `other` for scales outside this table. The conversion
method reference is stored on every event as `mw_conversion` in the form
`<relation>:<from_type>` (for example `identity:mwc`, `scordilis2006:mb`); an event whose
magnitude could not be homogenised keeps `mw = null` and `mw_conversion = null` rather than a
guess, and the homogenisation log records `magnitude_unconvertible`.

**Event type** — ComCat classifies entries by `type`: `earthquake`, `landslide`, `explosion`,
`quarry blast`, `ice quake` and others. rupture maps these to `EventType`
`{earthquake, landslide, explosion, other}`, **retains** non-earthquake entries in the catalogue
with their tag (e.g. `us7000tbwb`, a `landslide`-type M5.2 entry in Nepal on 2026-08-26) and
excludes them from ETAS fits and evaluation targets by filter, reporting how many were excluded.

**Provenance** — The record attached to every ingested row: `source`, `source_url`,
`retrieved_at` (UTC), `sha256` of the payload the row was cut from, `licence`, `adapter_version`.
Fixtures carry a `provenance.json` with the same fields.

## ETAS

**ETAS (Epidemic-Type Aftershock Sequence)** — A marked point-process model in which every event
is either "background" (Poisson in time, spatially heterogeneous) or "triggered" by an earlier
event, with triggering that decays with time (Omori–Utsu) and distance and grows exponentially
with the triggering magnitude (Ogata 1988, 1998; Zhuang, Ogata & Vere-Jones 2002). It is the
operational baseline in CSEP-style experiments (Werner et al. 2011) and rupture's F1 baseline.

**ETAS parameters (Mizrahi parametrisation)** — rupture uses the `etas` package of Mizrahi et al.
(2021 SRL, 2021 JGR), whose conditional intensity for a target at time distance t and squared
epicentral distance r² from a source of magnitude m is, up to normalisation,

```
λ(t, r² | m) = k0 · exp(a (m − Mc)) · exp(−t/τ) / (t + c)^(1+ω) · 1 / (r² + d · exp(γ (m − Mc)))^(1+ρ)
```

plus a background term μ. Parameter roles (values are fitted per region and published in
`FitResult.parameters` under `baselines/etas/<region>/`; none are quoted here):

| Symbol | Package name | Role |
|---|---|---|
| μ | `log10_mu` | background rate (events per unit area per day) |
| k0 (k) | `log10_k0` | productivity: expected number of direct aftershocks from an event at Mc |
| α (a) | `a` | exponential growth of productivity with triggering magnitude |
| c | `log10_c` | Omori–Utsu time offset regularising the early-time singularity |
| p = 1 + ω | `omega` | Omori–Utsu temporal decay exponent |
| τ | `log10_tau` | exponential taper of the time kernel at long times |
| d | `log10_d` | spatial scale of the triggering kernel at magnitude Mc |
| γ | `gamma` | growth of spatial scale with triggering magnitude |
| ρ | `rho` | spatial decay exponent |

The package stores several parameters in log10 space; the `ForecastModel` adapter records them as
stored in `FitResult.parameters`, and `parameter_snapshot_hash` is computed from that dictionary
(see below).

**FitResult** — What a model learned from a catalogue up to a hard cutoff, and how well:
`model_id`, `model_version`, `region_id`, `fit_cutoff` (only events with
`origin_time < fit_cutoff` were used), `training_start`, `training_catalog_hash`, `n_events`,
`mc`, `parameters`, `parameter_snapshot_hash`, `log_likelihood`, `diagnostics`, `converged`,
`fitted_at`. Persisted under `baselines/<model>/<region>/` and exported as
`contracts/fit-result.v0.json`.

**Background rate (μ)** — The spatially varying Poisson rate of events that are not triggered by
any earlier event in the catalogue. Estimated inside the ETAS fit, not by declustering.

**Fit diagnostics** — Log-likelihood at convergence, number of EM iterations, convergence flag,
number of events used, fit-window bounds, the Mc used, and the estimated b-value. Published with
every fit (non-negotiable 3). A fit that did not converge is reported as such, never used
silently.

## Evaluation

**Prospective** — The forecast was issued and archived *before* the target period began, so no
knowledge of the outcome could have influenced it. The gold standard (Schorlemmer et al. 2007).

**Pseudo-prospective** — The forecast is computed after the fact but using **only** data with
origin time before the issue time, replaying history as if the model had been running. This is
what rupture's evaluation schedule does. It is honest only if the leakage rules below hold and
the model's *design* (not just its parameters) was fixed without looking at the target period.

**Retrospective** — The model is fitted and evaluated on overlapping data, or the design was
tuned after seeing the outcomes. Useful for development, never for skill claims. Random k-fold
cross-validation on an earthquake catalogue is retrospective in disguise: aftershocks of a
"training" event fall into the "test" fold, and vice versa, so skill is inflated by the
clustering the model is supposed to forecast.

**Leakage** — Any path by which information from at or after the issue time reaches a fit or a
forecast: a fit catalogue that extends past the cutoff, a target slice starting before the issue
time, a re-fit inside a window that was not logged, a magnitude conversion calibrated on future
events, an Mc chosen by looking at the target period. rupture asserts against each of these in
tests on real catalogue timestamps (`docs/EVALUATION_PROTOCOL.md` § Leakage rules).

**Issue time** — The UTC instant at which a forecast is (or is treated as) issued. Everything the
model sees has `origin_time < issue_time`; the target slice is `[issue_time, issue_time + horizon)`.

**Horizon** — The length of the forecast window (1 d, 7 d, 30 d, 365 d in rupture). The
protocol horizon is 30 d.

**ForecastGrid** — rupture's gridded forecast: for a `region_id`, square cells of
`cell_size_deg` given by their lower-left `cell_origins`, magnitude bins given by their lower
`magnitude_bin_edges` (last bin open), an `issue_time` and a `horizon`, the `expected_counts`
per cell per bin (finite, non-negative), together with `model_id`, `model_version`,
`parameter_snapshot_hash`, `fit_cutoff`, `training_catalog_hash` and `n_simulations`. Its id is
`<model>-<region>-<issue_time>-<horizon>`. Serialised as zarr with a STAC item; convertible to a
pycsep `GriddedForecast`.

**Parameter snapshot hash** — `rupture.domain.forecast.snapshot_hash(parameters)`: the SHA-256
of the sorted `key=repr(value)` lines of the parameter dictionary a forecast was issued from.
`FitResult` validates that its hash matches its parameters. It must be constant across every
window of a schedule unless a refit at a declared boundary is logged; a change anywhere else is a
leakage finding.

**N-test (number test)** — Compares the total forecast count with the observed count under the
forecast's Poisson (or simulated) distribution; two-sided (Zechar, Gerstenberger & Rhoades 2010).

**M-test (magnitude test)** — Tests the forecast magnitude distribution against the observed one,
normalising away the total count (Zechar et al. 2010).

**S-test (spatial test)** — Tests the forecast spatial distribution against the observed
epicentres, normalising away the total count (Zechar et al. 2010).

**L-test (likelihood test)** — Tests the joint space–magnitude likelihood of the observed
catalogue under the forecast against simulated catalogues (Schorlemmer et al. 2007).
**CL-test (conditional likelihood test)** — the same conditioned on the observed number of
events, removing the N-test's influence (Werner et al. 2011).

**Paired T-test** — Compares two forecasts on the same target catalogue by the mean per-event
difference in log-likelihood, with a Student-t confidence interval (Rhoades et al. 2011).
**W-test** — the non-parametric Wilcoxon signed-rank counterpart (Rhoades et al. 2011). Both
are implemented in pycsep (Savran et al. 2022).

**Information gain per event (IGPE)** — The mean over target events of the difference in
log-likelihood between a challenger and the baseline; the T-test's statistic. Positive means the
challenger assigned more probability to what happened.

**EvaluationResult** — One test outcome: `forecast_id`, `model_id`, `test_name` (`TestName`
`{N, M, S, L, CL, T, W}`), `statistic`, `quantile` (one-sided tests) or `quantile_low` /
`quantile_high` (two-sided N-test) or `p_value`, `alpha`, `passed` (`null` when the test could
not be decided, e.g. no target events), `benchmark_model_id` for T/W, `n_target_events`,
`n_simulations`, the target window, `target_catalog_hash` (the frozen slice's
`Catalog.event_hash()`), `evaluated_at`, `evaluator_version`.

## Hazard and risk

**PSHA (probabilistic seismic hazard analysis)** — The computation of the probability that a
ground-motion intensity measure exceeds a level at a site within an investigation time, by
integrating over all sources, magnitudes, distances and ground-motion variability. rupture's F0,
via the OpenQuake engine (Pagani et al. 2014).

**GMPE / GSIM** — An empirical model of the distribution of a ground-motion intensity measure
given magnitude, distance, site and mechanism. OpenQuake calls it a ground-shaking intensity model
(GSIM); the older acronym GMPE expands to a phrase containing a banned word, so rupture uses
**GSIM** throughout the code and documentation and writes "GMPE" only as the bare acronym.

**IML (intensity measure level)** — A value of an intensity measure type (e.g. PGA in g,
SA(1.0 s) in g, PGV in cm/s).

**PoE (probability of exceedance)** — The probability that the intensity measure exceeds a given
IML at a site within the investigation time.

**Investigation time** — The exposure period of a hazard statement (e.g. 50 years).

**Hazard curve** — PoE as a function of IML at one site for one intensity measure type and one
investigation time. A `HazardCurveSet` is the set of curves for many sites and one logic-tree
realisation or statistic (mean, quantile).

**Logic tree** — OpenQuake's enumeration of epistemic alternatives: source-model branches and
GSIM branches with weights.

**Exposure** — The assets at risk: location, taxonomy (structural type), replacement value,
occupants. An `ExposurePortfolio` in rupture.

**Fragility function** — Probability of reaching or exceeding a damage state given an IML.
**Vulnerability function** — Distribution of loss ratio given an IML.
**Consequence function** — Loss ratio (or casualties, downtime) given a damage state. Fragility
plus consequence composes to vulnerability.

**Expected loss** — The mean loss to a portfolio for a scenario (one rupture) or over an
event-based stochastic event set, with an uncertainty interval. A `LossResult`.

**Intervention** — A change to the portfolio (retrofit, relocation, insurance layer,
evacuation plan) whose effect is expressed as a modified exposure/fragility set.

**Avoided loss** — Expected loss without the intervention minus expected loss with it, with an
interval. `AvoidedLossRequest` (a `portfolio`, a `trigger_kind` in `{scenario, forecast, hazard}`
with its `trigger_id`, optional `horizon`, `loss_types`, `interventions`, `interval_level`) and
`AvoidedLossResponse` (`status`, `baseline` `LossResult`s, one `InterventionOutcome` per
intervention with `avoided_expected` and `avoided_interval`, `model_ids`, `provenance`) form
rupture's public output contract for any downstream decision layer, shipped as one envelope
`{request, response}` in `contracts/avoided-loss.v0.json`. The computation is Prompt 2; the
contract is published now and `rupture underwriting-check` round-trips the example request.

**Scenario risk** — Loss for one specified rupture (magnitude, geometry, GSIM). Needs no
time-dependent forecast. **Event-based risk** — Loss statistics over a stochastic event set
sampled from a source model over an investigation time; annualised.

## Cascades

**Ground failure** — Secondary hazards triggered by shaking: **landslide** (slope failure) and
**liquefaction** (loss of strength in saturated granular soil). rupture's F3 uses the USGS
ground-failure models (Nowicki Jessee et al. 2018 for landslides; Zhu et al. 2017 for
liquefaction) as published products and as re-runnable models.

**Co-seismic ice avalanche** — A glacier or ice-cliff failure triggered by shaking; a mass
movement that can enter a catalogue as a seismic event.

**SourceTypeAssessment** — The file-level contract shared with `serac`'s discriminator: for a
catalogued event (`event_id`, `source_catalog`), the probabilities `p_mass_movement`
(landslide, ice avalanche, rockfall), `p_tectonic` and `p_other`, summing to 1, with the
`classifier_id`/`classifier_version`, human-readable `evidence` and numeric `features` used.
Interface and fixtures only in Prompt 1 (`contracts/source-type-assessment.v0.json`;
example in `tests/contract/fixtures/serac/`).

## Data formats

**GeoParquet** — Apache Parquet with geometry columns and standardised geospatial metadata; the
storage format for catalogues and fault databases.

**zarr** — Chunked, compressed N-dimensional arrays with a JSON metadata layer; the storage
format for `ForecastGrid` payloads (cell × magnitude bin × horizon) via xarray.

**STAC (SpatioTemporal Asset Catalog)** — A JSON specification for cataloguing geospatial assets
by space, time and links; rupture writes one STAC item per issued forecast via pystac.

**DVC (Data Version Control)** — Git-adjacent versioning for large files: `data/raw`,
`data/interim`, `data/catalogs`, `data/forecasts` and `baselines/` are DVC-tracked, with
`.dvc` pointers and `dvc.yaml` stages in git and payloads in a remote.

## References

- Cao, A. & Gao, S. S. (2002). Temporal variation of seismic b-values beneath northeastern Japan island arc. *Geophysical Research Letters*.
- Danciu, L. et al. (2021). The 2020 update of the European Seismic Hazard Model (ESHM20): model overview. EFEHR Technical Report; and Danciu, L. et al. (2024), *Natural Hazards and Earth System Sciences*.
- Di Giacomo, D. et al. (2015). ISC-GEM: Global Instrumental Earthquake Catalogue (1900–2009), III. Re-computed MS and mb, proxy MW, final magnitude composition and completeness assessment. *Physics of the Earth and Planetary Interiors*.
- Ekström, G., Nettles, M. & Dziewoński, A. M. (2012). The global CMT project 2004–2010: centroid-moment tensors for 13,017 earthquakes. *Physics of the Earth and Planetary Interiors*.
- Mizrahi, L., Nandan, S. & Wiemer, S. (2021). Embracing data incompleteness for better earthquake forecasting. *Journal of Geophysical Research: Solid Earth*.
- Mizrahi, L., Nandan, S. & Wiemer, S. (2021). The effect of declustering on the size distribution of mainshocks. *Seismological Research Letters*.
- Nowicki Jessee, M. A. et al. (2018). A global empirical model for near-real-time assessment of seismically induced landslides. *Journal of Geophysical Research: Earth Surface*.
- Ogata, Y. (1988). Statistical models for earthquake occurrences and residual analysis for point processes. *Journal of the American Statistical Association*.
- Ogata, Y. (1998). Space–time point-process models for earthquake occurrences. *Annals of the Institute of Statistical Mathematics*.
- Pagani, M. et al. (2014). OpenQuake engine: an open hazard (and risk) software for the Global Earthquake Model. *Seismological Research Letters*.
- Rhoades, D. A. et al. (2011). Efficient testing of earthquake forecasting models. *Acta Geophysica*.
- Savran, W. H. et al. (2022). pyCSEP: a Python toolkit for earthquake forecast developers. *Seismological Research Letters*.
- Schorlemmer, D. et al. (2007). Earthquake likelihood model testing. *Seismological Research Letters*.
- Schorlemmer, D. et al. (2018). The CSEP achievements-and-priorities paper. *Seismological Research Letters* (title contains a banned word and is not reproduced here).
- Scordilis, E. M. (2006). Empirical global relations converting MS and mb to moment magnitude. *Journal of Seismology*.
- Storchak, D. A. et al. (2013). Public release of the ISC-GEM Global Instrumental Earthquake Catalogue (1900–2009). *Seismological Research Letters*; and Storchak, D. A. et al. (2015), *Physics of the Earth and Planetary Interiors*.
- Styron, R. & Pagani, M. (2020). The GEM Global Active Faults Database. *Earthquake Spectra*.
- Weatherill, G. A., Pagani, M. & Garcia, J. (2016). Exploring earthquake databases for the creation of magnitude-homogeneous catalogues: tools for application on a regional and global scale. *Geophysical Journal International*.
- Werner, M. J. et al. (2011). High-resolution long-term and short-term earthquake forecasts for California. *Bulletin of the Seismological Society of America*.
- Wiemer, S. & Wyss, M. (2000). Minimum magnitude of completeness in earthquake catalogs: examples from Alaska, the western United States, and Japan. *Bulletin of the Seismological Society of America*.
- Woessner, J. & Wiemer, S. (2005). Assessing the quality of earthquake catalogues: estimating the magnitude of completeness and its uncertainty. *Bulletin of the Seismological Society of America*.
- Zechar, J. D., Gerstenberger, M. C. & Rhoades, D. A. (2010). Likelihood-based tests for evaluating space–rate–magnitude earthquake forecasts. *Bulletin of the Seismological Society of America*.
- Zhu, J., Baise, L. G. & Thompson, E. M. (2017). An updated geospatial liquefaction model for global application. *Bulletin of the Seismological Society of America*.
- Zhuang, J., Ogata, Y. & Vere-Jones, D. (2002). Stochastic declustering of space-time earthquake occurrences. *Journal of the American Statistical Association*.
