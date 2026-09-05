# ADR-0060 — Completeness is a field, Mc(x, t), and it ships with every catalogue

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Extends:** [ADR-0019](0019-target-thresholds-and-california-magnitude-policy.md) (target
  thresholds follow the published Mc)
- **Related:** [ADR-0054](0054-latency-aware-observation-sources.md),
  [ADR-0059](0059-reference-baseline-set.md)

## Context

rupture models completeness as a scalar per region. `Region.mc` is one `CompletenessEstimate` with
`Region.mc_estimates` holding the alternatives, and `rupture catalog build --update-region-mc`
sets it only when maximum-curvature b ≥ 0.7 and Mw coverage at the target is at least 80 %,
printing why when it declines. That is a careful implementation of the wrong object.

The cost is already visible in this repository's own results. Nepal's published Mc is 4.40 by
maximum curvature and 4.70 by b-value stability against a 4.7 target, so the target sits *at* the
completeness limit rather than above it; 33 of 55 Nepal windows held no target event and four of
the five consistency tests were undecidable in them (`RELEASE_STATUS.md`). A scalar cannot express
"complete at 3.8 near the network and 4.9 at the edge", so the threshold has to be set for the
worst cell in the region and the rest of the data is discarded.

The prediction programme makes this binding rather than merely wasteful, for three reasons.

**Dense catalogues are a liability without it.** Mancini et al. (2022, `single-study`) fed four
catalogues of the same sequence, from Mc 2.3 down to Mc 0.2, into ETAS and Coulomb rate-and-state
models and found *no* significant M3+ information gain and information *loss* at M1–M2. More events
are not more information when completeness, sub-kilometre kernels and magnitude homogeneity are not
modelled — which is the field's central under-appreciated fact and the reason the deep-learning
detection revolution has not moved forecasting.

**Completeness is the gating variable for the foreshock literature.** Mignan (2014, `single-study`)
shows foreshock anomalies appear only when completeness reaches about three magnitude units below
the mainshock. Whether a foreshock sequence is anomalous is therefore partly a statement about the
network, and a census run without an Mc field is measuring station density.

**Real-time completeness is a different object from archival completeness.** Hainzl et al. (2024,
`single-study`) quantify short-term aftershock incompleteness as a roughly 162-second blind time;
Li & Luo (2024, `single-study`) show maximum-likelihood, b-positive and KMS b-value estimators all
fail under realistic real-time incompleteness and magnitude error. Completeness therefore has a
time argument for the same reason observations have an availability time
([ADR-0054](0054-latency-aware-observation-sources.md)), and the two problems are the same problem
seen from two sides.

And the reference baseline this project now requires needs it as an input: ETAS-I
([ADR-0059](0059-reference-baseline-set.md)) models incompleteness, and Mizrahi et al. (2021)
parameterise it with a global blind time rather than a field. Supplying the field is the
improvement available.

## Decision

1. **Mc is a field with uncertainty, Mc(x, t), not a scalar.** A completeness product is a grid
   over the region and time with an estimate and an interval per cell, its estimator named, and its
   provenance recorded like any other derived product.

2. **No rupture catalogue is published without its completeness field, and no forecast is scored
   without one.** `validate-catalog` gains the check. A catalogue with a scalar and no field is
   labelled as such and cannot support a claim that uses sub-completeness events.

3. **`Region.mc` becomes a derived summary, not the authority.** It stays — thresholds, targets and
   the existing gates depend on it, and ADR-0019 fixes the target-threshold policy — but it is
   documented as an aggregate of the field, and where field and scalar disagree the field is right.

4. **The estimator is declared, and more than one is kept.** Maximum curvature and b-value
   stability already disagree in this tree by 0.3 magnitude units on Nepal; that disagreement is
   information about the estimate and is preserved rather than resolved by picking one.

5. **The intended construction, stated as a plan and not as a delivery**: station-level
   detection-probability models from pick residuals and noise power spectra, aggregated into a
   probabilistic grid. rupture ingests none of those inputs today. This decision fixes the contract
   — what a completeness product is and where it is required — and the construction is unbuilt and
   untested.

6. **Completeness is vintaged like everything else.** The Mc field a model reads at issue time is
   the one that could have been computed from the data available then, which for the first hours
   after a mainshock is very different from the archival one.

## Consequences

- The `Catalog` domain model gains a required companion product, and every catalogue already in
  the tree is retroactively incomplete in this sense. That is a migration, and it is honest to say
  that the existing built catalogues will carry `completeness_field: null` until they are rebuilt.
- Regions where the target threshold was forced up by the worst cell can lower it per cell, which
  is the direct route to more scored windows in Nepal — the sparsest region in the evaluation and
  the one where sparsity is a completeness artefact rather than a fact about the Himalaya.
- The inputs are not free. Station metadata, pick residuals and noise spectra are a new ingestion
  lane, and until it exists the field can only be estimated from the catalogue itself, which is
  circular in a way that has to be labelled wherever it is done.
- Comparisons against published figures computed on a scalar-Mc catalogue stop being like-for-like,
  the same way as-of replay breaks comparisons against figures computed on final data.

## Failure criterion

If ETAS and ETAS-I fits on Mc-corrected dense catalogues do **not** recover more stable b-values
and productivity parameters across catalogue versions of the same sequence than the uncorrected
fits do, then the instability Mancini et al. reported is caused by spatial discretisation rather
than by completeness, the field is not the missing piece, and effort moves to sub-kilometre
triggering kernels instead. The comparison is run on versions of the same sequence — the Central
Italy catalogue series, Ridgecrest, Türkiye 2023 — and it is the test of this ADR's premise.

## Alternatives considered

- **Keep the scalar and raise the target threshold until the region is complete everywhere.**
  Rejected: that is the status quo, and it is what produced a Nepal target sitting *at* the
  completeness limit with 33 empty windows.
- **Adopt ETAS-I's global blind-time parameterisation and stop there.** Rejected as sufficient,
  accepted as the interim: it is a real model of one component of incompleteness and it is a
  constant where the data has structure.
- **Estimate Mc per cell from the catalogue alone.** Not rejected — it is what is achievable today —
  but it is circular where the catalogue is the thing whose completeness is in question, and it is
  labelled whenever used rather than presented as a measurement.
- **Require the field only for claims that use sub-completeness events.** Rejected: a forecast
  scored on targets above the threshold still depends on a training set whose completeness varies,
  and the review's evidence is that this is where dense catalogues stop helping.
