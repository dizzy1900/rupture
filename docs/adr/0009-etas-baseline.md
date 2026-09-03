# ADR-0009 — ETAS baseline is the `etas` package (Mizrahi et al.) at a pinned commit

- **Status:** accepted
- **Date:** 2026-09-03

## Context

Non-negotiable 3: ETAS is a first-class citizen, fitted properly, with parameters and diagnostics
published. The brief fixes the implementation: the `etas` package by Mizrahi et al. (Mizrahi,
Nandan & Wiemer 2021 JGR: Solid Earth; 2021 SRL), wrapped behind the `ForecastModel` port; an
in-house re-implementation is out of scope for Prompt 1. The package is on GitHub
(`lmizrahi/etas`), MIT-licensed, not on PyPI, and requires Python ≥ 3.12.

## Decision

- Depend on `etas @ git+https://github.com/lmizrahi/etas@097f08b69a4f06f9c38d14799dedfbd4543144e3`
  in `pyproject.toml` (hatchling `allow-direct-references = true`). The pin is a commit, not a
  branch; moving it is an ADR-worthy change because it changes the baseline.
- `adapters/forecasting/etas_mizrahi.py` implements the `ForecastModel` port
  (`ports/forecast_model.py`):
  - `fit(catalog, region, cutoff) -> FitResult` filters to `event_type == earthquake`,
    `Mw ≥ Mc`, `origin_time < cutoff`, inside the region polygon; builds the package
    configuration (auxiliary and primary windows, `delta_m = 0.1`, `mc`, polygon); runs
    `etas.inversion.ETASParameterCalculation`; and returns a `FitResult` (`fit_cutoff`,
    `training_catalog_hash`, `n_events`, `mc`, `parameters`, `parameter_snapshot_hash`,
    `log_likelihood`, `diagnostics` with iterations and windows, `converged`), persisted under
    `baselines/etas/<region>/` (DVC-tracked).
  - `forecast(history, issue_time, horizon) -> ForecastGrid` runs stochastic continuations with
    `etas.simulation` from the fitted parameters on `history` restricted to
    `origin_time < issue_time`, bins to the region grid × magnitude bins, and returns a
    `ForecastGrid` whose `parameter_snapshot_hash` is
    `rupture.domain.forecast.snapshot_hash(parameters)` (the same value `FitResult` validates),
    with `fit_cutoff`, `training_catalog_hash` and `n_simulations` carried through. The
    simulation seed is recorded.
  - `parameter_snapshot()` returns the parameter dictionary the next `forecast` call would use.
- The parametrisation is the package's (μ, k0, a, c, ω with p = 1 + ω, τ, d, γ, ρ; several stored
  as log10); see `docs/GLOSSARY.md` § ETAS. rupture records them as stored and does not
  re-parametrise.
- Mc for the fit comes from `rupture catalog build` (maximum curvature +0.2 and b-value
  stability, both published), with the package's `mc_b_est` KS estimate as a cross-check.
- If a fit does not converge, the diagnostics say so and `validate-etas` fails; the fit is not
  used.

## Consequences

- The baseline is a peer-reviewed, actively used implementation rather than a straw man written
  in-house.
- Reproducibility: the commit pin plus `training_catalog_hash` plus `parameter_snapshot_hash`
  plus seed identify every forecast.
- The dependency is installed from git, so `uv sync` needs network the first time; the lockfile
  records the commit.
- Upstream API drift is isolated to one module; the two entry points relied on
  (`inversion.ETASParameterCalculation`, `simulation`) are named here so a future upgrade knows
  what to check.

## Alternatives considered

- **In-house ETAS.** Out of scope by the brief; would also invite the "our baseline is weak"
  criticism CSEP history warns about.
- **Other ETAS codes (e.g. pyetas variants, R packages).** Rejected: the brief fixes Mizrahi et
  al.; their handling of incompleteness and of data-driven windows is what rupture wants.
- **Pin to a tag or branch.** Rejected: the repository has no release tags suitable for pinning
  at this date; a commit hash is unambiguous.
