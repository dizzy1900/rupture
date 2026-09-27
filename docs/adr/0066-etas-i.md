# ADR-0066 — ETAS-I: a declared Mc(t), an opt-in inversion, and a fit that is not a forecast

- **Status:** accepted
- **Date:** 2026-09-10 (UTC)
- **Implements:** [ADR-0059](0059-reference-baseline-set.md) (ETAS-I is the mandatory reference for
  any claim using sub-completeness events), [ADR-0060](0060-completeness-as-a-field.md) (the time
  argument of Mc(x, t))
- **Extends:** [ADR-0009](0009-etas-baseline.md) (the pinned `lmizrahi/etas` baseline)
- **Related:** [ADR-0018](0018-etas-issuance-without-refit.md) (issuance without refit),
  [ADR-0054](0054-latency-aware-observation-sources.md) (real-time completeness is a vintage
  problem seen from the other side)

## Context

ADR-0059 named ETAS-I the mandatory reference whenever an event below the completeness limit
enters a score, and ADR-0060 made completeness a field with a time argument. Neither shipped one.
RELEASE_STATUS has said so plainly since: the pinned `lmizrahi/etas@097f08b6` carries the
incompleteness machinery, the adapter already calls `responsibility_factor` inside its
log-likelihood, and `baselines/` still holds plain ETAS only. CONTRIBUTING repeats it as the
highest-value multi-month task in the repository, and the reason is the review's sharpest finding:
**every claimed machine-learning gain from small events in the surveyed literature is measured
against plain ETAS, which was not designed for incomplete data, rather than against ETAS-I, which
was.** A standard nobody can run is a standard nobody has to meet.

The machinery was never the hard part. `etas.inversion` already supports a per-event completeness:
set `metadata["mc"] = "var"`, give the catalogue a `mc_current` column, and supply `m_ref`. What
was missing is the input — an Mc(t) — and the discipline about where it comes from.

There is a trap here that this ADR exists mostly to avoid. Mizrahi, Nandan & Wiemer (2021) present
two methods. The first inverts ETAS on a catalogue whose completeness varies in time and takes
`mc_current` as **given**; the second replaces the threshold with a rate- and magnitude-dependent
*detection probability*. The `mc="var"` path is the first. Building it and calling the result
"ETAS-I as Mizrahi et al. built it" would be a citation to a method that was not implemented, which
is the same class of error as scoring against a baseline someone else ran.

## Decision

1. **The Mc(t) law is a declared, cited object, not a constant in the arithmetic.**
   `rupture.domain.completeness.StaiCoefficients` carries `offset`, `decay` and a **required**
   `citation`. The default, `HELMSTETTER_2006`, is `Mc(t) = Mm − 4.5 − 0.75·log10(t)` with `t` in
   days, from Helmstetter, Kagan & Jackson (2006), BSSA 96(1), 90–106 — a *southern Californian*
   measurement, which is a scope condition and is recorded as one on the object itself.

2. **What was not verified is stated rather than implied.** Which Mc(t) Mizrahi et al. used for
   their own California ETAS-I results was not checked against the paper when this was built. The
   claim made here is "ETAS fitted through the package's variable-completeness inversion, with an
   externally declared Helmstetter-style curve". The claim *not* made is that these coefficients
   reproduce theirs.

3. **Mc(t) is domain code, in numpy, importing nothing.** Completeness is not a property of the
   forecasting adapter. The aftershock service needs the same curve (`docs/AFTERSHOCK.md`
   limitation 2 is exactly its absence), and any scorer that has to say which targets were
   detectable needs it too. Neither should import a forecasting adapter to ask what Mc was.

4. **Every event is a trigger, and the per-event threshold is the max over all of them.** ETAS has
   no mainshocks; a M5 inside a sequence blinds the network to its own aftershocks whether or not
   anybody labelled it. The result is floored at the network's long-run Mc — short-term
   incompleteness raises the threshold, it never lowers it — and capped at the trigger's own
   magnitude, because `log10(t)` diverges at the trigger and an event at or above the size of its
   own trigger is not one the catalogue can miss.

