# ADR-0028 — Operational aftershock forecast service: sequence window, refit schedule, fixed b, Poisson summary

- **Status:** accepted
- **Date:** 2026-09-03

## Context

Component C4 is the one genuinely operational F1 product in rupture: given a mainshock, the
probability of at least one further event of magnitude at least *m* within 1, 7 or 30 days. It is
an F1 forecast conditioned on an observed sequence, so it is bound by the same rules as the
scheduled forecasts — leakage (`docs/EVALUATION_PROTOCOL.md` § 7), the ETAS baseline as a
first-class citizen (ADR-0009), fixed-parameter issuance (ADR-0018).

Four things had to be decided before any number could be issued, and each of them is a modelling
choice that changes the answer.

1. **Which events are "the sequence".** The domain model
   (`rupture.domain.AftershockForecast`) reports `n_sequence_events` and a `region_id`; neither is
   defined until a space–time window is.
2. **What the model is fitted on, and when it is refitted.** An ETAS fit on the first hour of a
   sequence has a handful of target events; a fit on years of regional seismicity is not
   sequence-specific. Both are wrong in different directions.
3. **Whether the Gutenberg–Richter b is estimated from the sequence.** Fitting it freely on the
   2023 Kahramanmaraş sequence at +1 d gave b = 0.76 and a branching ratio of 1.07 — a
   supercritical model whose stochastic continuations do not terminate. That is not a tuning
   nuisance; it is the model saying the sequence explodes.
4. **How a gridded rate becomes a probability.** The grid holds expected counts; the product is a
   probability.

## Decision

**1. Sequence window: a circle of `1.5 × L(M)` about the epicentre, from the mainshock time on.**
`L(M) = 10^(-2.44 + 0.59 M)` km is the subsurface rupture length of Wells & Coppersmith (1994),
Table 2A, all slip types; the radius is floored at 20 km and capped at 600 km. For M7.8 that is
218 km. The multiplier 1.5 is chosen because the epicentre can sit at one end of a unilateral
rupture: at `f = 1` the 2015-05-12 M7.3 Gorkha aftershock, 139 km from the M7.8 epicentre, would
sit within a few kilometres of the boundary. Gardner & Knopoff (1974) windows (about 89 km at
M7.8) are declustering windows, tuned to remove dependent events from a catalogue rather than to
bound where triggering occurs, and are too tight here. The window is fixed before any forecast is
issued and does not depend on where the aftershocks fell. Implementation:
`rupture.services.aftershock.window`.

**2. The zone is a `Region` that inherits everything from the published parent region.** Mc, the
target threshold, the depth range and the magnitude binning come from
`data/regions/<parent>/region.json` (`nepal-himalaya`, `turkiye-eaf`); only the polygon and the id
change. Nothing about what a forecast *means* is invented per sequence.

**3. Fit on the zone catalogue with a moving cutoff; refit at +1, 3, 6, 12 h then daily to +30 d.**
The training slice is every event in the zone with `origin_time < cutoff`: about a decade of
pre-mainshock seismicity, which supplies the auxiliary window and the background rate, plus the
sequence so far. As the sequence accumulates target events it dominates the fit, so the parameters
start as the zone's long-run parameters and become sequence-specific — the usual operational
shape (generic parameters first, sequence-specific parameters later), reached by moving the ETAS
cutoff rather than by introducing a second model. Before the first scheduled refit the service
uses a fit cut at the mainshock time, i.e. purely pre-mainshock parameters. rupture writes no
second ETAS: this is `MizrahiETAS` (ADR-0009) with a different training slice.

**4. `beta` is fixed to the parent region's published long-run b; simulated magnitudes are capped
at `Region.magnitude_max`.** Short-term aftershock incompleteness biases a sequence-specific b
low, and a low b inflates the large-magnitude tail; see the Kahramanmaraş failure above. With b
fixed at the published value (1.138 for `nepal-himalaya`, 1.026 for `turkiye-eaf`) every fit in
`docs/AFTERSHOCK.md` is sub-critical (branching ratio 0.35–0.85). `FitResult.diagnostics`
records `beta_fixed`, so a reader can always tell.

