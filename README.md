# rupture

**rupture does not predict earthquakes.**

rupture is a standalone, open-source **probabilistic seismic forecasting and cascade-loss model**.
It answers four questions, each with a settled method and a scored (never asserted) forecast layer:

| Layer | Question | Method |
|---|---|---|
| F0 Long-term hazard | Exceedance probability of ground motion at a site over 50 years | PSHA via the OpenQuake engine |
| F1 Time-dependent seismicity forecast | Rate of M ≥ m events per cell over the next day / week / month / year, given the catalogue to date | ETAS (operational baseline); challengers gated by CSEP tests |
| F2 Ground motion → loss | Expected loss to a portfolio for a scenario or forecast, and what an intervention avoids | OpenQuake scenario / event-based risk; published avoided-loss contract |
| F3 Triggered cascades | What a large event triggers (landslides, ice avalanches, liquefaction) and where | USGS ground-failure models; shared discriminator with `serac` |

Deterministic prediction of the time, place and magnitude of individual earthquakes has no
scientifically accepted method. rupture issues **rate-based, gridded forecasts** and scores them
against the ETAS baseline under prospective, likelihood-based tests (N-, M-, S-, L-tests, paired
T-test) in the manner of CSEP. The word "predict" is banned from this repository except in the
sentence above; `make validate-language` enforces it.

## Status

This repository is at **Prompt 1: Foundations** — catalogue infrastructure, the ETAS baseline, the
CSEP evaluation harness, the OpenQuake adapter, versioned contracts, validation gates and a release
ledger. Read [RELEASE_STATUS.md](RELEASE_STATUS.md) for what actually runs today; it under-claims by
design. Challenger models, the loss layer and the cascade layer are Prompt 2.

## Quick start

```bash
uv sync
make validate-rupture          # offline: lint, mypy --strict, tests, language gate, contract drift
uv run rupture --help
```

Everything under `make validate-*` runs offline from a fresh clone on committed fixtures cut from
real catalogues. Online data pulls and the OpenQuake Docker image are opt-in (`make test-integration`,
`make validate-hazard`).

## Layout

```
contracts/          versioned JSON Schemas published for downstream consumers
docs/               ARCHITECTURE, EVALUATION_PROTOCOL, GLOSSARY, DATA_SOURCES, CREDENTIALS, adr/
data/regions/       test-region polygons + metadata (california, nepal-himalaya, turkiye-eaf)
data/fixtures/      small real catalogue slices for offline tests, each with provenance
src/rupture/
  domain/           pure models: Event, Catalog, Region, ForecastGrid, EvaluationResult, contracts
  ports/            CatalogSource, ForecastModel, Evaluator, HazardEngine, Tracker, GridStore
  adapters/         catalogs · sources · forecasting · evaluation · hazard · storage
  pipelines/        build_catalog · fit_etas · run_forecast · evaluate
  validation/       the make validate-* gates
  cli.py            `rupture ...`
infra/              docker/ (the deployment unit) · jobs/ (portable manifests, AWS-annotated)
baselines/          ETAS fits per region (DVC-tracked)
```

Architecture is hexagonal: `domain/` imports nothing from `adapters/`, enforced in CI.

## Sibling project

[`serac`](https://github.com/dizzy1900/serac) is a separate standalone repository. The two share
**file contracts only** (`contracts/avoided-loss.v0.json`, `contracts/source-type-assessment.v0.json`),
never code.

## Licence

Apache-2.0. Data sources carry their own licences; see [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
