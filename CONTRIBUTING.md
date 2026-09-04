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
- No `TODO` without an issue reference. The one `TODO` in the tree is inside a third-party file
  vendored verbatim (`tests/fixtures/cascade/usgs_groundfailure/jessee_2018.py.txt`), which the
  fixture rule forbids editing; see `CLAUDE.md` § Repository conventions.
- Commits are small and describe the *why*.

### What CI runs, and when

- The **offline job** runs on **every push, on any branch, and on every pull request**: ruff,
  `mypy --strict`, import-linter, the offline test suite, the nine gates that need neither network
  nor Docker, and `make underwriting-check`. A feature branch pushed before its pull request exists
  gets the same signal as one pushed after; the concurrency group cancels superseded runs.
- The **`hazard-integration` job** — pull the pinned `openquake/engine` image, run
  `make validate-hazard`, run the Docker integration tests — runs on pushes to `main` and on manual
  dispatch. It sets `RUPTURE_HAZARD_REQUIRE=1`, so a skip there is a failure. Locally,
  `make validate-hazard` skips with a printed reason where Docker is absent or the host is arm64.
- **Adding a gate means adding a CI step.** The offline job's last step compares the workflow's
  gate list against the `GATES` tuple in `src/rupture/validation/registry.py` and fails if they
  disagree, so a gate cannot be registered and then quietly never run.

## Licence

By contributing you agree your work is licensed under Apache-2.0 (see [LICENSE](LICENSE)).
