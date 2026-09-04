# ADR-0036: The ETAS log-likelihood rupture persists

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Supersedes:** the "no log-likelihood" limitation recorded in `docs/ETAS_BASELINE.md`
  (Known limitations) and in the `log_likelihood_note` diagnostic written before this ADR.

## Context

Prompt 1 requires the baseline's **parameters, log-likelihood and diagnostics** to be persisted to
`baselines/etas/<region>/`. Until now `FitResult.log_likelihood` was `null` in every fit, with a
diagnostic saying that the `etas` package of Mizrahi, Nandan & Wiemer (ADR-0009) "does not expose
the full point-process log-likelihood at convergence".

That statement was accurate about the package's API and wrong about what the package makes
available. `etas.inversion` exposes exactly one likelihood function, `neg_log_likelihood(theta,
Pij, source_events, mc_min)`. It is the **expected complete-data** negative log-likelihood — the
EM's Q function at the current responsibilities `Pij` — and the M step minimises it. Persisting
that number would have been worse than persisting nothing: it is defined only relative to a set of
responsibilities, so it is not comparable across cut-offs, regions, refits or models, which are
precisely the comparisons the brief wants a likelihood for.

The pieces of the *observed-data* likelihood, however, are all produced by the package's own
expectation step. `expectation_step` computes, for every target, the conditional intensity
`tot_rates` = μ + Σⱼ (ξⱼ+1)·gᵢⱼ; `expected_aftershocks` integrates the same triggering kernel `g`
over the plane and over the part of the primary window that follows each source; and
`optimize_parameters` fixes the background rate as `μ̂ = n̂ / (area · T)`, which identifies μ as a
rate density per km² per day. Assembling the likelihood from those pieces is arithmetic, not a new
model.

## Decision

1. **`FitResult.log_likelihood` is the space-time ETAS log-likelihood of the primary window at the
   fitted parameters**, computed by `point_process_log_likelihood` in
   `src/rupture/adapters/forecasting/etas_mizrahi.py`:

   ```
   λ(t, x, y) = μ + Σ_{j : t_j < t} (ξ_j + 1) · g(t − t_j, r_ij, m_j)

   LL = Σ_i (ζ_i + 1) · log λ(t_i, x_i, y_i)
        − μ · area · timewindow_length
        − Σ_j (ξ_j + 1) · G_j
   ```

   with `g` = `etas.inversion.triggering_kernel`, `G_j` = `etas.inversion.expected_aftershocks`,
   and `ξ+1` / `ζ+1` the package's own corrections (`responsibility_factor`,
   `observation_factor`) for triggering by events below completeness and for a target-time
   completeness above the reference magnitude. Both are exactly 1 in every fit rupture makes,
   because this adapter configures a constant `mc = m_ref`; they are carried so the formula stays
   the package's and not a special case of it.

2. **The three terms are persisted alongside the total**, in
   `diagnostics.log_likelihood_terms` (`observed_term`, `background_integral`,
   `triggering_integral`, `n_targets`, `n_sources`), so a reader can see what moved between two
   fits rather than only that the total moved.

3. **What the number is conditional on is stated, not implied.** It is conditional on the
   auxiliary catalogue (auxiliary events are sources, never targets); it excludes the magnitude
   density, so it is the space-time likelihood at fixed `beta`; and its integral term has **no
   spatial boundary correction** — `G_j` integrates over the whole plane while targets are counted
   inside the region polygon. The last is the package's own convention, shared with its EM
   objective, so the number is the likelihood of the model that was actually fitted. Two
   log-likelihoods are therefore comparable when the region, `mc`, `delta_m` and window agree, and
   not otherwise.

4. **A non-finite or undefined value is `null`, never a substitute.** `point_process_log_likelihood`
   raises when the expectation step has not run, when a `free_background` / `free_productivity` /
   induced-seismicity variant is in use (the intensity above is then not the model's), or when any
   term is not finite. `fit()` catches that, persists `log_likelihood = null` and records the
   reason in `diagnostics.log_likelihood_note`.

5. **A stored fit can be scored again without being refitted.** `MizrahiETAS.log_likelihood(catalog)`
   rebuilds the fitted window from the fit's own diagnostics, runs one expectation step at the
   stored parameters and returns the same quantity. It refuses unless the reconstructed training
   slice hashes to `FitResult.training_catalog_hash`, so it cannot silently score a fit against a
   different catalogue. This is how the three published fits of 2026-09-03 were given a
   log-likelihood without a refit (`docs/ETAS_BASELINE.md` § Published fits).

## Consequences

- Fits become comparable by likelihood across cut-offs and refits within a region, which is what
  the yearly-refit calendar needs in order to notice a fit-quality regression.
- The value is **not** a model-selection score against a challenger with a different support: the
  ETAS likelihood here is over the continuous space-time process on the region, whereas the CSEP
  tests (ADR-0010) score gridded, binned rates. Paired model comparison remains the T- and W-tests
  of the evaluator; this ADR does not create a second, quieter ranking.
- The identity `background_integral + triggering_integral = Σᵢ (ζᵢ+1)` holds at an EM optimum and
  is asserted in `tests/unit/forecasting/test_etas_log_likelihood.py`; a converged fit whose terms
  break it is a bug in the assembly, not a property of the catalogue.
- Fits persisted before this ADR keep `log_likelihood = null` on disk until they are refitted or
  backfilled; the note in their diagnostics still says the old reason, which is the honest record
  of what that file contains.

## Alternatives considered

- **Persist the EM expected complete-data NLL** under a distinct key. Rejected as the primary
  answer: it is not comparable across catalogues, and shipping it under a name that reads like a
  likelihood invites exactly the comparisons it cannot support. Nothing prevents adding it later
  under an explicit name.
- **Add the magnitude term** (`beta`-exponential density) to make it a full marked-process
  likelihood. Deferred: `beta` is estimated outside the EM (Tinti), so the joint number would mix
  an estimator and an optimiser, and every comparison rupture makes today is at fixed `mc` and
  `delta_m` where the term is a constant offset.
- **Boundary-correct the integral** by integrating `G_j` over the region polygon only. Rejected
  for Prompt 1: it would make the reported likelihood inconsistent with the objective the
  parameters were fitted under, which is the worse error. It is the natural content of a later
  ADR if edge effects are shown to matter for a region.
