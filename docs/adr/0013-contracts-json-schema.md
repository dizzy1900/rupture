# ADR-0013 — Contracts as versioned JSON Schema exported from pydantic

- **Status:** accepted
- **Date:** 2026-09-03

## Context

Downstream consumers (decision and financial layers) and the sibling `serac` integrate with
rupture through files, not code (non-negotiable 6). The contracts must be machine-checkable,
versioned, and impossible to drift silently from the models that produce the data.

## Decision

- Every public domain model is a pydantic v2 model in `src/rupture/domain/`, registered in
  `domain/contracts.py` (`CONTRACTS`). Eleven contracts: `event`, `catalog`, `region`,
  `forecast-grid`, `fit-result`, `evaluation-result`, `hazard-curve-set`, `exposure-portfolio`,
  `loss-result`, `avoided-loss` (an envelope `{request, response}` of
  `AvoidedLossRequest`/`AvoidedLossResponse`, so both ship in one file as `serac`'s contract
  does) and `source-type-assessment`. Schemas are draft 2020-12 with a stable `$id` under
  `https://github.com/dizzy1900/rupture/contracts/`.
- `rupture schema export [--out DIR]` writes each schema to `contracts/<name>.vN.json`;
  `rupture schema export --check` (`make schema-check`, part of `VALIDATE_GATES`; the same check
  is the `schema` gate in `validation/schema.py`) fails if the files on disk differ from the
  export. CI runs it.
- The two shared contracts also carry `contract_version` inside the payload so a file can be
  checked without knowing where it came from.
- **Versioning**: the version is in the filename (`.v0`, `.v1`, ...), semver-ish at the major
  level. Within a version, changes are **additive only** (new optional fields, new enum members
  that consumers are told to tolerate); renaming, removing, retyping or making a field required
  bumps the version and leaves the old file in place. `contracts/README.md` states this policy.
- `tests/contract/` round-trips fixtures through the schemas and models;
  `tests/contract/fixtures/avoided-loss.request.example.json` and
  `tests/contract/fixtures/serac/source-type-assessment.example.json` are the shared examples.
- Field names are generic (`scenario_id`, `portfolio_id`, `expected_loss`, `intervention`,
  `interval`) so a consumer can read rupture's and `serac`'s files with one reader (ADR-0014).

## Consequences

- Consumers validate rupture output with any JSON Schema library; no Python required.
- A model change without a schema regeneration is a CI failure, not a surprise for a consumer.
- Old versions stay readable; consumers upgrade on their own schedule.
- Discipline cost: an incompatible change means a new file and a deprecation note.

## Alternatives considered

- **Publish a Python package as the contract.** Rejected: code dependency, and useless to
  non-Python consumers.
- **Protobuf / Avro.** Rejected: JSON Schema falls out of pydantic for free and the payloads are
  small, human-readable records.
- **Hand-written schemas.** Rejected: they drift.
