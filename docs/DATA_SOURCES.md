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
| **ISC Bulletin** | ISC FDSN event service, `https://www.isc.ac.uk/fdsnws/event/1/query`, text output, paged one calendar year per request (HTTP 413 bisects the window); reviewed bulletin lags real time by roughly two years, so recent windows fall back to ComCat/GCMT. The text format carries one (preferred) magnitude per event | FDSN text | ISC data policy: free for research with attribution to the ISC (see `https://www.isc.ac.uk`) | MB scale per region | monthly (reviewed bulletin) | raw pages cached under `data/raw/isc/` keyed by query URL; merged directly into `data/catalogs/<region>/` | `source=isc`, query URL, `retrieved_at`, `sha256`, `licence`, adapter version; per event: ISC `eventid` and magnitude author |
| **ISC-GEM** Global Instrumental Earthquake Catalogue | download page `https://www.isc.ac.uk/iscgem/download.php` (form-gated: `request_catalogue.php` is an HTTP POST form; the user downloads the CSV manually and sets `RUPTURE_ISC_GEM_CSV`). Version 12.1 dated 2025-11-27 as of 2026-09-03 | CSV | CC-BY-SA 3.0 (unported), (C) International Seismological Centre and GEM Foundation, as stated on the download page on 2026-09-03; cite Storchak et al. 2013/2015, Di Giacomo et al. 2015 | a few MB | with each ISC-GEM release (roughly yearly) | read from the path in `RUPTURE_ISC_GEM_CSV` at build time (not copied); clipped per region at merge time. **No fixture is committed**: the CSV was not obtainable without the form | `source=isc-gem`, download page URL and local path, `retrieved_at` (file mtime), `sha256` of the CSV, `licence`, adapter version |
| **GCMT** Global Centroid-Moment-Tensor catalogue | `https://www.globalcmt.org/`; NDK files from LDEO: `jan76_dec20.ndk` (23.0 MB, 1976–2020, 56 832 events), monthly final files `NEW_MONTHLY/<yyyy>/<mon><yy>.ndk` (60–85 kB each; available through apr26 on 2026-09-03) and the quick-CMT file `NEW_QUICK/qcmt.ndk` for months without a final file yet | NDK (fixed-format text, 5 lines per event) | free for research with citation of Ekström, Nettles & Dziewoński 2012 (see site) | ~23 MB + monthly files (kB) | monthly | `data/raw/gcmt/` (cache keyed by URL); events carry Mw from the scalar moment, centroid location/time, and the reference hypocentre in `provenance.notes` | `source=gcmt`, file URL, `retrieved_at`, `sha256` per file, `licence`, adapter version; per event: GCMT event name, quick/standard flag in `raw_type` |
| **GEM Global Active Faults Database** | `https://github.com/GEMScienceTools/gem-global-active-faults` (harmonised GeoJSON, ~10.6 MB) | GeoJSON | **CC-BY-SA-4.0** (attribution: Styron & Pagani 2020; derived GeoParquet inherits share-alike, see ADR-0007) | ~10.6 MB | with each database release | `data/interim/gem_active_faults.parquet` (GeoParquet, all fields kept, per-region clips at use time) | `source=gem-gaf`, file URL and commit, `retrieved_at`, `sha256`, `licence=CC-BY-SA-4.0`, adapter version |
| **OpenQuake source models** | `turkiye-eaf`: ESHM20 (Danciu et al. 2021/2024) from the EFEHR GitLab project `efehr/eshm20`, directory `oq_computational/oq_configuration_eshm20_v12e_region_main` (source-model logic tree `source_model_logic_tree_eshm20_model_v12e.xml`, GSIM logic tree `gmpe_complete_logic_tree_5br.xml`, 55 files, 40.2 MB at commit `fbd334de`), OpenQuake NRML 0.4. `california`: none openly licensed in NRML verified (USGS NSHM is public domain but in nshmp format). `nepal-himalaya`: none openly licensed found. See ADR-0008 | NRML XML + logic-tree XML | ESHM20: **CC-BY-4.0** per the repository `LICENSE` and `oq_computational/README.md` (verified 2026-09-03), with the citation Danciu et al. 2021, doi:10.12686/ESHM20-OQ-INPUT required | 40.2 MB for the whole mainland-model directory (all of it is fetched; no clip is needed) | with each model release | `data/raw/eshm20/` with `manifest.json` (paths, sizes, sha256, blob ids, commit, licence text) | `source=eshm20`, repository URL and commit, `retrieved_at`, `sha256` per file, `licence`, adapter version |
| **OpenQuake demos** | bundled with the engine source in the pinned image `openquake/engine:3.26.2` (`demos/hazard/AreaSourceClassicalPSHA` and siblings) | job.ini + NRML | as the OpenQuake engine (AGPL-3.0 for the engine; demo inputs distributed with it) | kB | with the image tag | nothing persistent; run as the `validate-hazard` integration test | image tag and digest recorded in the gate output |

