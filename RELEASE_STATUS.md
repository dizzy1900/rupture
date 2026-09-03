# RELEASE_STATUS

rupture does not predict earthquakes. This ledger says what runs today, under-claiming by design.

**Phase:** Prompt 1 — Foundations. **State:** bootstrap only (Phase 0).

| Component | Maturity | Notes |
|---|---|---|
| Repository, CI, tooling | scaffold | `uv`, ruff, mypy --strict, pytest, import-linter; CI offline job |
| Language gate | working | `make validate-language`, allowlist of one sentence + glossary terms |
| Everything else | not started | see the plan in Prompt 1 |

## Known gaps

- No domain contracts, catalogues, ETAS baseline, evaluation harness or OpenQuake adapter yet.
- No challenger models; no loss layer; no cascade layer (Prompt 2).

Maturity scale: `not started` · `scaffold` (structure, no behaviour) · `stub` (runs, returns
not-implemented) · `working` (offline tests pass) · `validated` (ran on real data, results recorded).
