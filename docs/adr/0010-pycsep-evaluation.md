# ADR-0010 — pycsep 0.8.0 for CSEP tests and containers

- **Status:** accepted
- **Date:** 2026-09-03

## Context

The evaluation protocol (`docs/EVALUATION_PROTOCOL.md`) requires the CSEP consistency tests
(N, M, S, L, CL) and the paired comparison tests (T, W) on gridded rate forecasts. pycsep (Savran
et al. 2022) is the reference open implementation maintained by the CSEP community; version 0.8.0
is on PyPI, supports Python 3.12, and provides `GriddedForecast`, `CSEPCatalog`, the RELM
California region, `poisson_evaluations.{number_test, magnitude_test, spatial_test,
likelihood_test, conditional_likelihood_test, paired_t_test, w_test}` and plotting utilities.

## Decision

- Depend on `pycsep==0.8.0` (exact pin; the test implementations define the protocol's numbers).
- `adapters/evaluation/pycsep.py` implements the `Evaluator` port (`ports/evaluator.py`:
  `evaluate(forecast, target, tests, *, n_simulations=1000, alpha=0.05, seed=None)`,
  `compare(forecast, benchmark, target, *, alpha=0.05)`, `plot_bundle(...)`): converts
  `ForecastGrid` ↔ `GriddedForecast`, target `Catalog` slice → `CSEPCatalog`, runs the requested
  `TestName`s with the protocol's α and simulation count and a recorded seed, and maps results to
  `EvaluationResult` (statistic, `quantile` or `quantile_low`/`quantile_high` or `p_value`,
  `passed` — `null` when undecidable — `n_target_events`, `target_catalog_hash`). Plot bundles use
  `csep.utils.plots`.
- The `california` region polygon and grid are taken from `csep.core.regions.california_relm_region`
  so forecasts and tests share cells exactly; the other two regions use rupture's own polygons at
  the same 0.1° cell size.
- pycsep's heavy dependencies (cartopy, rasterio) are accepted; if wheel resolution fails on a
  platform, plotting becomes an optional path and the tests still run.

## Consequences

- Test statistics are those the CSEP community publishes and reviewers recognise.
- Version upgrades change the protocol's arithmetic and therefore go through an ADR and a
  re-run of the schedule.
- Adapters never expose pycsep types to the domain; `EvaluationResult` is rupture's own.

## Alternatives considered

- **Re-implement the tests in-house.** Rejected: reproducing the reference implementation adds
  risk and no value; a reviewer would ask why.
- **Pin to a range (`>=0.8`).** Rejected: a minor release could change simulation details and
  silently alter pass rates.
