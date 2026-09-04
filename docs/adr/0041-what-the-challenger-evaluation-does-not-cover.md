# ADR-0041: What the challenger evaluation does not cover, and why it was not approximated

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)
- **Related:** [ADR-0040](0040-promotion-rule-single-encoding.md) (the promotion rule, encoded
  once), [ADR-0029](0029-neural-point-process-challenger-and-shared-dataset-layer.md),
  [ADR-0031](0031-gridded-spatio-temporal-challenger.md),
  [ADR-0032](0032-log-linear-ensemble.md)

## Context

An audit of the challenger deliverables found four gaps that are real, that were not closed, and
that a reader can only judge if the repository says so in its own ledger rather than in a commit
message. None of them is a defect in the code; each is a run that was not made or a comparison
that was not earned. They are recorded here so that "not promoted" is understood for what it is:
a verdict over the evidence that exists.

The temptation in each case is to close the gap with something that looks like the missing thing —
a Californian fit at a coarser threshold, an ensemble number extrapolated from the components, a
published figure quoted beside a differently defined one. All four would make the evaluation look
more complete and none would make it more true.

## Decision

Record the following as accepted limitations, in this ADR, in the model cards, and in the gate's
own output where the gate can see them. Do not approximate any of them.

1. **The neural challenger was never fitted on `california`.** Its likelihood is
   O(targets × sources) per epoch and California's pre-cutoff slice holds 55,828 events above the
   RELM threshold; at 8,000 epochs this is not hours but weeks on the hardware available. A
   windowed or truncated source set would make it tractable and would also change the model — it
   would no longer be the model whose Türkiye and Nepal numbers are published — so the honest
   options were "run it as it is" or "do not run it". It was not run. Consequence: the challenger
   is evaluated in two of the three protocol regions, and condition 3 of the promotion rule was
   unreachable rather than failed. Both evaluated regions lost condition 1 outright, so the
   verdict does not turn on it.

2. **`california` was not run for the gridded challenger or the ensemble either**, and could not
   have produced a pass for anyone: condition 1 compares pass rates *against ETAS over the same
   schedule*, and the published Californian ETAS schedule is 6 windows against the 12 consecutive
   that condition 1 requires (`RELEASE_STATUS.md` records why it was stopped there and that it is
   resumable). This is stated mechanically by `make validate-challengers`, which names every
   unevaluated region and says whether running it could have changed the verdict. It matters most
   for the ensemble, the one model that passed a region: one pass plus a Californian pass would be
   the two § 10 asks for. Extending the Californian ETAS schedule is therefore the single highest
   -value run left in this workstream.

3. **No ensemble pooling ETAS with the neural challenger was evaluated.**
   `LogLinearEnsemble` accepts any component mapping and both challengers now live in the same
   tree, so this is a configuration rather than a feature; what it needs is a weight fit on the
   2020–2022 validation block and a rescored 55-window schedule per region, which is hours of
   compute per region. The brief's "a log-linear mixture of ETAS and any challenger" is therefore
   satisfied in code and *evaluated* for one challenger only. No number was estimated for the
   unevaluated pool.

4. **No number in this repository is comparable to a published EarthquakeNPP table.** The
   benchmark's conventions were adopted where they apply (`docs/CHALLENGER_NTPP.md` § 2), but its
   seven datasets are all Californian, its horizon is a rolling 24 hours against this protocol's
   30 days, and its thresholds and split dates are its own. Placing a 30-day Türkiye figure beside
   a 24-hour Californian one would be a category error dressed as a benchmark. What is claimed is
   agreement with the benchmark's *finding* — a neural point process losing to ETAS, and losing on
   the spatial component — reproduced on different data.

## Consequences

- `reports/CHALLENGER_EVALUATION.md`, the model cards and `RELEASE_STATUS.md` must not read as
  though the evaluation covered three regions or two ensemble pools. The model cards say so
  explicitly; `make validate-challengers` names the unevaluated regions on every run, so the
  omission is printed in CI rather than remembered.
- The verdict — no challenger promoted — is unchanged by all four gaps, and for the gridded and
  neural challengers it is provably unchangeable by them. For the ensemble it is not: a Californian
  pass would promote it, and that is stated wherever the ensemble's verdict is stated.
- If any of these runs is later made, the run comes first and the document changes after it. None
  of the four may be closed by an estimate.

## Alternatives considered

- **Fit California with a truncated source window.** Rejected as described above: it produces a
  different model, and comparing its numbers with the published ones would be worse than having
  none.
- **Report the ensemble-with-NTPP as "expected to be similar".** Rejected outright. An unevaluated
  configuration has no result.
- **Lower the Californian target threshold to shrink the catalogue.** Rejected: § 1 of the protocol
  fixes the RELM threshold, and moving a threshold to make a model runnable is exactly the tuning
  the protocol was written in advance to prevent.
- **Say nothing and let the absence speak.** Rejected. An absence in a report reads as a result
  that was too dull to mention.
