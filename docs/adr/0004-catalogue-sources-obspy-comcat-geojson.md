# ADR-0004 — Catalogue sources: obspy FDSN for ComCat and ISC; ComCat GeoJSON to keep `type`; libcomcat optional

- **Status:** accepted
- **Date:** 2026-09-03

## Context

rupture needs USGS ComCat and the ISC Bulletin as event sources. Both expose the FDSN event web
service, which obspy's `Client` speaks. ComCat additionally classifies entries by `type`
(`earthquake`, `landslide`, `explosion`, ...); the FDSN QuakeML path does not reliably surface
this, but ComCat's GeoJSON output does. The brief requires that landslide-type entries such as
`us7000tbwb` (type `landslide`, M5.2, Nepal, 2026-08-26) be retained and tagged, not dropped,
because they matter for the F3 cascade layer and for the `SourceTypeAssessment` contract shared
with `serac`. The brief also names `libcomcat` for detail products; on PyPI it is
`usgs-libcomcat` and brings a heavy `esi_utils_*` dependency tree.

## Decision

- **ISC Bulletin**: obspy FDSN `Client("ISC")` (or the ISC FDSN URL) for event queries, text
  output parsed into `Event` records with agency, magnitude author and type.
- **USGS ComCat**: queries go to the ComCat FDSN event endpoint with `format=geojson`, paged by
  time window, so that `type`, `net`, `magType`, `updated` and the event `id` are available.
  `type` is mapped to `EventType {earthquake, landslide, explosion, other}` and **retained**;
  non-earthquake entries are excluded from fits and targets by filter, never deleted.
- **`usgs-libcomcat`** is an optional extra `rupture[comcat-products]`, used only from Prompt 2
  for ShakeMap, PAGER and ground-failure detail products. Core event ingestion does not depend on
  it.
- All adapters fetch or raise; a partial page or an HTTP error fails the build of that window.
  Requests carry `RUPTURE_CONTACT_EMAIL` in the `User-Agent` when set.

## Consequences

- The event-type information survives into the homogenised catalogue and `validate-catalog`
  checks it.
- Two code paths for ComCat (GeoJSON) and ISC (FDSN text) rather than one QuakeML path; the
  domain does not care.
- The default install stays lighter; F3 work adds the extra explicitly.

## Alternatives considered

- **QuakeML through obspy for both sources.** Rejected: loses or complicates the ComCat `type`
  field and paging behaviour that the retention requirement depends on.
- **`usgs-libcomcat` for all ComCat access.** Rejected: heavy dependencies for the core path;
  its search API wraps the same GeoJSON endpoint.
- **Drop non-earthquake entries at ingestion.** Rejected by the brief: they are catalogue
  content and F3 input.
