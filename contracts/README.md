# contracts/

Versioned JSON Schemas (draft 2020-12) that downstream consumers integrate against. They are
**generated** from the pydantic models in `src/rupture/domain/` by `rupture schema export`
(`make schema-export`) and checked for drift in CI (`make schema-check`). Do not edit by hand.

| File | Model | Purpose |
|---|---|---|
| `event.v0.json` | `Event` | one catalogued event with homogenised Mw, type tag and provenance |
| `catalog.v0.json` | `Catalog` | events + completeness estimates + bounds + homogenisation log |
| `region.v0.json` | `Region` | test-region polygon, grid, thresholds, fitted Mc |
| `forecast-grid.v0.json` | `ForecastGrid` | expected counts per cell per magnitude bin for one horizon |
| `fit-result.v0.json` | `FitResult` | model parameters, diagnostics and the hard cutoff they were fitted to |
| `evaluation-result.v0.json` | `EvaluationResult` | one CSEP-style test outcome against a frozen target slice |
| `hazard-curve-set.v0.json` | `HazardCurveSet` | classical PSHA output (F0) |
| `exposure-portfolio.v0.json` | `ExposurePortfolio` | assets a loss is computed for (F2, schema only in Prompt 1) |
| `loss-result.v0.json` | `LossResult` | expected loss with interval (F2, schema only in Prompt 1) |
| `avoided-loss.v0.json` | `AvoidedLossRequest` / `AvoidedLossResponse` | **public output contract** for decision and financial layers; shared by file with `serac` |
| `source-type-assessment.v0.json` | `SourceTypeAssessment` | **shared with `serac`**: probability an event is a mass movement rather than a tectonic rupture |

## Versioning policy (ADR-0013)

- The `.vN` in the file name is the contract version. `v0` means pre-release: shape may still
  change, but every change is recorded in the ADR log and in `RELEASE_STATUS.md`.
- Within a version, changes are **additive only** (new optional fields). Renames, removals,
  type changes or tightened constraints bump `N` and the old file stays published.
- `contract_version` is also carried inside the payload for the two shared contracts so a file
  can be checked without knowing where it came from.
- All timestamps are RFC 3339 in UTC. Unknowns are `null`, never sentinel values.

## Coordination with `serac` (ADR-0014)

`serac` and `rupture` share `avoided-loss.v0.json` and `source-type-assessment.v0.json` by
**copying the schema file**, never by importing code. As of 2026-09-03 the `serac` repository is
empty, so these files are the first publication; if `serac` later publishes a differing schema, the
two are reconciled to a field-compatible superset and the version bumped here.

Example payloads: `tests/contract/fixtures/`.
