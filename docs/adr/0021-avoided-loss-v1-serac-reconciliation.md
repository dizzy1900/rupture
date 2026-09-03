# ADR-0021: Avoided loss v1 — reconciliation with the sibling `serac`

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)
- **Supersedes in part:** ADR-0014 (coordination rule), which anticipated this case

## Context

ADR-0014 recorded that `serac` was empty on 2026-09-03, that rupture would publish
`avoided-loss.v0.json` first, and that **if serac later published a differing schema of the same
name, the two would be reconciled to a field-compatible superset with the version bumped**.

serac has now published. Its `AvoidedLossRequest` is:
`{contract_version, request_id, requested_utc, requester, forecast: CascadeForecast, exposure:
[ExposureItem], scenarios: [WarningScenario]}`, with value types `MoneyRange`, `Range`,
`AttributedEstimate`, `ConfidenceTier`, `ModelProvenance` and an `InterventionKind` of
`{none, warning, evacuation, combined}`.

rupture's v0 is `{request_id, requested_at, portfolio, trigger_kind, trigger_id, horizon,
loss_types, interventions, interval_level, consumer}`.

These are the same *question* — what loss does an intervention avoid — asked about different
hazards. serac's envelope is cascade-warning shaped (lead times, evacuation); rupture's is
portfolio-risk shaped (retrofits, insurance layers, a trigger that may be a forecast). Forcing one
envelope on both would make each worse at its own job.

## Decision

Publish `avoided-loss.v1.json` that reconciles what genuinely should be shared, and keep distinct
what genuinely differs. `v0` stays published and unchanged.

1. **Shared value vocabulary, adopted verbatim from serac**: `MoneyRange` (low, high, best,
   currency, price_year, basis), `Range`, `AttributedEstimate`, `ConfidenceTier`,
   `ModelProvenance`. Same field names, same constraints, so a consumer reads money and confidence
   identically from either project. rupture copies the shape; it does not import serac.
2. **Field aliases on input**: `requested_utc`↔`requested_at`, `requester`↔`consumer`,
   `exposure`↔`portfolio`. A serac-shaped request parses in rupture unchanged.
3. **A `hazard_kind` discriminator** (`seismic` | `cascade`) so a shared reader dispatches instead
   of guessing.
4. **A superset `InterventionKind`**: serac's four values verbatim, plus rupture's structural
   measures (`structural_retrofit`, `automated_shutdown`, `land_use_exclusion`,
   `insurance_layer`).
5. **A common response shape**: losses as `MoneyRange`, an avoided figure per intervention,
   decomposition by asset and by hazard component, and explicit `ModelProvenance`.
6. **serac's honesty rule is adopted**: a response whose provenance is `stub` may claim only
   `ConfidenceTier.UNQUALIFIED`. This is enforced by a validator, not by convention.

Compatibility is proven by executable tests (`tests/contract/test_serac_reconciliation.py`) that
parse serac-shaped payloads. A compatibility claim that is not executed is not a claim.

## Consequences

- A downstream consumer can read an avoided-loss answer from either project with one money type
  and one confidence scale.
- rupture carries serac's vocabulary and must track it. Divergence is a contract test failure.
- Coordination remains by copying files, never by importing code; serac is not a dependency.

## Alternatives considered

- **One merged envelope.** Rejected: it would carry cascade lead times into portfolio requests and
  portfolio trigger semantics into warning requests, helping neither.
- **Leave v0 and ignore serac.** Rejected: ADR-0014 committed to reconciliation, and a consumer
  reading both would need a private translation layer.
- **Ask serac to adopt rupture's schema.** Rejected: rupture published first by accident of
  timing, not by authority, and serac's value types are better than rupture's original bare floats.
