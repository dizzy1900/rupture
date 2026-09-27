# ADR-0071 — Import-linter contracts for reporting and the remaining adapter families

- **Status:** accepted (amended 2026-09-27)
- **Date:** 2026-09-13 (UTC)
- **Amends:** [ADR-0002](0002-hexagonal-architecture.md) (adapter independence listed five families),
  [ADR-0049](0049-report-figures-from-committed-evidence.md) (reporting had no contract)

## Context

Two holes sat next to the contracts that CI actually runs.

ADR-0002's independence contract named `catalogs`, `sources`, `forecasting`, `evaluation` and
`hazard`. Five more adapter packages have existed for some time — `groundmotion`, `exposure`,
`vulnerability`, `cascade`, `storage` — and were not in it. A green `lint-imports` said nothing
about those families importing each other.

ADR-0049 put figures in `src/rupture/reporting/` and recorded that no contract mentioned the
package. The modules import only the standard library, `json` and `matplotlib`, but that was a
fact about today's code, not a rule.

## Decision

1. **`rupture.reporting` is a forbidden contract.** It must not import `adapters`, `pipelines`,
   `cli`, `validation`, `commands`, `risk`, `cascade`, `models`, `services`, `scoring` or
   `preregistration` (the ADR-0056 package, which landed first and is added to the domain, ports
   and scoring contracts the same way). Domain is allowed; so are the standard library and matplotlib. The current modules are clean, so
   there is nothing to grandfather.

2. **The adapter independence contract lists every `adapters.*` package that exists on disk.**
   The five newer families are added to `modules`. Six pre-existing cross-family imports are
   named in `ignore_imports` so a seventh cannot arrive silently:

   - `groundmotion.openquake_scenario` and `groundmotion.openquake_event_based` each import
     `hazard.job_builder` and `hazard.openquake_docker` (the OpenQuake adapters wrap the pinned
     docker runner rather than duplicating it);
   - `cascade.chamoli` imports `groundmotion.distances` and `groundmotion.native` (the
     non-ShakeMap scenario route through the native GSIM).

   Inverting those six is a separate change. They are a ratchet, not a refactor.

3. **A unit test fails if a new `adapters.*` package appears without being listed**, by scanning
   `pkgutil` against the contract in `pyproject.toml`. That is how the last five families escaped
   the list.

Measured with `PYTHONPATH=src` and `lint-imports` on 2026-09-13: 206 files, 711 dependencies;
9 contracts kept, 6 ignored adapter edges, 6 ignored models→pipelines edges (unchanged).

## Consequences

- A new import from `reporting` into pipelines, CLI, validation, services or adapters fails CI.
- A new adapter family that is not added to the independence contract fails
  `tests/unit/architecture/test_adapter_families.py`.
- A new cross-family adapter import fails `lint-imports` unless it is named in `ignore_imports`
  *and* in that test's frozen set.
- The six models→pipelines ignores from the Prompt 2 contracts are untouched.

## Alternatives considered

- **Leave the holes in RELEASE_STATUS and keep writing them down.** Rejected: a known gap that
  CI does not close is a gap that grows.
- **Refactor the six adapter edges to restore independence without ignores.** Rejected for this
  change: the OpenQuake ground-motion adapters exist specifically to wrap the hazard runner, and
  Chamoli is the documented scenario route through the native GSIM. Untangling either is a
  separate evidence burden.
- **A `layers` contract that allowlists domain for reporting.** Equivalent in force to the
  forbidden contract; forbidden matches every other contract in this file.

## Amendment (2026-09-27) — shared adapter infrastructure, and the eleventh family

Adding `observations` (ADR-0067) as an eleventh family exposed eight imports from it into
`catalogs`: the USGS real-time and FDSN event feeds reused ComCat's parsing, and all three new
adapters reused `catalogs._http` and `catalogs.fixtures`. Naming those eight in `ignore_imports`
would have made the contract green by exempting the thing it exists to catch. The layout was
changed instead, and the count of by-name exceptions is still six.

1. **The two catalogue-shaped feeds moved into `catalogs`.** `usgs_feed` and `fdsn_events` emit
   `Catalog`s and reuse ComCat's GeoJSON mapping, so they belong to that family; their imports of
   `catalogs._common` and `catalogs.comcat` are now intra-family. `observations` holds the NGL
   GNSS adapter only.

2. **HTTP fetch and fixture loading are shared infrastructure, not part of a family.** They moved
   to `rupture.adapters._http` and `rupture.adapters.fixtures`: plain modules directly under
   `rupture.adapters`, which the independence contract does not cover because they are not
   families. That is only sound if they stay leaves, so a new `forbidden` contract, *shared
   adapter infrastructure imports no adapter family*, forbids both from importing any of the
   eleven families or any outer layer. They may import `rupture.domain`, `rupture.__version__`
   and the standard library / `requests`.

3. **The side door is closed by test.** `tests/unit/architecture/test_adapter_families.py` now
   also fails if a plain module appears directly under `rupture.adapters` without being listed
   as a shared leaf, and if the shared-leaf contract stops forbidding any family. A new shared
   module is therefore a reviewed change to `pyproject.toml`, not a file dropped in a directory.

Verified by probe, not assumed: appending an import of `rupture.adapters.catalogs` to
`_http.py` breaks both the shared-leaf contract and the independence contract, and an empty
`rupture/adapters/_sidedoor.py` fails the test. With the tree as committed: 10 contracts kept,
6 ignored adapter edges, 6 ignored models→pipelines edges.
