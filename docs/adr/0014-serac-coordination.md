# ADR-0014 — Coordination with the sibling `serac` by shared schema files

- **Status:** accepted
- **Date:** 2026-09-03

## Context

`serac` (`github.com/dizzy1900/serac`) is rupture's only sibling: a separate standalone repository
whose discriminator estimates whether a catalogued seismic event is a mass movement (landslide,
ice avalanche, rockfall) rather than a tectonic rupture, and which publishes an avoided-loss
contract of the same name as rupture's. The brief requires the two to coordinate by copying schema
files, never by importing code, and to keep `avoided-loss` field-compatible where semantics
coincide. On 2026-09-03 the `serac` repository was verified **empty** (no branches, no files).

## Decision

- Two shared contracts, authored in rupture first because `serac` is empty:
  - `contracts/source-type-assessment.v0.json` — `SourceTypeAssessment`: `event_id`,
    `source_catalog`, `assessed_at`, `p_mass_movement`, `p_tectonic`, `p_other` (summing to 1),
    `classifier_id`, `classifier_version`, `evidence`, `features`, `contract_version`. Interface
    and fixtures only in Prompt 1.
  - `contracts/avoided-loss.v0.json` — an envelope `{request, response}` of
    `AvoidedLossRequest` (portfolio, `trigger_kind` in `{scenario, forecast, hazard}`,
    `trigger_id`, optional `horizon`, `loss_types`, `interventions`, `interval_level`) and
    `AvoidedLossResponse` (`status`, baseline `LossResult`s, per-intervention `avoided_expected`
    and `avoided_interval`, `model_ids`, `provenance`), each with `contract_version`.
- **Coordination mechanism**: `serac` copies the schema files into its own `contracts/`
  directory; rupture copies `serac`'s if `serac` becomes the author of a later version. Neither
  repository ever lists the other as a dependency, imports its code, or reads its git history at
  runtime. `tests/contract/fixtures/serac/source-type-assessment.example.json` and
  `tests/contract/fixtures/avoided-loss.request.example.json` are the example files both sides
  validate against.
- **Reconciliation rule** if `serac` publishes a differing schema of the same name:
  1. Compare field by field. Where semantics coincide, the field name and type are unified in a
     new version that is a **field-compatible superset** of both (every field either side emits
     is representable; rupture-only or serac-only fields are optional).
  2. The new version gets a bumped `.vN`; both `.v0` files stay published for existing readers.
  3. The reconciliation is recorded in an ADR in both repositories with the diff.
- Semantic ownership: rupture owns the loss and hazard semantics of `avoided-loss`; `serac` owns
  the discriminator semantics of `source-type-assessment`. The owner proposes changes; the other
  side copies.

## Consequences

- No coupling between build systems, Python environments or release cycles.
- A consumer can read either repository's files with one schema-driven reader.
- Someone must actually copy the files when either side changes; the contract tests catch a
  copy that is out of date (fixtures fail to validate).
- Because `serac` is empty today, rupture's `.v0` files are provisional in the sense that the
  first reconciliation may produce a `.v1`; `.v0` will still be honoured.

## Alternatives considered

- **A shared `contracts` git submodule or package.** Rejected: a code/repo dependency, and a
  third repository to govern.
- **Wait for `serac` to publish first.** Rejected: nothing exists to wait for, and rupture's
  Prompt 1 deliverables include the schema.
