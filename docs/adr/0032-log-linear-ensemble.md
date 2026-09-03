# ADR-0032: The ensemble is a log-linear pool, weights fitted on a validation window, rates floored relatively

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

The brief asks for a log-linear ensemble of ETAS with any challenger,

    log lambda_ens = sum_k w_k log lambda_k    (normalised)

with weights fitted on a validation window only, never on a test window, implemented behind the
same `ForecastModel` port so it is scored like any other model. Two details are left to us and
both change the numbers: what to do about cells whose rate is zero (the logarithm of zero is not a
number), and what "normalised" means for a pool of rate fields.

The ensemble is also the component of this work most likely to look good, which is exactly why it
needs the most explicit construction. A geometric pool of two models can beat both when they make
independent errors; it can also inherit the worst of both, because a geometric mean is dominated
by whichever component says "almost nothing here".

## Decision

1. **Log-linear (geometric) pooling with weights on the simplex.** `w_k >= 0`, `sum_k w_k = 1`.
   The component list is a constructor argument, so the ensemble runs with ETAS alone, with ETAS
   plus the gridded challenger, or with any further challenger added later.
2. **Zero-rate floor, relative to the component's own mean rate.** Before taking logarithms each
   component's rates are floored at

       floor_k = floor_fraction * total_k / (n_cells * n_bins)

   with `floor_fraction = 1e-6`, fixed in advance and **not** tuned on any window. The floor is
   relative rather than absolute so that it means the same thing in a region with two target
   events a year and in one with a hundred, and so that it is invariant to the magnitude
   threshold. It has a useful bound: since at most every cell-bin can be raised to the floor, the
   floor adds at most `floor_fraction` of the component's own total, so it cannot move the count
   forecast. What it does move is the far tail of the spatial law — an ETAS grid on
   `nepal-himalaya` has cells at 1e-23 expected events, which is the analytic background law
   extrapolated, not an estimate anyone should defend — and there the floor is the point. Without
   it a single observed event in such a cell drives the pooled log-likelihood to minus infinity
   and the ensemble is rejected on one cell's worth of extrapolation.
3. **Normalisation to the weighted geometric mean of the component totals**,
   `log N_ens = sum_k w_k log N_k`, after pooling. The geometric mean of two rate *fields* does
   not integrate to anything in particular, so an unnormalised pool is not a rate forecast at all.
   With this rescaling the ensemble's N-test behaviour interpolates between its components'
   rather than being an artefact of the pooling.
4. **Weights are fitted by maximising the summed Poisson log-likelihood of the observed
   cell-magnitude counts over the validation windows**, and over nothing else. Every validation
   window must close at or before the test cutoff, and this is asserted rather than assumed;
   `fit` refuses when it is not so. Each component's forecast for a validation window must come
   from a fit whose own cutoff is at or before that window's issue time, which is also asserted.
5. **The search is a deterministic grid over the simplex** — a coarse pass at 0.05 followed by a
   refinement pass at 0.01 inside the winning cell — not a gradient optimiser. The fitted weights
   are then reproducible to the grid step and do not depend on an initialisation or a random
   restart. With two components this is exhaustive to 0.01.
6. **Components must agree on cells and magnitude bins**; a mismatch is an error, never something
   the ensemble reconciles silently.
7. **One ablation is run alongside every ensemble result: the same pool with the challenger's
   spatial field flattened to uniform**, keeping its total and its magnitude distribution. With a
   near-static second component a log-linear pool reduces to *tempering* the baseline — raising its
   rate field to a power below one and renormalising — and tempering alone can improve a
   badly-calibrated baseline without any model contributing information about place. The uniform
   ablation is exactly tempering and nothing else, so the two numbers side by side say how much of
   any gain is the pooling arithmetic and how much is the challenger.

## Consequences

- The ensemble is a `ForecastModel` and is issued, persisted and scored exactly like ETAS or the
  gridded challenger, including the paired T-test against ETAS.
- At `w_k = 1` for one component the ensemble is that component with its own floor applied and
  renormalised — not bit-identical to it. That is a real, small difference and the tests state it
  rather than papering over it.
- The floor is a modelling choice with a number attached, and the number is published. Anyone who
  disagrees with `1e-6` can rerun with another value; what they may not do is tune it on a test
  window.
- Weights fitted on a two-year validation block with a handful of target events are themselves
  uncertain. The fitted value is reported with the number of validation windows and target events
  behind it, so the reader can see how thin that evidence is.

## Alternatives considered

- **Reporting the ensemble's gain without the uniform ablation.** Rejected: a geometric pool with
  a flat second component is a well-known variance-reduction trick, and a reader has no way to tell
  it apart from a real contribution unless both are measured.
- **A linear (arithmetic) pool.** Better behaved around zeros and needs no floor, but the brief
  asks for the log-linear form, and the log-linear form is the one that corresponds to combining
  log-likelihoods, which is what the CSEP tests score. Recorded here as the obvious fallback if
  the floor ever proves to be doing real work.
- **An absolute floor (e.g. 1e-12 expected events per cell-bin).** Rejected: it means different
  things in different regions and at different magnitude thresholds, and it has no bound on the
  mass it adds.
- **Tuning `floor_fraction` on the validation block.** Legitimate under ADR-0022 and deliberately
  not done, so that the floor cannot be blamed for, or credited with, the result.
- **Fitting weights by gradient descent on a softmax parameterisation.** Rejected as
  unnecessary: with two or three components an exhaustive simplex grid is cheap and removes a
  source of run-to-run variation.
