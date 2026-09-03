# ADR-0012 — Data layer: GeoParquet, zarr, STAC, pydantic v2, DVC

- **Status:** accepted
- **Date:** 2026-09-03

## Context

rupture stores tabular geospatial data (catalogues, faults), gridded multi-dimensional data
(forecast grids: cell × magnitude bin × horizon, one per issue time), an index of gridded
products, and typed contracts, and must version large derived artefacts without committing them to
git. The brief fixes the stack.

## Decision

| Data | Library | Format | Location |
|---|---|---|---|
| Catalogues, homogenisation logs, faults | pandas / geopandas | GeoParquet | `data/interim/`, `data/catalogs/` |
| Forecast grids | xarray | zarr (v3) | `data/forecasts/<region>/<model>/<issue>.zarr` |
| Index of forecast products | pystac | STAC items/collections (JSON) | alongside the zarr stores |
| Domain models and contracts | pydantic v2 | Python models → JSON Schema | `src/rupture/domain/`, `contracts/` |
| Large-file versioning and lineage | DVC | `.dvc` pointers, `dvc.yaml` stages | `data/raw|interim|catalogs|forecasts`, `baselines/` |

- Writers live in `adapters/storage/{geoparquet,zarr,stac}.py`; the domain never sees a file
  format.
- Every GeoParquet and zarr store carries provenance and licence in its metadata (Parquet
  key-value metadata; zarr attributes; STAC properties).
- DVC stages in `dvc.yaml` (`build_catalog`, `fit_etas`, `evaluate_schedule`, per region) declare
  dependencies and outputs; `dvc repro` needs network and is never invoked by the offline gates.
- Default DVC remote is a local placeholder; production is S3 via `dvc remote modify`
  (ADR-0001; `docs/CREDENTIALS.md`).

## Consequences

- Columnar, compressed, language-neutral files that consumers can read without rupture.
- Forecast grids are chunked and appendable across issue times; STAC gives a discoverable index
  with space/time bounds and links to evaluation results.
- pydantic v2 gives validation at every boundary and free JSON Schema export (ADR-0013).
- DVC adds a tool developers must learn; the offline suite does not need it.

## Alternatives considered

- **CSV / GeoJSON for catalogues.** Rejected: no types, no compression, no geometry metadata
  standard.
- **NetCDF for grids.** Acceptable but zarr's cloud-native chunking suits S3-backed DVC remotes
  better; xarray reads both.
- **A database (PostGIS).** Rejected: a running service is not an offline-friendly dependency.
- **Git LFS.** See ADR-0001.
