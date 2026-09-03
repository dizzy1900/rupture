# Data sources

rupture does not predict earthquakes. Everything it does starts from public catalogues, fault
databases and source models listed here. Every record ingested from any of them carries a
provenance record (`source`, `source_url`, `retrieved_at`, `sha256`, `licence`,
`adapter_version`); unknown values are `null`. Adapters fetch or fail loudly; none synthesises
rows.

Licence statements below are as understood on 2026-09-03; the authoritative text is at each
provider's URL, and the `licence` field on each record repeats what the adapter recorded at
retrieval time. If a statement here is found to be wrong, correct the adapter's recorded licence
and this table together.

## Sources

| Source | Access / URL | Format | Licence | Size (approx.) | Refresh | What rupture stores | Provenance captured |
|---|---|---|---|---|---|---|---|
| **USGS ComCat** (ANSS Comprehensive Earthquake Catalog) | FDSN event web service, `https://earthquake.usgs.gov/fdsnws/event/1/query` with `format=geojson` (paged by time); GeoJSON is used because it carries the `type` field (`earthquake`, `landslide`, `explosion`, ...) and per-event `net`, `magType`, `updated` | GeoJSON | US Government work, public domain (USGS) | tens of MB per region for the full period; a few hundred kB per month | daily | `data/raw/comcat/<region>/<from>_<to>.geojson`; parsed to `data/interim/comcat/<region>.parquet` with `event_type` mapped and retained (landslide-type entries **kept and tagged**, never dropped) | `source=usgs-comcat`, query URL, `retrieved_at`, `sha256` of the GeoJSON page, `licence`, adapter version; per event: `updated` timestamp and `net` |
| **ComCat detail products** (ShakeMap, PAGER, ground failure) | `usgs-libcomcat` (PyPI), optional extra `rupture[comcat-products]`; used from Prompt 2 for F3 | product JSON / GeoTIFF | public domain (USGS) | per event, MB scale | on demand | not stored in Prompt 1 | as above, plus product `code`/version |
| **ISC Bulletin** | ISC FDSN event service, `https://www.isc.ac.uk/fdsnws/event/1/query`, text output; reviewed bulletin lags real time by roughly two years, so recent windows fall back to ComCat/GCMT | FDSN text (or ISF) | ISC data policy: free for research with attribution to the ISC (see `https://www.isc.ac.uk`) | MB scale per region | monthly (reviewed bulletin) | `data/raw/isc/<region>/...txt`; parsed to `data/interim/isc/<region>.parquet` | `source=isc-bulletin`, query URL, `retrieved_at`, `sha256`, `licence`, adapter version; per event: ISC `eventid`, contributing agency and magnitude author |
| **ISC-GEM** Global Instrumental Earthquake Catalogue | download page `https://www.isc.ac.uk/iscgem/download.php` (form-gated: the user downloads the CSV manually and sets `RUPTURE_ISC_GEM_CSV`) | CSV | per the ISC-GEM terms of use stated on the download page (attribution to Storchak et al. 2013/2015; Di Giacomo et al. 2015) | a few MB | with each ISC-GEM release (roughly yearly) | the CSV as downloaded under `data/raw/isc_gem/`; parsed to `data/interim/isc_gem.parquet` (global; clipped per region at merge time) | `source=isc-gem`, download page URL, `retrieved_at` (file mtime and user-supplied date), `sha256` of the CSV, ISC-GEM version string from the header, `licence`, adapter version |
| **GCMT** Global Centroid-Moment-Tensor catalogue | `https://www.globalcmt.org/`; NDK files from LDEO: `jan76_dec20.ndk` (about 23 MB, 1976–2020) plus monthly "quick" NDK files for later months | NDK (fixed-format text, 5 lines per event) | free for research with citation of Ekström, Nettles & Dziewoński 2012 (see site) | ~23 MB + monthly files (kB) | monthly | `data/raw/gcmt/*.ndk`; parsed to `data/interim/gcmt.parquet` with Mw, centroid location/time, hypocentre, moment tensor and nodal planes | `source=gcmt`, file URL, `retrieved_at`, `sha256` per file, `licence`, adapter version; per event: GCMT event name |
| **GEM Global Active Faults Database** | `https://github.com/GEMScienceTools/gem-global-active-faults` (harmonised GeoJSON, ~10.6 MB) | GeoJSON | **CC-BY-SA-4.0** (attribution: Styron & Pagani 2020; derived GeoParquet inherits share-alike, see ADR-0007) | ~10.6 MB | with each database release | `data/interim/gem_active_faults.parquet` (GeoParquet, all fields kept, per-region clips at use time) | `source=gem-gaf`, file URL and commit, `retrieved_at`, `sha256`, `licence=CC-BY-SA-4.0`, adapter version |
| **OpenQuake source models** | `turkiye-eaf`: ESHM20 (Danciu et al. 2021/2024) from the EFEHR GitLab (`https://gitlab.seismo.ethz.ch/efehr`), OpenQuake NRML format. `california`: none openly licensed in NRML verified (USGS NSHM is public domain but in nshmp format). `nepal-himalaya`: none openly licensed found. See ADR-0008 | NRML XML + logic-tree XML | ESHM20: as stated in the EFEHR repository (open licence with attribution; confirm from the repository's licence file at retrieval and record it) | tens to hundreds of MB for the full ESHM20; rupture keeps the files needed for the EAF clip | with each model release | `data/raw/oq_sources/eshm20/...`; clip metadata for `turkiye-eaf` | `source=eshm20`, repository URL and commit, `retrieved_at`, `sha256` per file, `licence` as found, adapter version |
| **OpenQuake demos** | bundled with the engine source in the pinned image `openquake/engine:3.26.2` (`demos/hazard/AreaSourceClassicalPSHA` and siblings) | job.ini + NRML | as the OpenQuake engine (AGPL-3.0 for the engine; demo inputs distributed with it) | kB | with the image tag | nothing persistent; run as the `validate-hazard` integration test | image tag and digest recorded in the gate output |

Source precedence at merge time (location and time): ISC-GEM > GCMT centroid (Mw only) > ISC >
ComCat; duplicates identified by a time window of ±16 s and a distance of ≤ 100 km following
Weatherill, Pagani & Garcia (2016); every merge decision is written to the per-event
homogenisation log. Magnitude conversions and their citations are in `GLOSSARY.md`
§ Magnitude types.

## Fixtures

Four small, **real** slices are committed under `data/fixtures/` for the offline suite. Each is
cut from an actual pull by the corresponding adapter and is under about 1 MB.

| Fixture | Content | Sources in the slice |
|---|---|---|
| `gorkha-2015` | 2015-04-25T00:00:00Z to +30 d, M ≥ 4, `nepal-himalaya` polygon; includes the M7.8 mainshock and the 2015-05-12 M7.3 aftershock | ComCat, ISC, GCMT rows, deliberately including cross-source duplicates so the merge is exercised |
| `kahramanmaras-2023` | 2023-02-06T00:00:00Z to +30 d, M ≥ 4, `turkiye-eaf` polygon; the doublet and its aftershocks | ComCat, ISC (where available), GCMT |
| `ridgecrest-2019` | 2019-07-04T00:00:00Z to +30 d, M ≥ 3.5, `california` polygon | ComCat, GCMT |
| `comcat-landslide-us7000tbwb` | a ComCat GeoJSON slice containing `us7000tbwb` (`type=landslide`, M5.2, Nepal, 2026-08-26) and its neighbours in time | ComCat |

Rules:

1. Every fixture directory contains a `provenance.json` with the same six provenance fields as a
   catalogue record, plus the exact query used to cut it and the `sha256` of the raw payload it
   was cut from.
2. Fixtures are **never edited by hand**. To change one, re-run the adapter with the recorded
   query, re-record provenance, and commit both. A fixture whose contents cannot be reproduced
   from its provenance is removed.
3. Fixtures are what they say they are. ETAS fits run on them in unit tests are smoke fits with
   fixed seeds and reduced iterations; they are never reported as baselines.
4. `make validate-catalog` checks that `us7000tbwb` is present in the built offline catalogue
   with `event_type=landslide` and that no duplicates survive the merge.

## The > 5 GB and paid-API rule

Non-negotiable 7: **ask before downloads > 5 GB or paid API calls.**

- Nothing in this table is paid. All sources are free public services or downloads; no API key
  purchases anything.
- Nothing in this table approaches 5 GB. The largest single pulls are the GCMT NDK (~23 MB), the
  GEM faults GeoJSON (~10.6 MB), the ESHM20 files needed for the EAF clip, and the OpenQuake
  engine image (a Docker pull of order 1 GB, well below the threshold). Full-period ComCat pulls
  for a region are tens of MB.
- If a future source (for example a global ShakeMap archive, a DEM for F3, or a full GEM
  hazard mosaic) would exceed 5 GB, the adapter must stop and the request must be raised with
  the user before any bytes are fetched. Sizes are recorded in the provenance so the ledger can
  show how much was pulled.
