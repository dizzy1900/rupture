# Architecture decision records

One file per decision. A settled ADR is not relitigated in a PR; write a new ADR that supersedes
it and update the Status of the old one. Format: Status / Date / Context / Decision /
Consequences / Alternatives considered. All dates UTC.

| ADR | Title | Status |
|---|---|---|
| [0001](0001-self-contained-repo-conventions.md) | Self-contained repository conventions | accepted |
| [0002](0002-hexagonal-architecture.md) | Hexagonal architecture with import-linter contracts | accepted |
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
| [0016](0016-deployment-docker-image-and-job-manifests.md) | Deployment unit is a plain Docker image; portable job manifests | accepted |
| [0017](0017-catalogue-homogenisation-rules.md) | Catalogue homogenisation rules: precedence, association windows, magnitude conversions | accepted |
| [0018](0018-etas-issuance-without-refit.md) | Issuing ETAS forecasts from a stored fit without refitting; expected counts analytic where the model allows | accepted |
| [0019](0019-target-thresholds-and-california-magnitude-policy.md) | Target thresholds follow the published Mc (Nepal 4.7, Türkiye 4.6); California network-preferred magnitudes assumed Mw-equivalent | accepted |
| [0020](0020-ground-motion-two-adapters.md) | A `GroundMotionEngine` port with two adapters: the OpenQuake container (authoritative) and a native GSIM evaluator verified against OpenQuake's own test vectors | accepted |
| [0021](0021-avoided-loss-v1-serac-reconciliation.md) | Avoided loss v1: shared value vocabulary and field aliases reconciled with the sibling `serac`, envelopes kept distinct | accepted |
| [0022](0022-leakage-engineering-for-learned-models.md) | Leakage engineering for learned models: causal features, blocked time-forward CV only, a labelled leaky ablation | accepted |
| [0023](0023-tracker-adapters.md) | Local-filesystem tracking is the default; Weights & Biases is optional and never required | accepted |
| [0026](0026-usgs-ground-failure-models.md) | USGS ground-failure models (Nowicki Jessee 2018 landslide, Zhu 2017 general liquefaction): coefficients taken from the USGS reference implementation, covariates a declared gap | accepted |
| [0027](0027-serac-slope-units.md) | serac slope units by file contract, with a labelled fixture fallback while serac has no export, and a screening threshold that is not a failure criterion | accepted |
| [0024](0024-hydropower-damage-state-decomposition.md) | Hydropower damage-state decomposition: HAZUS for powerhouse, switchyard and tunnel; intake and penstock explicitly assumed | accepted |
| [0025](0025-avoided-loss-intervention-models-and-scenarios.md) | Intervention models, the IRENA replacement-cost basis, and how the Gorkha and MHT scenarios are built | accepted |
| [0028](0028-operational-aftershock-forecast-service.md) | Operational aftershock forecast service: sequence window, refit schedule, fixed b, Poisson summary | accepted |
| [0029](0029-neural-point-process-challenger-and-shared-dataset-layer.md) | Challenger C1a is a neural-kernel Hawkes process, built on a shared `models/data` layer that implements the ADR-0022 leakage rules once | accepted |
| [0030](0030-openquake-runner-design.md) | OpenQuake runner: docker CLI via subprocess, demo-first validation, skip semantics | accepted |
| [0033](0033-gsim-coefficient-provenance-and-licence.md) | GSIM coefficients are numeric facts from the journal articles, extracted via oq-engine with attribution; rupture ships no AGPL code | accepted |
| [0034](0034-cite-published-titles-verbatim.md) | The banned-language allowlist admits published paper titles quoted verbatim, so rupture can cite its sources by name | accepted |
