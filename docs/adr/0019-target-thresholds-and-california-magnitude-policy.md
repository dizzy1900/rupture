# ADR-0019: Target thresholds follow the published Mc; California magnitude policy

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

`docs/EVALUATION_PROTOCOL.md` §1 rule 3 fixed the Nepal and Türkiye target thresholds as
*provisional* until `rupture catalog build` published a fitted Mc, and required that both Mc
estimators (maximum curvature +0.2 and b-value stability) be at or below the target threshold.
The first real builds (1976-01-01 → 2026-08-01, ComCat + ISC + GCMT; `docs/CATALOG_BUILD.md`)
gave:

| Region | Mc maximum curvature +0.2 | Mc b-value stability | Provisional target | Mw coverage at target |
|---|---|---|---|---|
| nepal-himalaya | 4.40 | 4.70 | 4.5 | 94 % |
| turkiye-eaf | 4.30 | 4.60 | 4.0 | 94 % |
| california | 3.70 | 4.90 | 3.95 (RELM) | 49 % |

Two problems follow. (1) In Nepal and Türkiye the b-value-stability Mc exceeds the provisional
threshold, so the protocol's own rule requires the thresholds to rise. (2) In California only 49 %
of events reported at M ≥ 3.95 receive a homogenised Mw, because the network-preferred scale for
most Californian events is ML (or Md) and rupture adopts no ML→Mw relation without a citation
(ADR-0017). The California Mc of 3.70 with b = 0.59 is an artefact of that gap, not a property of
the catalogue, and an ETAS fit or a target set built from it would be meaningless.

## Decision

1. **Thresholds.** `nepal-himalaya.target_min_magnitude = 4.7`; `turkiye-eaf.target_min_magnitude
   = 4.6`. Both equal the b-value-stability Mc, the larger of the two estimators. California stays
   at 3.95 (RELM convention) pending decision 2.
2. **California magnitude policy.** A new `Region.magnitude_policy` field (contract `region.v0`,
   additive) with values `strict` (default) and `network-preferred-as-mw`. For `california` the
   policy is `network-preferred-as-mw`: an event whose preferred magnitude is ML or Md and has no
   moment magnitude from any source is given `mw = magnitude.value` with
   `mw_conversion = 'assumed-equivalent:<type>'`. This follows CSEP RELM practice, where the
   California experiments scored forecasts against ANSS preferred magnitudes without conversion
   (Schorlemmer et al. 2007; Werner et al. 2011). It is an approximation, flagged on every affected
   event, and used for no other region. Moment magnitudes still take precedence when present.
3. After the California rebuild under this policy, Mc is re-estimated and, if either estimator
   exceeds 3.95, the California threshold rises by the same rule and this ADR is amended.
4. The ETAS fit magnitude of completeness remains the region's published maximum-curvature Mc
   (`Region.mc`), as before; only the *target* threshold changes here.

## Consequences

- Target counts fall: Nepal has few M ≥ 4.7 events per 30-day window outside sequences, so many
  windows will be "N-test only" per protocol §5. That is the honest state of a sparse region.
- The pseudo-prospective schedule has not started, so no window is affected retroactively.
- Every California event scored under the assumed-equivalence policy is identifiable in the
  catalogue (`mw_conversion` prefix `assumed-equivalent`), so a later ADR adopting a cited ML→Mw
  relation can rebuild without ambiguity.
- `RELEASE_STATUS.md` records the thresholds and the policy under "Known gaps".

## Alternatives considered

- **Keep provisional thresholds.** Rejected: it would violate the protocol written before any run.
- **Adopt a published ML→Mw relation for California** (e.g. regional relations in the literature).
  Deferred: none was verified in time, and CSEP practice provides a defensible interim.
- **Time-varying Mc** (`etas` supports `mc='var'`). Deferred to Prompt 2; it changes the fit, not
  the target rule.
