# ADR-0007 — GEM Global Active Faults as the fault database (CC-BY-SA-4.0)

- **Status:** accepted
- **Date:** 2026-09-03

## Context

rupture needs a fault database for region definition, for spatial context in the ETAS and hazard
lanes and, later, as a possible input to building source models where none is openly available.
The GEM Global Active Faults Database (GAF; Styron & Pagani 2020) is global, harmonised, in
GeoJSON (about 10.6 MB) and licensed **CC-BY-SA-4.0**.

## Decision

- `adapters/sources/gem_faults.py` fetches the harmonised GAF GeoJSON from the GEM repository,
  records provenance (`source=gem-gaf`, file URL and commit, `retrieved_at`, `sha256`,
  `licence=CC-BY-SA-4.0`, adapter version) and writes `data/interim/gem_active_faults.parquet`
  (GeoParquet, all attributes retained).
- **Attribution**: every artefact derived from GAF carries the attribution string for Styron &
  Pagani (2020) and the GEM Foundation in its metadata (Parquet key-value metadata, STAC item
  properties where relevant) and `RELEASE_STATUS.md` names the database.
- **Share-alike**: a GeoParquet that is a transformation of GAF is a derived work and is
  distributed under CC-BY-SA-4.0. rupture's code is Apache-2.0; this ADR records that the
  *data* artefact derived from GAF is not, and the `licence` field says so. Region clips and
  fault-distance columns computed from GAF inherit the same licence.
- rupture does not mix GAF geometry into any artefact it intends to release under a more
  permissive licence.

## Consequences

- One global, well-documented fault source with a clear licence trail.
- Downstream users of the fault GeoParquet must honour CC-BY-SA-4.0; this is stated in
  `docs/DATA_SOURCES.md` and in the file's metadata.
- If a region needs a fault database under a different licence, that is a new adapter and ADR.

## Alternatives considered

- **National fault databases (e.g. USGS Quaternary faults for California).** Not rejected for
  the future; GAF is harmonised across all three test regions and is enough for Prompt 1.
- **Digitising faults from literature.** Rejected: fabricating geometry is against the
  non-negotiables; GAF already did this with provenance.
