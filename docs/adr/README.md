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
| [0018](0018-etas-issuance-without-refit.md) | Issuing ETAS forecasts from a stored fit without refitting; expected counts analytic where the model allows | accepted |
