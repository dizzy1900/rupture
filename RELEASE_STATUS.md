# RELEASE_STATUS

rupture does not predict earthquakes. This ledger says what runs today, under-claiming by design.

**Phase:** Prompt 1 — Foundations. **State:** Phase 2 branches (catalogues, ETAS + evaluation,
hazard) merged; QA fixes in progress; real ETAS fits and the pseudo-prospective schedule not yet run.
Interim ledger — rewritten at the end of Phase 4. Last updated 2026-09-03.

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
| Catalogue adapters (ComCat, ISC, GCMT; ISC-GEM parser only), `rupture catalog build`, `validate-catalog` | validated (interim) | three real 1976–2026 builds done 2026-09-03 (outputs DVC-tracked, not committed); California Mw coverage 49 % at M ≥ 3.95 before ADR-0019 policy; ISC-GEM never fetched (form-gated) |
| Test regions `data/regions/`, fixtures `data/fixtures/` | working | Mc from real builds; California Mc 3.70 is an artefact (see Known gaps); thresholds being raised per ADR-0019 |
| GEM Global Active Faults, OpenQuake source models | working | GAF fetched (13 696 faults); ESHM20 fetched for Türkiye (40 MB); California and Nepal gaps (ADR-0008) |
| ETAS baseline (`etas_mizrahi`), `rupture forecast fit/issue`, `validate-etas` | working | smoke fit on a real California fixture only; no production fit yet (blocked on catalogue reader convergence, in progress) |
| CSEP harness (`pycsep`), `rupture evaluate [schedule]`, `validate-eval` | working | N/M/S/L/CL + T/W on the fixture schedule (6 windows); no protocol run yet |
| OpenQuake adapter, `rupture hazard demo`, `validate-hazard` | validated (CI) | demo ran in `openquake/engine:3.26.2` in CI run 33744626791 (2026-09-03); Docker absent locally, gate skips with reason |
| Docker image, `infra/jobs/*.yaml` | scaffold | Dockerfile and compose never built or run anywhere; manifests schema-validated |
| `make promote` | working | refuses unless `validate-rupture` is green |

## Known gaps

- Three catalogues built; no production ETAS fit, no protocol forecast issued, no protocol evaluation run yet.
- California: Mc 3.70 / b 0.59 from the first build is an artefact of 49 % Mw coverage (ML/Md unconverted); ADR-0019 adopts the CSEP network-preferred policy and a rebuild is in progress.
- Nepal and Türkiye b-value-stability Mc (4.7, 4.6) exceed the provisional targets (4.5, 4.0); ADR-0019 raises the targets.
- No challenger models; no loss layer; no cascade layer (Prompt 2).
- Open OpenQuake source models: Türkiye (ESHM20) only; none verified for California (USGS NSHM is in
  nshmp format, not NRML) or Nepal.
- Nepal catalogue completeness is expected to limit ETAS fits (Mc ≈ 4.5; sparse before ~2000).
- The OpenQuake demo cannot run on the development machine (no Docker); CI is the proving ground.
- ISC-GEM is a form-gated download; the adapter reads a local CSV.
- `serac` is empty as of 2026-09-03: the shared contracts are published here first.