5. **The computation is exact and near-linear, not sampled or approximated.** The quadratic
   reading is unusable at 10⁵ events. Two exact bounds replace it: a trigger expires once its
   curve reaches background (`searchsorted` turns that into an index range), and a trigger is
   dominated by any later event at least as large (a monotone-stack pass). Measured: 0.03 s for
   110 k events, and agreement with a brute-force reference on randomised catalogues with
   deliberate timestamp collisions is a unit test rather than a claim.

6. **Plain ETAS is the default and does not move.** `MizrahiETAS(incompleteness=None)` is
   byte-for-byte the model that produced every fit under `baselines/` and every number in
   `reports/` — the ETAS-I diagnostics block is *added* only when the feature is on, so an existing
   diagnostics dict is unchanged. A default that quietly switched the inversion would restate every
   published result without anybody editing a line.

7. **The two models carry different ids.** `etas-mizrahi` and `etas-i-mizrahi`. `load_fit` already
   refuses a fit whose `model_id` does not match, so an ETAS-I fit cannot be loaded into a plain
   model and a `ForecastGrid` cannot be mislabelled.

   **`baselines/` cannot yet hold both.** `fit_dir` keys on region alone, so the two models
   resolve to the same `baselines/etas/<region>/`. `save_fit` therefore *refuses* the collision
   rather than clobbering the plain baseline, which is a guard and not a layout: persisting an
   ETAS-I fit needs a directory scheme this ADR does not settle, and the DVC `fit_etas` stage
   hangs off the current path. An earlier draft of this decision claimed the opposite and
   contradicted this ADR's own Consequences section.

8. **`mc_current` is snapped *up* onto the `delta_m` grid.** The package rounds magnitudes onto
   that grid and then keeps `magnitude >= mc_current`, so an off-grid threshold acts as the bin
   above it regardless; snapping makes the effective cut explicit, keeps `m_ref = mc` a valid floor
   (the package silently *lowers* `m_ref` otherwise, which would change the reference magnitude the
   parameters are expressed in), and silences the package's own "rounding issues" warning. Up
   rather than down is the conservative direction: it can discard a marginal event, never admit one
   the network may not have seen.

9. **ETAS-I can be fitted here and cannot yet be issued, and `forecast()` raises rather than
   pretending.** Two pieces of the issuance path are plain-ETAS assumptions written into code:
   `issuance_state` sets every source's `xi_plus_1` to 1 — which *is* the responsibility factor
   ETAS-I exists to apply — and the continuation is simulated above a single scalar cut. A forecast
   produced by mixing those with ETAS-I parameters would be an ETAS-I label on a plain-ETAS
   number, which is the exact failure this reference exists to catch.

## Consequences

- **The first ETAS-I fit in this repository exists and converged.** On the committed California
  fixture (`tests/fixtures/forecasting/`, ComCat M3+, 2018-01-01 to 2019-12-28) with a training
  cutoff of **2020-01-01** — chosen so the Ridgecrest M6.4/M7.1 sequence is *inside* the window —
  mc = 3.0, delta_m = 0.1, `auxiliary_years=0.5`, `m_ref = 3.0`, default EM start: 1425 training
  events, of which 550 carry an `mc_current` above 3.0 (maximum 5.1). ETAS-I converged in 31 EM
  iterations on 1011 target events; plain ETAS on the identical slice converged in 22 iterations
  on 1358. Both take one to two minutes on a laptop — ETAS-I is not the slower of the two by
  anything that matters. Every figure below was reproduced twice, bit for bit.

  | | plain ETAS | ETAS-I |
  |---|---|---|
  | b-value | 0.869 | **1.012** |
  | `a` | 2.179 | 5.205 |
  | `log10_k0` | −2.659 | −3.077 |
  | `gamma` | 1.133 | 1.768 |
  | `rho` | 0.801 | 1.919 |
  | branching ratio | 1.044 | 0.968 |
  | target events | 1358 | 1011 |

  The b-value is the headline and it moves in the direction the mechanism predicts: short-term
  incompleteness truncates small events preferentially, which biases b **low**, and modelling it
  moves the estimate from 0.87 to 1.01 — onto the canonical value for California rather than away
  from it. The branching ratio crossing from supercritical (1.044) to subcritical (0.968) is the
  second-order consequence and is reported without further interpretation.

  **The two log-likelihoods are not comparable and are not compared.** They are computed on
  different target sets (1011 against 1358 events), so the difference between −4683.3 and −4678.2
  measures the filtering, not the models. A like-for-like comparison needs a common evaluation set
  and does not exist yet.

