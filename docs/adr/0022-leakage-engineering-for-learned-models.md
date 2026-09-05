# ADR-0022: Leakage engineering for learned models

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

Prompt 1's leakage rules were enforced on one model whose fitting procedure rupture controls end
to end. Prompt 2 adds learned models with dataset builders, feature windows, validation splits and
hyperparameter search — every one of which is a place where information from after the cutoff can
reach the model without anyone intending it. The field's own history is the warning: random
k-fold cross-validation on earthquake catalogues produces leakage and fake skill, and a challenger
that beats ETAS because of a subtle leak is worse than no challenger at all.

## Decision

1. **Dataset builders take a `cutoff` and refuse events at or after it.** The refusal is an
   exception, not a filter: silently dropping late events hides the bug that put them there.
2. **Feature windows are strictly causal.** A feature at time *t* may use only data with
   `origin_time < t`. Rolling statistics are computed with closed-left, open-right windows.
3. **Time-forward blocked cross-validation only.** Random k-fold is not merely discouraged: the
   splitter API has no shuffle option, and a test asserts that every validation index is strictly
   later than every training index.
4. **Hyperparameters are chosen on a validation window strictly before the test window**, and the
   chosen configuration is frozen and recorded with its snapshot hash before any test window is
   scored.
5. **Normalisation statistics are fitted on training data only** and carried with the model.
6. **One deliberately leaky ablation is run and clearly labelled**, to quantify how much apparent
   skill leakage buys. It is reported in `reports/CHALLENGER_EVALUATION.md` and never presented as
   a result.

## Consequences

- Challenger scores are comparable to ETAS under the same protocol, which is the only basis on
  which the promotion rule means anything.
- The leaky ablation gives a number for what the discipline is worth, rather than an assertion
  that it matters.
- Some legitimate modelling choices are foreclosed (any global normalisation, any tuning that
  peeks at the test period). That is the intended cost.

## Alternatives considered

- **Rely on review to catch leakage.** Rejected: leakage is invisible in a diff and shows up as
  good news, which is exactly when reviewers relax.
- **Allow random k-fold for hyperparameters only.** Rejected: catalogue events are strongly
  autocorrelated in time and space, so a random split leaks through aftershock sequences.

## Amendment (2026-09-04)

Three later ADRs extend these rules for the prediction programme. The six decisions above are
unchanged.

- **[ADR-0054](0054-latency-aware-observation-sources.md)** adds a leakage class these rules cannot
  express. Rule 2's strictly causal feature windows filter on the time a datum *refers to*; latency
  leakage is reading a value that did not exist yet at that time, in the revision it has today.
- **[ADR-0056](0056-preregistration-by-git-ancestry.md)** puts a machine behind rule 4: a frozen
  hyperparameter configuration recorded before scoring is to be verified by git ancestry rather
  than asserted in a file the author dated. **That runner does not exist yet** — today rule 4 rests
  on the challenger pipeline's `select`-before-`fit` ordering, which is a real constraint and not a
  proof of ordering against the test data.
- **[ADR-0059](0059-reference-baseline-set.md)** fixes which baseline a comparison must use, per
  task. Rule 6's leaky ablation keeps its role and its numbers: **+0.31 to +2.16 nats per event** of
  manufactured skill, and a −0.346 nats-per-event Nepal loss turned into a +0.429 apparent win.
