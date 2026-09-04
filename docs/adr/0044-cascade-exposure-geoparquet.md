# ADR-0038 — CascadeExposure as GeoParquet: geometry, and the caveat in the file's metadata

- **Status:** accepted
- **Date:** 2026-09-03
- **Relates to:** ADR-0012 (catalogue GeoParquet), ADR-0013 (contract versioning), ADR-0027 (serac
  slope units)

## Context

The brief specifies the co-seismic exposure product as "a `CascadeExposure` GeoParquet with
provenance". What existed was a pydantic record emitted as JSON. Two things were missing.

First, **geometry**. `ExposedSlopeUnit` carried no footprint at all: the adapter read serac's
polygon, took its centroid to sample PGA, and dropped the polygon. A GeoParquet built from that
record would have had nothing to overlay, which defeats the purpose of the format — a GIS or serac
consumer wants the unit outlines, not a list of ids.

Second, **where the caveat lives**. `CascadeExposure.label` carries the susceptibility caveat in
the payload precisely so a downstream reader cannot lose it. A columnar file whose rows are units
has no obvious home for a record-level statement, and a caveat that survives JSON but not Parquet
is a caveat that goes missing exactly when the data is handed to someone else.

## Decision

**1. The unit carries its own footprint.** Three additive fields on `ExposedSlopeUnit` (v0 is
additive-only under ADR-0013, so no version bump):

- `polygon` — the exterior ring, `(lon, lat)` in EPSG:4326, closed. Empty when the slope-unit
  source carries no geometry, which is a statement about the source, not a licence to invent one.
- `representative_longitude` / `representative_latitude` — the point at which `pga_g` was actually
  sampled, so the sampling is auditable rather than implied.

A fourth additive field, `assets_below`, carries the non-settlement receptors the slope-unit source
maps in the corridor. It exists because serac maps **no settlement** in `chamoli-rishiganga`: its
receptors are the Rishi Ganga and Tapovan Vishnugad hydropower projects. Reporting them as
`settlements_below` would be wrong and dropping them would lose the only receptors the AOI has.
`CascadeExposure` gains `shaking_source`, the id of the ground-motion field the PGA came from, so a
reader can tell a ShakeMap-driven record from a GSIM-driven one without parsing prose.

**2. One file, one row per unit.** `rupture.adapters.cascade.geoparquet`, deliberately mirroring
`rupture.adapters.storage.geoparquet` (catalogues) rather than extending it: the cascade adapters
own their own output and do not reach into the storage family. Scalar unit fields are columns of
the same name; `settlements_below`, `assets_below` and `source_refs` are `*_json` strings, as the
catalogue writer does with its tuples.

**3. Geometry falls back, then goes null — never invented.** Polygon where there is one, otherwise
the representative point, otherwise a null geometry. A unit rupture knows nothing about is written
as nothing.

**4. The record-level fields, including the caveat, are Parquet key-value metadata** under the
`rupture:` prefix: scenario, AOI, kind, threshold, slope-unit source, shaking source, model
provenance tier, confidence tier, `computed_at`, `notes`, the unit counts, the `label`, and
`rupture:statement`. A reader that opens only the schema still sees what the file is and is not.

**5. The round trip is exact and the gate proves it every run.**
`read_cascade_exposure(write_cascade_exposure(x)) == x`, asserted in
`tests/unit/cascade/test_geoparquet.py` and again inside `validate-cascade` for both the Gorkha and
the Chamoli records. That is what makes the format a contract rather than a report.

## Consequences

- `rupture cascade exposure --out-parquet <file>` is the published output; `--out` still writes the
  JSON record, and both validate against `contracts/cascade-exposure.v0.json`.
- `contracts/cascade-exposure.v0.json` is regenerated: four optional fields added, nothing removed
  or retyped, so an existing consumer keeps working.
- The exterior ring is normalised closed on the way out of the serac adapter, so the round trip
  through shapely is exact.
- A `MultiPolygon` slope unit would contribute only its first polygon's exterior ring. serac's
  committed AOI geometries are single polygons, so this is not exercised today; it is recorded here
  rather than discovered later.

## Alternatives rejected

- **Extend `adapters/storage/geoparquet.py`.** It is the catalogue writer, owned by another family;
  the cascade output belongs with the cascade adapters.
- **A GeoJSON-string geometry column.** Portable, but not a GeoParquet: no CRS, no spatial type, and
  no GIS reads it as geometry.
- **Storing the caveat only as a repeated column value.** Wasteful per row, and invisible to a
  reader who inspects the schema. The metadata is the right home for a record-level statement.
