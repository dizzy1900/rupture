# contracts/

Versioned JSON Schemas (draft 2020-12) that downstream consumers integrate against. They are
**generated** from the pydantic models in `src/rupture/domain/` by `rupture schema export`
(`make schema-export`) and checked for drift in CI (`make schema-check`). Do not edit by hand.

There are **19** of them. The authoritative list is `rupture.domain.contracts.CONTRACTS`, which is
what `rupture schema export` iterates and what `make schema-check` compares against this directory;
if this table and that mapping ever disagree, the mapping is right.

**Catalogue and forecast (F1)**

| File | Model | Purpose |
|---|---|---|
| `event.v0.json` | `Event` | one catalogued event with homogenised Mw, type tag and provenance |
| `catalog.v0.json` | `Catalog` | events + completeness estimates + bounds + homogenisation log |
| `region.v0.json` | `Region` | test-region polygon, grid, thresholds, fitted Mc |
| `forecast-grid.v0.json` | `ForecastGrid` | expected counts per cell per magnitude bin for one horizon |
| `fit-result.v0.json` | `FitResult` | model parameters, diagnostics and the hard cutoff they were fitted to |
| `evaluation-result.v0.json` | `EvaluationResult` | one CSEP-style test outcome against a frozen target slice |
| `aftershock-forecast.v0.json` | `AftershockForecast` | the operational aftershock service's output: probabilities by magnitude and horizon for one sequence |

**Hazard and ground motion (F0)**

| File | Model | Purpose |
|---|---|---|
| `hazard-curve-set.v0.json` | `HazardCurveSet` | classical PSHA output |
| `ground-motion-field.v0.json` | `GroundMotionField` | intensity measures at a set of sites for one rupture, from either ground-motion adapter |

**Exposure, vulnerability and loss (F2)**

| File | Model | Purpose |
|---|---|---|
| `exposure-portfolio.v0.json` | `ExposurePortfolio` | the assets a loss is computed for |
| `exposure-import.v0.json` | `ExposureImport` | the shape a third party hands rupture to build a portfolio from |
| `fragility-model.v0.json` | `FragilityModel` | damage-state exceedance against an intensity measure, with its source or an `assumption` flag |
| `consequence-model.v0.json` | `ConsequenceModel` | damage state → loss ratio, with the same honesty flag |
| `loss-result.v0.json` | `LossResult` | expected loss with interval |
| `avoided-loss.v1.json` | `AvoidedLossRequestV1` / `AvoidedLossResponseV1` | **the public output contract** for decision and financial layers; the shape reconciled with `serac` (ADR-0021), and what `rupture underwriting-check` and `rupture risk` produce |
| `avoided-loss.v0.json` | `AvoidedLossRequest` / `AvoidedLossResponse` | the first published version. Superseded in practice by v1 and kept published: a version is never withdrawn |

**Cascades (F3)**

| File | Model | Purpose |
|---|---|---|
| `ground-failure-field.v0.json` | `GroundFailureField` | modelled landslide / liquefaction susceptibility over a footprint. Susceptibility and exposure — never a statement that a slope will fail |
| `cascade-exposure.v0.json` | `CascadeExposure` | slope units and assets exposed to a cascade footprint, naming the source of the units (a real `serac` export, or the labelled fallback of ADR-0027) |
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

`serac` and `rupture` share schemas by **copying the schema file**, never by importing code.
`source-type-assessment.v0.json` was published by rupture first. `avoided-loss` has already been
through the reconciliation rule once: serac's shape and rupture's v0 disagreed, they were merged to
a field-compatible superset, and the result is `avoided-loss.v1.json` (ADR-0021). v0 stays
published.

In the other direction rupture *consumes* serac's `contracts/slope-unit.v0.json`. serac has
published no slope-unit records yet, so `SeracSlopeUnitSource` falls back to a stand-in built from
serac's own AOI files with every terrain attribute null, and labels itself as a fallback in the
`CascadeExposure` it produces (ADR-0027). Two field types disagree between the two models —
`glacier_cover` boolean against float, `elevation_band_m` pair against string — and the mapping is
recorded in that ADR rather than silently applied.

Example payloads: `tests/contract/fixtures/`.
