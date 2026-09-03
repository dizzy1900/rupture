# RELEASE_STATUS

rupture does not predict earthquakes. This ledger says what runs today, under-claiming by design.

**Phase:** Prompt 1 — Foundations. **State:** Phase 1 (governance, domain, ports, contracts) complete;
Phase 2 (catalogues, ETAS, evaluation, hazard) not started. Last updated 2026-09-03.

Maturity scale: `not started` · `scaffold` (structure, no behaviour) · `stub` (runs, exits
"not implemented") · `working` (offline tests pass) · `validated` (ran on real data, results recorded).

| Component | Maturity | Notes |
|---|---|---|
| Repository, CI, tooling | working | `uv`, ruff, mypy --strict, pytest (sockets disabled), import-linter; CI offline job green |
| Governance docs (CLAUDE, ARCHITECTURE, EVALUATION_PROTOCOL, GLOSSARY, DATA_SOURCES, CREDENTIALS, 16 ADRs) | working | protocol written before any model run |
| Language gate `validate-language` | working | allowlist: one sentence, the banned list itself, glossary headings, the GMPE term of art |
| Domain models (`Event`, `Catalog`, `Region`, `ForecastGrid`, `FitResult`, `EvaluationResult`, `HazardCurveSet`, loss and avoided-loss, `SourceTypeAssessment`) | working | pydantic v2, frozen, UTC-enforced; half-open time filters; validators for finite non-negative rates and snapshot hashes |
| Contracts `contracts/*.v0.json` + `schema-check` gate | working | 11 schemas generated from the models; drift fails CI |
| Ports (`CatalogSource`, `ForecastModel`, `Evaluator`, `HazardEngine`, `Tracker`, `GridStore`) | working | Protocols only; no adapters yet |
| `rupture underwriting-check` | stub | round-trips the example `AvoidedLossRequest` through the schema, then exits 2 "not implemented: Prompt 2" |
| Catalogue adapters (ComCat, ISC, ISC-GEM, GCMT), `rupture catalog build`, `validate-catalog` | not started | Phase 2A |
| Test regions `data/regions/`, fixtures `data/fixtures/` | not started | Phase 2A |
| GEM Global Active Faults, OpenQuake source models | not started | Phase 2A; Türkiye via ESHM20; California and Nepal gaps (ADR-0008) |
| ETAS baseline (`etas_mizrahi`), `rupture forecast fit/issue`, `validate-etas` | not started | Phase 2B |
| CSEP harness (`pycsep`), `rupture evaluate [schedule]`, `validate-eval` | not started | Phase 2B |
| OpenQuake adapter, `rupture hazard demo`, `validate-hazard` | not started | Phase 2C; Docker is not installed on the development machine, CI runs the demo |
| Docker image, `infra/jobs/*.yaml` | not started | Phase 2C |
| `make promote` | working | refuses unless `validate-rupture` is green |

## Known gaps

- No catalogue has been built, no ETAS fit performed, no forecast issued, no evaluation run.
- No challenger models; no loss layer; no cascade layer (Prompt 2).
- Open OpenQuake source models: Türkiye (ESHM20) only; none verified for California (USGS NSHM is in
  nshmp format, not NRML) or Nepal.
- Nepal catalogue completeness is expected to limit ETAS fits (Mc ≈ 4.5; sparse before ~2000).
- The OpenQuake demo cannot run on the development machine (no Docker); CI is the proving ground.
- ISC-GEM is a form-gated download; the adapter reads a local CSV.
- `serac` is empty as of 2026-09-03: the shared contracts are published here first.
