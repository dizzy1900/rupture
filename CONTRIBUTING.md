# Contributing to rupture

rupture does not predict earthquakes. Every contribution is held to the non-negotiables in
[CLAUDE.md](CLAUDE.md); read them first.

## Setup

```bash
uv sync
make validate-rupture
```

## Rules of the road

1. **Language.** The word "predict" and its derivatives are banned from docs, identifiers and outputs
   (`make validate-language`). Use *forecast*.
2. **No leakage.** Anything that fits or issues a forecast must only see events with
   `origin_time < cutoff`. Tests assert this on real timestamps.
3. **No fabricated data.** Adapters fetch or fail loudly. Unit tests run offline on committed
   fixtures cut from real catalogues, each with a `provenance.json`. Unknowns are `null`.
4. **Provenance.** Every ingested record carries `source`, `source_url`, `retrieved_at`, `sha256`,
   `licence` and `adapter_version`.
5. **Architecture.** Hexagonal. `src/rupture/domain/` imports nothing from `adapters/`
   (enforced by import-linter in CI).
6. **Decisions are ADRs** in `docs/adr/`. Do not relitigate a settled ADR in a PR; write a new ADR.
7. **Honesty in `RELEASE_STATUS.md`.** Under-claim. If it did not run, say so.

## Workflow

- Branch from `main`; keep `ruff`, `mypy --strict` and the offline suite green.
- Network or Docker tests are marked `integration` and are opt-in (`pytest -m integration`).
- No `TODO` without an issue reference.
- Commits are small and describe the *why*.

## Licence

By contributing you agree your work is licensed under Apache-2.0 (see [LICENSE](LICENSE)).