- **On the committed fixture fit's own window, ETAS-I and plain ETAS are identical.** That window
  ends 2019-07-01, three days before Ridgecrest, and its largest event is M5.29; with a background
  Mc of 3.0 the Helmstetter curve never rises above background anywhere in it. Not one parameter
  moves. This is a unit test, and it is the strongest available evidence that the switch is inert
  when it should be — but it also means the committed fixture fit cannot be used to argue anything
  about ETAS-I, and nothing here is a re-scoring of any published result.

- **`baselines/` cannot yet hold both models, and `save_fit` now refuses rather than clobbers.**
  `fit_dir` keys on the region alone — `baselines/etas/<region>/` — so an ETAS-I fit of a region
  would have overwritten that region's plain-ETAS baseline and its per-cutoff archive. Giving the
  two models separate directories is a layout change with DVC outputs and the `fit_etas` stage
  attached to it, so it is not made here; instead `save_fit` raises when the target directory
  already holds a fit of a different `model_id`. Persisting an ETAS-I baseline is therefore still
  blocked, which is why the measurement above is reported in this ADR rather than committed under
  `baselines/`.

- **Nothing is re-scored and `baselines/` is unchanged.** No committed fit is touched, no report is
  regenerated, and no challenger has been re-measured against ETAS-I. ADR-0059's requirement is now
  *runnable*; it is not yet *run*.

- **The Mc field of ADR-0060 is still a scalar in space.** This is Mc(t), not Mc(x, t). A network
  whose completeness varies across the region is still forced to its worst cell, which is exactly
  the cost ADR-0060 was written about.

- **The curve is southern Californian and will be applied elsewhere.** Türkiye and Nepal have
  different station densities and different analyst latencies. Using `HELMSTETTER_2006` there is an
  assumption, and the `notes` field on the object says so at the point of use rather than in a
  document nobody opens.

## Alternatives considered

- **Use the package's `mc="positive"` instead.** Rejected: it is a different model. Van der Elst
  (2021) b-positive conditions on magnitude *differences* to sidestep incompleteness rather than
  modelling a threshold, and the two are one string literal apart in the metadata dict — which is
  why this ADR names the distinction rather than leaving it to be rediscovered.
- **Estimate Mc(t) from the catalogue itself** (rolling maximum-curvature, or the package's own
  `estimate_mc`). Not rejected, deferred. It is circular where the catalogue's completeness is the
  thing in question (ADR-0060 says so), and it would make the reference baseline depend on an
  estimator with its own failure modes. A declared law is auditable in a way a fitted one is not,
  and it is the right first version.
- **Implement Mizrahi et al.'s detection-probability formulation.** Deferred. It is the better
  model and it is a substantially larger change: it replaces the threshold rather than varying it,
  and the package's `mc="var"` path does not express it.
- **Make ETAS-I the default.** Rejected outright. See decision 6.
- **Let `forecast()` issue from an ETAS-I fit anyway, with a caveat in the notes.** Rejected. A
  caveat in a `notes` string does not stop the number being quoted, and the repository's own
  governing principle is that the harness refuses an invalid result rather than documenting it.
- **Put the Mc(t) curve in the forecasting adapter.** Rejected: three other consumers need it and
  none of them should import an adapter. See decision 3.