**5. `P = 1 - exp(-lambda)`, stated as an assumption everywhere the number appears.** `lambda` is
the expected count above the threshold summed over the whole grid. The formula is exact only for
a Poisson process; ETAS clusters, so the real count is over-dispersed and `1 - exp(-lambda)`
**over-states** P(at least one) whenever `lambda` is not small. The assumption is named in the
module docstring, in `AftershockForecast.notes` on every issued forecast, in the API description,
in `docs/AFTERSHOCK.md` and in `reports/MODEL_CARD_aftershock.md`. It is not corrected silently.

**6. Validation is pseudo-prospective on two real sequences at +1 h, +1 d and +7 d**, scoring
every horizon whose window closed inside the catalogue's coverage, with the existing
`PyCSEPEvaluator` for the gridded forecast and a Poisson count check for each rung of the ladder.
Results, including the poor ones, are in `docs/AFTERSHOCK.md` and `reports/aftershock/`.

**7. The HTTP surface is a self-contained FastAPI application** with `GET /healthz` and
`POST /aftershock/forecast`, authenticated by an `X-API-Key` header and nothing else. With no key
configured the forecast route answers 503 rather than serving open. It mounts nothing; whoever
assembles the deployment can mount it alongside the avoided-loss service.

## Consequences

- The published probabilities are conditional on a 218 km circle for an M7.8. A user who cares
  about a specific site must read the gridded `ForecastGrid`, not the zone-wide ladder.
- Because b is fixed, the service cannot report a sequence-specific b, and a sequence whose true b
  really differs from the regional value will be mis-forecast in the tail. The alternative was
  worse (see above), and the diagnostics say which was done.
- Fixing the window before the fact means the validation numbers are honest, and it also means
  the zone is too big for some sequences and too small for others. It is one number for every
  mainshock of a given magnitude.
- The gate uses committed fits (`tests/fixtures/aftershock/fits/`) because six EM fits take about
  four minutes. The gate checks that each fit's `training_catalog_hash` recomputes from the
  committed slice, so a fit cannot drift away from its data unnoticed.
- The service reads its offline catalogues from `tests/fixtures/aftershock/`, following the
  precedent of `rupture.validation._fixture`. When `data/catalogs/<region>/` exists in a full
  clone, `rupture aftershock forecast --catalog <dir> --region <file>` uses it instead.

## Alternatives considered

- **Fit ETAS on the sequence alone.** At +1 h that is a handful of events with no auxiliary
  window; the EM has nothing to estimate a background rate from and the productivity is
  unconstrained. Rejected.
- **Generic aftershock parameters in the manner of Reasenberg & Jones (1989) / van der Elst &
  Page (2018), fitted across many sequences.** This is what operational aftershock forecasts
  usually do, and it is very likely the right answer for the early hours — the results in
  `docs/AFTERSHOCK.md` show the regional-ETAS fit under-forecasting the first day by about an
  order of magnitude. It is not done here because rupture has no multi-sequence parameter set and
  the brief says to use the existing ETAS. Recorded as the main known weakness rather than
  quietly worked around.
- **A time-varying Mc(t) after the mainshock** (Helmstetter, Kagan & Jackson 2006). Correct, and
  it would raise the early expected counts. Not implemented; the fixed regional Mc is used and
  the resulting bias is stated.
- **A negative-binomial or simulation-based probability instead of Poisson.** The stochastic
  continuations already sampled would support an empirical P(at least one). Not done, so that the
  probability is a stated closed form the reader can check; the direction of the error is
  documented.
- **Reusing the parent region polygon as the forecast region.** Simpler, but the ladder would
  then be a probability for the whole Himalayan or East Anatolian corridor, not for the sequence.
  Rejected.
