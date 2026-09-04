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

**Prompt 1 (foundations) and Prompt 2 (challengers, loss, cascades) are both complete.** Prompt 1
built the catalogue infrastructure, the ETAS baseline, the CSEP evaluation harness, the OpenQuake
adapter, versioned contracts, validation gates and a release ledger. Prompt 2 added three challenger
models and an ensemble, the loss layer, the cascade layer and an operational aftershock service.

**No challenger was promoted.** That is a result, not an omission:
[reports/CHALLENGER_EVALUATION.md](reports/CHALLENGER_EVALUATION.md) has the evidence, the figures
and the fraction of apparent skill that vanished once the leakage controls were applied.

Read [RELEASE_STATUS.md](RELEASE_STATUS.md) for what actually ran; it under-claims by design, and
its "Known gaps" section is the honest list of what this repository cannot do.

## Quick start

```bash
uv sync
make validate-rupture          # offline: lint, mypy --strict, tests, and all ten gates
uv run rupture --help
make underwriting-check        # price the serac Nepal corridor against the MHT scenario
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
  risk/             ground motion → damage → loss → avoided loss (F2)
  cascade/          earthquake-triggered ground failure and slope exposure (F3)
  models/           challenger forecast models and the ensemble
  services/         operational products (the aftershock forecast service)
  validation/       the make validate-* gates (ten, listed in validation/registry.py)
  reporting/        figures for reports/*.md, drawn only from committed evidence
  commands/         one typer sub-application per CLI noun
  cli.py            `rupture ...`
infra/              docker/ (the deployment unit) · jobs/ (portable manifests, AWS-annotated)
baselines/          ETAS and gridded fits per region (DVC-tracked); the NTPP weights (git-tracked)
reports/            the published evidence: model cards, protocol and challenger schedules, figures
```

Architecture is hexagonal: `domain/` imports nothing from `adapters/`, enforced in CI.

## Sibling project

[`serac`](https://github.com/dizzy1900/serac) is a separate standalone repository. The two share
**file contracts only** — `contracts/avoided-loss.v1.json` (reconciled shape, ADR-0021),
`contracts/avoided-loss.v0.json` (still published), `contracts/source-type-assessment.v0.json`, and
serac's own `slope-unit.v0.json` in the other direction — never code. serac has not exported any
slope units yet, so rupture's cascade layer runs on a fallback that labels itself as one and leaves
every terrain attribute null (ADR-0027).

## Licence

Apache-2.0. Data sources carry their own licences; see [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
