# ADR-0067 — NGL GNSS as the first continuous ObservationSource

- **Status:** accepted
- **Date:** 2026-09-13 (UTC)
- **Implements (partly):** [ADR-0054](0054-latency-aware-observation-sources.md) (`available_as_of`
  on a loaded series), [ADR-0064](0064-data-vintage-and-the-second-clock.md) (the port that
  previously had no adapter)
- **Related:** [ADR-0004](0004-catalogue-sources-obspy-comcat-geojson.md) (fetch via the shared
  HTTP helper), [ADR-0062](0062-third-party-licence-quarantine.md) (licence as published, not
  invented)

## Context

Every catalogue adapter in this tree fetches events. A catalogue is a lossy summary of continuous
observations, and the prediction programme is aimed at those observations — GNSS positions first,
because they are commercially open, free, and already the product behind the GNSS-precursor
literature Rupture will eventually adjudicate.

Nevada Geodetic Laboratory (NGL) serves daily tenv3 series over public HTTP with no API key.
The data paper NGL asks users to cite is Blewitt, Hammond & Kreemer (2018), *Eos*, 99,
https://doi.org/10.1029/2018EO104623 (homepage text retrieved 2026-09-13). No SPDX identifier is
published. The IGS14 daily files are the *final* product: IGS final orbits lag the observation
day by about two weeks. Rapid products are documented at about 24 hours. Reading the final
series at a one-hour lead is the textbook latency leak ADR-0054 exists to catch.

The port `ObservationSource.available_as_of` existed and nothing implemented it. Catalogue
adapters stamp ComCat's `updated` and stop there.

## Decision

1. **NGL is the first continuous observation adapter**, implemented against the tenv3 daily
   series. Station holdings are at `NGLStationPages/DataHoldings.txt`. The documented series URL
   `http://geodesy.unr.edu/gps_timeseries/tenv3/IGS14/<SITE>.tenv3` is tried first; on 2026-09-13
   that path 404'd and the current layout
   `https://geodesy.unr.edu/gps_timeseries/IGS14/tenv3/IGS14/<SITE>.tenv3` served the file. The
   adapter tries both and fails if neither returns bytes. It never synthesises positions.

2. **`available_time` is required.** tenv3 carries no publish stamp, so FINAL positions receive
   `available_time = valid_time + FINAL_ORBIT_LAG` (14 days) and RAPID positions
   `valid_time + RAPID_ORBIT_LAG` (1 day). Those constants are named fields with comments, not
   literals in the arithmetic. If a payload later carries a publish stamp, that stamp wins.

3. **As-of is half-open:** a position is readable at `t` iff `available_time < t`. Equality is
   excluded. This is the ADR-0054 convention, and it is asserted on the committed P595 fixture.

4. **What this does not reconstruct.** NGL serves the *current* series. Applying a lag withholds
   values that would not yet have been published; it cannot recover a position that was later
   revised, and it is not an archived vintage of the series itself. Results that rest on this
   reconstructed availability must say so. A vintaged store of snapshots remains the next step
   named in ADR-0064.

5. **This is not Bletery & Nocquet adjudication.** It is the data port that adjudication needs.
   Nothing here inverts strain, scores a precursor, or claims that GNSS predicts earthquakes.

6. **USGS real-time GeoJSON and IRIS FDSN event query** ship in the same adapter family as
   catalogue-shaped `ObservationSource`s so the as-of clock is one code path. The USGS live
   `all_day` feed is a moving window and is not committed; the fixture is a cut of the already
   committed ComCat Ridgecrest GeoJSON. IRIS `fdsnws/event/1/query` returned HTTP 410 Gone on
   2026-09-13; the adapter keeps the documented URL and fails loudly rather than inventing a
   successor or inventing events.

## Consequences

- GNSS can enter a replay through `available_as_of`. Final-orbit positions are invisible until
  two weeks after `valid_time`; that is the whole point.
- Retrospective NGL reads are reconstructed availability, not observed vintages. Prospective
  snapshots, once a store exists, are the honest form.
- The licence field is `no SPDX` plus the citation NGL actually requested. A later SPDX, if NGL
  publishes one, updates the adapter and `docs/DATA_SOURCES.md` together.

## Alternatives considered

- **EarthScope / CWU L2 as the first GNSS source.** Not rejected; deferred. NGL is the product
  the GNSS-precursor literature actually used, and it needs no account.
- **Commit the full P595 series.** Rejected: multi-megabyte, and the as-of invariant is
  exercised on the first 21 data lines. Parent sha256 is recorded so the cut is auditable.
- **Synthesise rapid positions from the final series by shifting timestamps.** Forbidden
  (principle 5). Rapid is a different product; fetch it or do not claim it.
- **Treat NGL as immediately available because the file is on disk today.** Rejected: that is
  the latency leak.
