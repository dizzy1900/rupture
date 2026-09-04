# Prompt 2 — candid summary

rupture does not predict earthquakes. This document says what an underwriter can use today, what
is research, and what needs partners. It under-claims deliberately; where a number rests on an
assumption, the assumption is named.

## What an underwriter can use today

**F0 + F2, the loss layer.** A portfolio, a scenario, expected loss and what an intervention
avoids — each as an interval with a stated basis and a named provenance. `make underwriting-check`
runs the sibling `serac` project's Trishuli corridor (14 hydropower assets, real capacities, real
sourcing) through a Main Himalayan Thrust M8.5 scenario and prints:

| | Figure |
|---|---|
| Expected loss | USD 675.2M [361.6–996.5M] |
| Retrofit avoids | USD 45.0M [32.2–54.5M] |
| Confidence | **low**, provenance **assumed** |

Two ground-motion models are implemented natively and **verified against OpenQuake's own published
test vectors**: the BC Hydro subduction-interface model reproduces 22,400 reference values to
within 5 parts in a billion (4.9e-07 %) with exact standard deviations, and BSSA14 to within 0.00067 % at its
tabulated periods (1.8 % worst case at interpolated ones, which is the same discrepancy OpenQuake
itself carries).

**What stops it being underwriting-grade, stated plainly:** 27 % of the loss rests on fragility
functions for which no published source was found — intake and penstock components are
parameterised and flagged `assumption: true`. All component value shares are assumed. The
replacement-value central estimate is sourced (IRENA 2024, USD 2,806/kW) but its ±40 % band is
judgement. And the active-crustal model cannot discriminate across this corridor, because the
corridor sits above a shallow thrust where its distance metric is zero at every site.

**C4, the operational aftershock service.** The one genuinely operational F1 product. Given a
mainshock it issues probabilities of further events by magnitude and horizon, refits as the
sequence evolves, and serves over an API. Validated pseudo-prospectively on Gorkha 2015 and
Kahramanmaraş 2023.

**What it does badly, and why:** it **under-forecasts the first day by three to twelve times**.
Every forecast issued at +1 hour and +1 day fails its consistency test low; it becomes consistent
by +7 days. The cause is structural, not a bug: early in a sequence the training slice is a decade
of quiet background plus a handful of events, so the fitted productivity is that of a quiet region.
Real operational earthquake forecasting uses generic multi-sequence parameters; rupture has none.
Issued at +1 hour, Kahramanmaraş gave a 7.2 % chance of M ≥ 6.8 within a day, and the M7.5 came
nine hours later — but Gorkha's M7.3 tail probability was flagged **inconsistent** in all three
windows.

**F3, the cascade layer** produces susceptibility and exposure, never a statement that a slope
will fail. Both USGS ground-failure models are implemented against the published operational
algorithm, with coefficients re-parsed from the USGS source at gate time so drift fails the build.

## What is research

**The challengers. None was promoted.** Three learned models — a neural temporal point process, a
gridded ConvLSTM, and a log-linear ensemble — were scored on the same 55 windows, with the same
issue times and the same target counts, as the published ETAS baseline. Full evidence in
`reports/CHALLENGER_EVALUATION.md`.

One metric was beaten: the ensemble's information gain in Türkiye, +0.335 nats per event. It was
attacked rather than banked. It survives a floor check, a spatial-flattening ablation and the
removal of the Kahramanmaraş window, but its confidence interval assumes independent events and
aftershocks are not independent, and what it actually corrects is a baseline that over-forecasts
aftershock totals by two to six times. That is worth having. It is not a discovery, and under the
promotion rule — two of three regions — it is not a promotion.

**The most useful number in Prompt 2 is from the leaky ablation.** Letting a fit see across the
cutoff buys between +0.31 and +2.16 nats per event depending on the model and region. On Nepal the
neural challenger's leak (+0.77) *flips the sign*: a model that honestly
loses to ETAS by 0.35 appears to win by 0.43, and its spatial pass rate moves from below the
baseline to above it. On Türkiye the same leak barely moves the pass rates while nearly tripling
information gain, so neither diagnostic catches it alone. Leakage arrives as good news, in the
region where the honest model is weakest, and it survives the checks a careful person would run.

## What needs partners

- **Open source models.** Türkiye has ESHM20, fetched and ready. **California and Nepal have no
  openly licensed model in OpenQuake's format that we could verify.** No probabilistic seismic
  hazard analysis has been run for any test region.
- **Exposure and vulnerability data.** No published hydropower-component fragility function and no
  Nepali cost breakdown was verified. This is the single largest source of assumption in the loss
  numbers, and it is the kind of thing an owner or a reinsurer has and a public repository does not.
- **Static covariates for ground failure.** Slope, lithology, land cover and topographic index were
  not sourced, so the ground-failure models run on shaking alone. Against the published USGS
  product for Gorkha this gives correlations of 0.45 (liquefaction) and 0.16 (landslide), both
  biased low. That is the honest measure of what rupture can compute today without them.
- **Generic aftershock parameters.** The fix for the first-day under-forecast is a multi-sequence
  parameter set, which is a data-sharing problem more than a modelling one.
- **An amd64 machine or CI.** OpenQuake cannot run on Apple Silicon in any form, so the container
  path is proved only in CI.

## The honest one-line version

The loss and cascade layers are useful today with their assumptions named; the aftershock service
is operational and knows where it is weak; and **the challengers did not beat ETAS**.
