# Architecture decision records

One file per decision. A settled ADR is not relitigated in a PR; write a new ADR that supersedes
it and update the Status of the old one. Format: Status / Date / Context / Decision /
Consequences / Alternatives considered. All dates UTC.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-self-contained-repo-conventions.md) | Self-contained repository conventions | accepted |
| [0002](0002-hexagonal-architecture.md) | Hexagonal architecture (ports and adapters) | accepted |
| [0003](0003-python-toolchain.md) | Python 3.12, uv, ruff, mypy --strict, pytest with sockets disabled | accepted |
| [0004](0004-catalogue-sources-obspy-comcat-geojson.md) | Catalogue sources: obspy FDSN for ComCat and ISC; ComCat GeoJSON to keep `type`; libcomcat optional | accepted |
| [0005](0005-isc-gem-csv-ingestion.md) | ISC-GEM CSV ingestion via a manual, form-gated download | accepted |
| [0006](0006-gcmt-ndk-parser.md) | In-house GCMT NDK parser | accepted |
| [0007](0007-gem-global-active-faults.md) | GEM Global Active Faults as the fault database (CC-BY-SA-4.0) | accepted |
| [0008](0008-openquake-source-models-per-region.md) | OpenQuake source models per region: ESHM20 for Türkiye; California and Nepal gaps | accepted |
| [0009](0009-etas-baseline.md) | ETAS baseline is the `etas` package (Mizrahi et al.) at a pinned commit | accepted |
| [0010](0010-pycsep-evaluation.md) | pycsep 0.8.0 for CSEP tests and containers | accepted |
| [0011](0011-openquake-docker.md) | OpenQuake engine via the pinned Docker image `openquake/engine:3.26.2` | accepted |
| [0012](0012-data-layer.md) | Data layer: GeoParquet, zarr, STAC, pydantic v2, DVC | accepted |
| [0013](0013-contracts-json-schema.md) | Contracts as versioned JSON Schema exported from pydantic | accepted |
| [0014](0014-serac-coordination.md) | Coordination with the sibling `serac` by shared schema files | accepted |
| [0015](0015-pseudo-prospective-evaluation.md) | Pseudo-prospective evaluation with a hard 2022-01-01 cutoff | accepted |
| [0016](0016-deployment-docker-image-and-job-manifests.md) | Deployment unit is a plain Docker image; portable job manifests with `aws:` annotations | accepted |
| [0017](0017-catalogue-homogenisation-rules.md) | Catalogue homogenisation rules: precedence, association windows, magnitude conversions | accepted |
| [0018](0018-etas-issuance-without-refit.md) | Issuing ETAS forecasts from a stored fit without refitting | accepted |
| [0019](0019-target-thresholds-and-california-magnitude-policy.md) | Target thresholds follow the published Mc; California magnitude policy | accepted |
| [0020](0020-ground-motion-two-adapters.md) | A `GroundMotionEngine` port with two adapters | accepted |
| [0021](0021-avoided-loss-v1-serac-reconciliation.md) | Avoided loss v1 — reconciliation with the sibling `serac` | accepted |
| [0022](0022-leakage-engineering-for-learned-models.md) | Leakage engineering for learned models | accepted |
| [0023](0023-tracker-adapters.md) | Experiment tracking adapters | accepted |
| [0024](0024-hydropower-damage-state-decomposition.md) | Hydropower damage-state decomposition, and what is published versus assumed | accepted |
| [0025](0025-avoided-loss-intervention-models-and-scenarios.md) | Intervention models, the replacement-cost basis, and how the scenarios are built | accepted |
| [0026](0026-usgs-ground-failure-models.md) | USGS ground-failure models: which two, and where their coefficients come from | accepted |
| [0027](0027-serac-slope-units.md) | serac slope units: the file contract, the fixture-fallback rule, and the threshold | accepted |
| [0028](0028-operational-aftershock-forecast-service.md) | Operational aftershock forecast service: sequence window, refit schedule, fixed b, Poisson summary | accepted |
| [0029](0029-neural-point-process-challenger-and-shared-dataset-layer.md) | The C1a challenger is a neural-kernel Hawkes process, on a shared dataset layer | accepted |
| [0030](0030-openquake-runner-design.md) | OpenQuake runner: docker CLI via subprocess, demo-first validation, skip semantics | accepted |
| [0031](0031-gridded-spatio-temporal-challenger.md) | C1b is a small ConvLSTM over rasterised seismicity plus static covariates | accepted |
| [0032](0032-log-linear-ensemble.md) | The ensemble is a log-linear pool, weights fitted on a validation window, rates floored relatively | accepted |
| [0033](0033-gsim-coefficient-provenance-and-licence.md) | GSIM coefficient provenance and the AGPL question | accepted |
| [0034](0034-cite-published-titles-verbatim.md) | The banned-language allowlist admits published paper titles | accepted |
| [0035](0035-models-data-seam.md) | The `models/data` seam between the two challengers | accepted |
| [0039](0039-gem-exposure-licence.md) | GEM's global exposure and vulnerability models are not openly licensed | accepted |
| [0040](0040-promotion-rule-single-encoding.md) | Condition 2 of the promotion rule is the schedule-pooled paired T-test, and the rule is encoded once | accepted |
| [0041](0041-what-the-challenger-evaluation-does-not-cover.md) | What the challenger evaluation does not cover, and why it was not approximated | accepted |
| [0042](0042-stochastic-event-sets-and-expected-annual-loss.md) | Stochastic event sets from F1, and expected annual loss | accepted |
| [0043](0043-gsim-logic-tree-and-openquake-event-based.md) | A GSIM logic tree, and the engine's event-based path | accepted |
| [0044](0044-shutdown-warning-time-and-the-anchored-pair-crossing.md) | The automated shutdown depends on warning time, and the anchored pair crosses | accepted |
| [0045](0045-one-http-service-and-an-executed-refit-schedule.md) | One HTTP service, the grid over HTTP, and a refit schedule something actually runs | accepted |
| [0046](0046-etas-log-likelihood.md) | The ETAS log-likelihood rupture persists | accepted |
| [0047](0047-classical-psha-job-derived-from-the-source-model-manifest.md) | A classical PSHA job is derived from the source-model manifest, not written by hand | accepted |
| [0048](0048-licence-and-ci-platform.md) | Apache-2.0 as the repository licence, GitHub Actions as the CI platform, and a gate-coverage ratchet | accepted |
| [0049](0049-report-figures-from-committed-evidence.md) | Report figures are rendered from committed evidence, never from a model | accepted |
| [0050](0050-learned-ground-failure-hook.md) | a documented hook for a learned global ground-failure model, not trained here | accepted |
| [0051](0051-chamoli-ronti-scenario.md) | the Chamoli / Ronti scenario case: how a scenario without a published answer is built | accepted |
| [0052](0052-cascade-exposure-geoparquet.md) | CascadeExposure as GeoParquet: geometry, and the caveat in the file's metadata | accepted |
