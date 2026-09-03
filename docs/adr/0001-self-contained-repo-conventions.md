# ADR-0001 — Self-contained repository conventions

- **Status:** accepted
- **Date:** 2026-09-03

## Context

rupture has no parent organisation, no internal platform and no inherited house conventions. The
brief's non-negotiable 6 requires that no private repository, internal package or hosted platform
be a dependency, and that rupture define and document its own conventions. Its only sibling,
`serac`, is consumed through file contracts. A fresh clone must be able to run the whole offline
gate suite with `uv sync && make validate-rupture`.

## Decision

rupture defines the following conventions, recorded here and summarised in `CLAUDE.md`:

1. **DVC-versioned `data/` and `baselines/`.** Fetched payloads, derived catalogues, forecasts and
   ETAS fits are DVC-tracked; git holds code, docs, contracts, region definitions, small real
   fixtures and DVC pointers. The default remote is a local placeholder (`.dvc/local-remote`) so a
   clone works without an account; production points at S3 via `dvc remote modify`.
2. **Validation gates** live in `src/rupture/validation/<name>.py`, each exposing
   `run(repo_root: Path) -> GateResult`, are named in `validation/registry.py` (`GATES`), and are
   invoked as `rupture validate <name>` behind `make validate-<name>`. Gates are offline-safe or skip with a printed reason. `make validate-rupture`
   aggregates `lint typecheck test` and `$(VALIDATE_GATES)`; new gates register by adding
   `mk/<name>.mk` with `VALIDATE_GATES += validate-<name>`.
3. **`make promote`** refuses unless `validate-rupture` is green and prints every skip reason.
   **`make underwriting-check`** validates the `AvoidedLossRequest` round-trip and exits non-zero
   "not implemented: Prompt 2" until the loss layer exists.
4. **`RELEASE_STATUS.md`** is the ledger: component × maturity (`not started`, `scaffold`, `stub`,
   `working`, `validated`), filled truthfully and under-claiming; "Known gaps" is mandatory.
5. **Deployment unit is a plain Docker image** (`infra/docker/Dockerfile`); **portable job
   manifests** in `infra/jobs/*.yaml` carry an `aws:` annotation block (ADR-0016).
6. **`contracts/`** holds versioned JSON Schemas exported from the domain models; downstream
   consumers integrate only through them (ADR-0013).
7. Decisions are ADRs in `docs/adr/`; all timestamps UTC; windows half-open `[from, to)`;
   provenance on every record; no `TODO` without an issue reference.

## Consequences

- Anyone can clone, sync and validate offline with no credentials.
- Adding a gate or a job never requires touching a shared platform configuration.
- The ledger and the gates make over-claiming a build failure rather than a review comment.
- The cost is some duplication (a Makefile, DVC and manifests that a platform would otherwise
  provide); this is accepted as the price of independence.

## Alternatives considered

- **Adopt an existing organisation's template.** Rejected: there is no organisation, and the
  brief forbids inheriting private conventions.
- **A hosted MLOps platform for data and runs.** Rejected: would make a hosted service a
  dependency of the offline suite and of reproducibility.
- **Git LFS instead of DVC.** Rejected: no pipeline stages, no remote abstraction over S3 and
  local, and worse handling of many-file outputs; DVC also documents `dvc.yaml` lineage.
