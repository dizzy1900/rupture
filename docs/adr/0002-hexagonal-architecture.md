# ADR-0002 — Hexagonal architecture (ports and adapters)

- **Status:** accepted
- **Date:** 2026-09-03

## Context

rupture wraps several heavy, externally maintained libraries and services (obspy, the `etas`
package, pycsep, the OpenQuake engine in Docker, DVC) whose APIs change, and it must be testable
offline on fixtures. The domain — events, catalogues, regions, forecast grids, evaluation results,
hazard curves, loss and avoided-loss contracts — must stay independent of any of them so that
contracts can be exported and challengers swapped in without touching the models.

## Decision

- `src/rupture/domain/` holds pure pydantic v2 models and imports nothing from `adapters/`,
  `pipelines/`, `cli` or `validation/`.
- `src/rupture/ports/` holds `typing.Protocol` classes (`CatalogSource`, `ForecastModel`,
  `Evaluator`, `HazardEngine`, `Tracker`, `GridStore`) and imports only `domain`.
- `src/rupture/adapters/<family>/` implements ports; families (`catalogs`, `sources`,
  `forecasting`, `evaluation`, `hazard`) do not import each other.
- `src/rupture/pipelines/` orchestrates ports; `cli.py` wires adapters to pipelines.
- The rules are import-linter contracts in `pyproject.toml` (`[tool.importlinter]`):
  - "domain is pure" — `forbidden`: `rupture.domain` → `rupture.adapters`, `rupture.pipelines`,
    `rupture.cli`, `rupture.validation`;
  - "ports import only domain" — `forbidden`: `rupture.ports` → the same four;
  - "adapters do not import each other across families" — `independence` over the five adapter
    families.
  `make lint` runs `lint-imports`; CI fails on a violation.

## Consequences

- A `ForecastGrid` can be produced by ETAS today and by a challenger tomorrow with no change to
  the evaluator or the storage.
- Unit tests exercise pipelines with in-memory fakes of the ports; adapters are tested against
  fixtures (offline) and live services (integration, opt-in).
- The `etas`, pycsep and OpenQuake dependencies are quarantined in single modules, so an upstream
  API change is a one-file fix.
- Some boilerplate: every external capability needs a port and an adapter.

## Alternatives considered

- **Layered monolith calling libraries directly from pipelines.** Rejected: leaks library types
  into the domain, makes offline testing depend on the libraries' own fixtures, and couples the
  contracts to third-party schemas.
- **Enforce the layering by review only.** Rejected: import-linter makes it a build failure at
  negligible cost.
