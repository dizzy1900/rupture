# ADR-0042: Stochastic event sets from F1, and expected annual loss

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)
- **Extends:** ADR-0024 (damage decomposition), ADR-0025 (intervention models and scenarios)

## Context

Prompt 2 delivered a scenario loss layer: pick a rupture, price a portfolio, report what a measure
avoids. That answers a what-if. It does not answer the question an underwriter, an insurer or a
public-finance decision-maker actually asks, which is what a *year* costs and how bad the bad year
is. A scenario loss cannot become a premium, a benefit-cost ratio or an expected payout on an
insurance layer, because it carries no rate.

Two things were missing and they are the same thing. The brief asked for **expected annual loss**,
and it asked for **stochastic event sets sampled from the promoted F1 model** with the avoided-loss
intervals coming from them. An annual figure needs a rate-carrying event set; the event set is
where the intervals come from. Building them separately would have produced two modules that
happened to agree, or more likely did not.

Before this ADR, `risk.scenarios.from_stochastic_event` was a constructor with no caller outside
its own tests, `TriggerKind.FORECAST` returned `status = not_implemented`, and the `--forecast`
flag on `rupture risk run` was a documented dead end. The reported "90 % intervals" were quantiles
over GSIM aleatory realisations of a *single rupture the user chose*, which is a legitimate
quantity but not the one the brief asked for and not one that widens with event-set uncertainty.

## Decision

### 1. An event set is sampled from a `ForecastGrid`, and carries rates

`rupture.risk.event_set.sample_from_forecast_grid` draws whole synthetic catalogues from a
promoted F1 forecast. Each catalogue covers `catalogue_duration_years` (one year by default), and
each sampled event carries an occurrence rate of `1 / (n_catalogues * duration)` per year. The
total rate of the set is then the grid's own rate, and every downstream annual number is arithmetic
on it.

Four sampling choices, each named in `StochasticEventSet.assumptions` on **every** set produced,
so a reader never has to open the source to find them:

1. **Poisson occurrence per cell per magnitude bin.** This reproduces an ETAS grid's expected
   counts exactly and *understates* the variance of a clustered process, so the tail of the
   aggregate exceedance curve is tighter than the underlying process. Recorded, not hidden.
2. **Rates outside the grid's own horizon are the same rates.** Scaling a 30-day ETAS forecast to a
   year states "if this rate persisted", which for a decaying aftershock sequence it will not. The
   scaling factor is reported on the set and repeated in the response.
3. **Uniform location within a cell**, which is the finest thing the grid resolves.
4. **Point ruptures at one stated depth** (15 km, the USGS hypocentral depth for the 2015 Gorkha
   mainshock, marked assumed). ADR-0025 refused to manufacture a fault plane from a magnitude and
   that refusal stands here: distances are therefore longer than a finite rupture of the same
   magnitude would give, and the resulting loss is a **lower** estimate.

Magnitudes within a bin follow a Gutenberg-Richter density truncated to the bin, using the
**region's fitted b-value** where a `Region` is supplied (1.138 for `nepal-himalaya`, Aki 1965 MLE
from the region's own Mc estimate) and a stated assumed b = 1.0 otherwise. Which was used is on
the set.

Events below a threshold (default M 5.0) are not sampled: at 15 km depth they produce ground
motion far below the lowest fragility median in the library, and they would dominate the run time.
This makes the annual loss a lower estimate by an amount a caller can bound by lowering the
threshold and re-running. A `max_events` guard raises rather than truncating silently.

### 2. Expected annual loss, and what its interval is

`rupture.risk.event_based.run_event_based` prices every event of the set through the same
exposure, ground-motion and vulnerability chain the scenario path uses, and reduces to:

- **AAL** = sum over events of rate x expected loss, the expectation taken over the GSIM's
  aleatory realisations;
- an **aggregate exceedance curve** (AEP) from the catalogue-year totals — the rate at which the
  *total loss in a year* exceeds a level;
- an **occurrence exceedance curve** (OEP) from every (event, realisation) pair weighted by its
  rate — the rate at which a *single event* exceeds a level.