Source precedence at merge time (location and time): ISC-GEM > ISC > ComCat > GCMT centroid
(GCMT supplies Mw and wins location only when it is the sole source); duplicates identified by a
time window of ±16 s and a distance of ≤ 100 km following Weatherill, Pagani & Garcia (2016),
with GCMT matched on its reference hypocentre; every merge decision is written to the per-event
homogenisation log. The full rules are ADR-0017 and `docs/CATALOG_BUILD.md`; magnitude
conversions and their citations are also summarised in `GLOSSARY.md` § Magnitude types.

## Fixtures

Small, **real** slices are committed under `data/fixtures/` for the offline suite (1.3 MB in
total; the largest file is 330 kB). Each is a byte-exact service response or a verbatim subset,
cut by the adapter, with the query recorded.

| Fixture | Content | Sources in the slice |
|---|---|---|
| `comcat/gorkha-2015-30d-m4.geojson`, `isc/gorkha-2015-7d-m4.txt`, `gcmt/apr15.ndk` + `may15.ndk` | 2015-04-25T00:00:00Z to +30 d (ISC: +7 d), M ≥ 4, bbox 80–89E / 26–31N; includes the M7.8 mainshock and the 2015-05-12 M7.3 aftershock, which appear in all three sources so the merge is exercised | ComCat GeoJSON page, ISC FDSN text page, whole GCMT monthly NDK files |
| `comcat/kahramanmaras-2023-30d-m4.geojson`, `isc/kahramanmaras-2023-7d-m4.txt`, `gcmt/feb23.ndk` + `mar23.ndk` | 2023-02-06T00:00:00Z to +30 d (ISC: +7 d), M ≥ 4, bbox 35–42E / 35.5–40N; the doublet and its aftershocks | ComCat, ISC, GCMT |
| `comcat/ridgecrest-2019-30d-m3.5.geojson`, `isc/ridgecrest-2019-7d-m3.5.txt`, `gcmt/jul19.ndk` + `aug19.ndk` | 2019-07-04T00:00:00Z to +30 d (ISC: +7 d), M ≥ 3.5, bbox −122–−114E / 32–37.5N | ComCat, ISC, GCMT |
| `comcat/nepal-2026-landslide-us7000tbwb.geojson` | ComCat GeoJSON, 2026-08-20 to 2026-09-01, M ≥ 4, bbox 80–89E / 26–31N, `eventtype` unrestricted; contains `us7000tbwb` (`type=landslide`, M5.2 `ms_vx`, 2026-08-26) and `us7000tc90` (landslide, M4.2) | ComCat |
| `gem_faults/gem_active_faults_harmonized.nepal-bbox.geojson` | the 59 GAF features intersecting 80–89E / 26–31N, copied verbatim from the 13 696-feature file (parent sha256 recorded) | GEM GAF (CC-BY-SA-4.0) |
| `eshm20/source_model_logic_tree_eshm20_model_v12e.head2048.xml` | byte-exact first 2048 bytes of the ESHM20 source-model logic tree at commit `fbd334de` | ESHM20 (CC-BY-4.0) |

`rupture catalog refresh-fixtures` re-cuts the ComCat, ISC and GCMT files with the queries in
`src/rupture/adapters/catalogs/refresh.py` and rewrites each `provenance.json`. There is no
ISC-GEM fixture (form-gated download; ADR-0005).

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