The interval on the AAL is a **percentile bootstrap of the mean over the synthetic
catalogue-years**: it is how well the event set pins the number down, and it is *not* the spread of
annual loss. Those are different quantities and conflating them is the standard way an annual-loss
figure misleads: the annual loss distribution here has a point mass at zero covering most years,
so its 5th percentile is zero and its 95th is a number no one should read as a confidence bound.
The spread of annual loss is what the exceedance curves are for. The `basis` string on every AAL
figure says this in full, and a test asserts the sentence is there.

Neither curve is reported beyond the return period the event set resolves
(`n_catalogues * duration`). Extrapolating past it would be reading a 1000-year loss off the single
worst of 120 sampled years.

### 3. Branches share catalogues and realisations

ADR-0025's rule — every branch priced on one ground-motion field, the same realisations in the
same order — is carried into the event-based path: every branch sees the same events, and the
catalogue aggregation draws the **same** realisation index per event for every branch. Avoided
annual loss is then the catalogue-by-catalogue difference, bootstrapped the same way.

### 4. `TriggerKind.FORECAST` is answered; `HAZARD` still is not

`avoided_loss.respond` routes a forecast trigger through the event set and returns
`status = ok` with `baseline_total` as the expected loss **per horizon window** — per year unless
the request names a different `horizon`. The `basis` on every money figure says which window it
is, because a per-year figure and a per-event figure in the same field would be the most damaging
ambiguity this contract could carry.

`TriggerKind.HAZARD` still returns `not_implemented`, with a message that now names exactly what
is missing: a long-term (F0) source model for the corridor. The engine-side machinery to consume
one exists (ADR-0043); the model does not.

### 5. The offline fixture is a real slice

`tests/fixtures/risk/forecast/trishuli-corridor-slice.json` is the 156 cells of a **real issued
`ForecastGrid`** — `etas-mizrahi-nepal-himalaya-20260801T000000Z-365d`, from the ETAS baseline
fitted with a hard cutoff at 2022-01-01 — that lie in a box around the Trishuli corridor, with
their expected counts carried through unchanged. It is a real slice, not a synthesised grid, per
the repository's fixture rule, and its `provenance.json` records the parent grid, its fit cutoff,
its parameter snapshot hash and the fact that a slice's rate is a fraction of the region's.

## Consequences

- The forecasting half of rupture can now change a loss number. That was the point of having one.
- The corridor has an annual figure: **USD 4.42 M/yr** (0.29 % of portfolio value) from the real
  1-year ETAS grid, with the exceedance curve in `docs/RISK.md`. Every caveat above applies to it,
  and it is a lower estimate for at least four stated reasons.
- Leakage: an event set adds no information the forecast did not already have. The grid's
  `fit_cutoff` is carried onto the set and into its provenance so a reviewer can check it, and a
  test asserts it is there.
- The Poisson assumption means the AEP tail is optimistic. An ETAS-clustered event set (drawing
  from `etas.simulation` rather than from the binned expected counts) would fix it and is the
  obvious next step; it needs the forecasting adapter to expose simulated catalogues, which it
  does not today.

## Alternatives considered

- **Compute AAL only through OpenQuake's `event_based` calculator.** Rejected as the *only* route:
  the engine cannot run on this project's machine (arm64), so the headline deliverable would have
  no number. Both routes are built (ADR-0043); the native one runs.
- **Report the annual-loss spread as the AAL interval.** Rejected: it is [0, 0] for a portfolio
  whose damaging years are rare, which would read as a precise zero rather than as a skewed
  distribution.
- **Interpolate a loss-ratio lookup table for speed.** Rejected: `rupture.risk.curves` is the
  vectorised *restatement* of the scalar damage chain and a test asserts the two agree to
  floating-point noise. An approximation would have needed a tolerance nobody could justify.
- **Sample a finite fault plane for large sampled magnitudes.** Rejected for now: it needs a
  magnitude-area scaling relation and a fault-attachment rule, neither of which this pass
  verified. The consequence — losses are a lower estimate — is stated everywhere instead.
