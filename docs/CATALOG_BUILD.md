# Catalogue build

This document describes how `rupture catalog build` turns
public bulletins into one homogenised, provenance-complete catalogue per test region, what the
rules are (settled in ADR-0017), how the offline and online runs are invoked, what the real runs
produced, and what the known limitations are.

## 1. Sources and adapters

| Source | Adapter (`src/rupture/adapters/catalogs/`) | Access | What it contributes |
|---|---|---|---|
| USGS ComCat | `comcat.py` — `parse_comcat_geojson` + `ComCatSource` | FDSN event service, `format=geojson`, bbox/time/min-magnitude, `count` then bisect windows above 20 000 events | hypocentres, network magnitudes (`mww`, `mwr`, `mb`, `ml`, ...), **event `type`** (landslide, explosion, ...) |
| ISC Bulletin (reviewed) | `isc.py` — `parse_isc_text` + `IscSource` | FDSN event service, `format=text`, one calendar year per request, HTTP 413 bisects | reviewed hypocentres and ISC's preferred magnitude (`mb`, `MS`, `MW` by GCMT, ...) |
| Global CMT | `gcmt.py` — `parse_ndk` + `GcmtSource` | `jan76_dec20.ndk`, then `NEW_MONTHLY/<yyyy>/<mon><yy>.ndk`, then `NEW_QUICK/qcmt.ndk` for months without a final file | Mw from the scalar moment, centroid location/time, reference hypocentre |
| ISC-GEM | `isc_gem.py` — `parse_isc_gem_csv` + `IscGemSource` | local CSV named by `RUPTURE_ISC_GEM_CSV` (form-gated download, ADR-0005) | relocated hypocentres and Mw for large events since 1904 |

Every adapter is a pure parser (raw bytes → `Event`s) plus a thin fetch layer that either
returns real bytes with `Provenance` (`source`, `source_url`, `retrieved_at`, `sha256` of the
payload, `licence`, `adapter_version`) or raises. Nothing is synthesised. Online fetches cache raw
pages under `data/raw/<source>/` keyed by the exact URL so an interrupted ISC pull resumes; a
cached page keeps the `retrieved_at` of the original fetch.

Offline, each adapter reads the committed fixtures under `data/fixtures/<source>/` and refuses a
file whose sha256 differs from `provenance.json` (fixtures are never edited by hand;
`rupture catalog refresh-fixtures` re-cuts them).

## 2. Rules (ADR-0017)

### Association

Same event when `|Δt| ≤ 16 s` and distance `≤ 100 km` (Weatherill, Pagani & Garcia 2016).
Parameters: `--time-window-s`, `--distance-km`. In time order, a record joins — among the clusters
whose first key lies within one time window of it — the cluster with the nearest compatible
member, so a cluster never chains beyond one window from its first record.
**Lane rule:** records from the same lane never merge (lane = source id; for ComCat
`usgs-comcat/<net>` from the id prefix), so one bulletin's own aftershock pairs are never
collapsed while ComCat's separate copies of ISC-GEM or other-network origins can be associated.
**GCMT** is matched on its reference hypocentre (NDK line 1), because the centroid time lags the
origin by the half-duration (32 s for Gorkha 2015).

### Preferred solution

Location, time, depth, as-reported magnitude and provenance come from
`ISC-GEM > ISC > ComCat > GCMT`. Event ids are `rup-<sha1('<source>:<id>')[:12]>` of that
record; `contributing_ids` lists every merged record as `<source>:<id>`.

### Homogenised Mw

| Priority | Rule | `mw_conversion` |
|---|---|---|
| 1 | GCMT Mw = (2/3)(log10 M0 − 16.1), M0 in dyne·cm (Hanks & Kanamori 1979) | `identity:mwc` |
| 2 | ISC-GEM Mw | `identity:mw` |
| 3 | reported `mww`/`mwc`/`mwb`/`mwr`/`mw` from ISC, then ComCat | `identity:<type>` |
| 4 | Scordilis (2006): Mw = 0.85 mb + 1.03 (3.5 ≤ mb ≤ 6.2); Mw = 0.67 Ms + 2.07 (3.0 ≤ Ms ≤ 6.1); Mw = 0.99 Ms + 0.08 (6.2 ≤ Ms ≤ 8.2); Ms before mb within a source | `scordilis2006:mb`, `scordilis2006:ms` |
| 5 | **`network-preferred-as-mw` regions only** (`Region.magnitude_policy`, ADR-0019; California): a preferred `ml`/`md`/`mlv` magnitude with no moment magnitude from any source is assumed Mw-equivalent | `assumed-equivalent:<type>` + `magnitude_converted` "assumed Mw-equivalent (ADR-0019)" |
| — | otherwise (`strict` policy): ML, Md, `mb1`, `ms_vx`, unknown scales, or mb/Ms outside the ranges | `None` + `magnitude_unconvertible` in the log |

Scordilis, E. M. (2006), J. Seismol. 10, 225–236, doi:10.1007/s10950-006-9012-4. See the
`verify` note in ADR-0017: the slopes and ranges were confirmed against third-party citations on
2026-09-03; the intercepts match the brief but the paper itself was not opened.

### Event type

Any non-earthquake tag from any record wins; ComCat `type` → `EventType` mapping is in ADR-0017
and `comcat.EVENT_TYPE_MAP`. Landslide-type entries (`us7000tbwb`, `us7000tc90` in the 2026 Nepal
fixture) are retained, tagged `landslide`, have `mw = None` (their `ms_vx` magnitude has no
accepted conversion) and are excluded from fits and targets by filter, never deleted.

### Filters

After association: epicentre must be covered by the region polygon (`outside_region_dropped`),
depth ≤ `depth_max_km`, and ≥ `depth_min_km` only when that is set above 0 (networks report
small negative depths for very shallow events; `depth_filtered`; unknown depth kept). Half-open
`[from, to)` on `origin_time`.

### Completeness (`pipelines/completeness.py`)

On the homogenised Mw of earthquakes, 0.1 bins:

- **maximum curvature** (Wiemer & Wyss 2000) + 0.2 (Woessner & Wiemer 2005); ties resolved to the
  lowest bin before the correction;
- **b-value stability** (Cao & Gao 2002; Woessner & Wiemer 2005): first cut-off whose Aki b is
  within σ_b (Shi & Bolt 1982) of the mean b over the half-magnitude range Mc … Mc+0.5 (six
  cut-offs, Woessner & Wiemer 2005 eq. for b_ave); ≥ 30 events per cut-off;
  if no cut-off is stable the method is absent and the notes say so;
- **`mc_ks`** cross-check with `etas.mc_b_est.estimate_mc` (Mizrahi et al. 2021), p ≥ 0.1,
  2 000 simulated samples; reported when it passes, skipped with `--no-etas-cross-check`.

b is Aki (1965) MLE with the Utsu half-bin correction: `b = log10(e) / (mean(m) − (Mc − 0.05))`.
All estimates land in `Catalog.completeness`. `--update-region-mc` copies them all to
`Region.mc_estimates` (each noting the Mw coverage at the target threshold and the maximum-curvature
b) and publishes `Region.mc` (the maximum-curvature estimate, which the ETAS fit reads) **only** when
that b ≥ 0.7 and ≥ 80 % of earthquakes reported at or above the target threshold have a homogenised
Mw; otherwise `mc` stays null and the command prints the reason (`--force-mc` overrides and marks the
estimate). The build also records per-source skipped-row counts, the etas cross-check status and the
magnitude policy in `Catalog.notes`.

## 3. Outputs

`data/catalogs/<region>/` (DVC-tracked, not committed):

| File | Content |
|---|---|
| `events.parquet` | GeoParquet, one row per event; scalar `Event` fields as columns, preferred magnitude flattened to `magnitude_*`, `other_magnitudes_json`, `contributing_ids_json`, `provenance_json`; geometry = epicentre (EPSG:4326); `rupture:*` key-value metadata (catalogue id, region, sources, licences, built_at) |
| `catalog.meta.json` | the `Catalog` minus events and log (`model_dump`), plus `n_events`, `n_log_entries`, `event_hash` |
| `homogenisation_log.jsonl` | one `HomogenisationLogEntry` per line |

`adapters/storage/geoparquet.read_catalog` reverses the mapping exactly (round-trip test and gate).

## 4. Commands

Offline (fixtures; no network; what `make validate-catalog` and the unit tests run):

```sh
uv run rupture region list
uv run rupture region show nepal-himalaya
uv run rupture catalog build --region nepal-himalaya --from 2015-04-25T00:00:00Z \
    --to 2015-05-25T00:00:00Z --offline-fixtures --out /tmp/nepal-gorkha
uv run rupture catalog inspect /tmp/nepal-gorkha
uv run rupture validate catalog
```

Online (the real builds; ComCat + ISC + GCMT, source magnitude floor = region target − 1.5):

```sh
for r in nepal-himalaya turkiye-eaf california; do
  uv run rupture catalog build --region $r --from 1976-01-01T00:00:00Z --to 2026-08-01T00:00:00Z \
      --sources comcat,isc,gcmt --update-region-mc
  uv run dvc commit -f build_catalog@$r   # dvc add refuses stage outputs; this updates dvc.lock
done
```

Add `--sources comcat,isc,gcmt,isc-gem` with `RUPTURE_ISC_GEM_CSV` set to include ISC-GEM; without
the variable the build proceeds and records `source isc-gem not included` in the catalogue notes.
`--min-magnitude` overrides the floor; `--no-etas-cross-check` skips the KS estimate (used for
California, where the simulation on ~10^5 magnitudes is slow).

`dvc repro build_catalog@<region>` runs the same build **without** `--update-region-mc`, so it never
touches `data/regions/<id>/region.json`; the region record is refreshed out of band with the command
above and committed to git.

Fixtures: `uv run rupture catalog refresh-fixtures` (network) re-cuts every ComCat, ISC and GCMT
fixture and rewrites `provenance.json`. Regions: `uv run rupture region init` writes the three
default region files (refuses to overwrite a file holding a fitted `mc` unless `--force`).

Faults and source models (`src/rupture/adapters/sources/`):

```python
from rupture.adapters.sources import gem_faults, openquake_sources
gem_faults.fetch_gem_faults()          # -> data/interim/gem_active_faults.parquet + .provenance.json
openquake_sources.fetch_eshm20()       # -> data/raw/eshm20/** + manifest.json (55 files, 40.2 MB)
openquake_sources.available_models("california")   # ([], gap reason referencing ADR-0008)
```

## 5. Real runs (2026-09-03)

Builds from 1976-01-01T00:00:00Z to 2026-08-01T00:00:00Z with ComCat + ISC + GCMT, association
windows 16 s / 100 km, source magnitude floor = target − 1.5. ISC-GEM was **not** included in any
build (no CSV configured). Results are what the commands printed; nothing here is adjusted.

The numbers below are the **second** set of builds, run after three changes that all affect the
result: the ADR-0019 thresholds (Nepal 4.7, Türkiye 4.6, so their fetch floors rose to 3.2 and 3.1
and their event counts fell), the ADR-0019 California magnitude policy
(`network-preferred-as-mw`), and the depth-filter fix that stops dropping events reported with a
small negative depth. The first set (before those changes) is kept at the end of this section
because the ETAS baseline was first fitted on it.

| Region | Events (earthquake / explosion / other) | Preferred source (ISC / ComCat / GCMT) | Events with Mw | Mw coverage at the target threshold | Mc maximum curvature (+0.2) | Mc b-value stability | Mc KS (`etas`) | Runtime |
|---|---|---|---|---|---|---|---|---|
| `nepal-himalaya` (target 4.7, floor 3.2) | 2 728 (2 727 / 1 / 0) | 2 678 / 50 / 0 | 2 132 | 187 / 195 (96 %) | **4.40** (b = 1.14 ± 0.03, n = 1 052) | 4.70 (b = 1.22 ± 0.06, n = 513) | 4.30 (n = 1 355) | 104 s |
| `turkiye-eaf` (target 4.6, floor 3.1) | 7 038 (7 036 / 2 / 0) | 6 943 / 93 / 2 | 2 363 | 282 / 288 (98 %) | **4.30** (b = 1.03 ± 0.03, n = 917) | 4.60 (b = 1.16 ± 0.05, n = 495) | 4.70 (n = 388) | 160 s |
| `california` (target 3.95, floor 2.45, policy `network-preferred-as-mw`) | 110 766 (107 601 / 3 137 / 28) | 42 860 / 67 906 / 0 | 106 381 | 3 080 / 3 123 (99 %) | **2.70** (b = 1.01 ± 0.004, n = 65 544) | 2.60 (b = 1.00 ± 0.004, n = 82 710) | not run (`--no-etas-cross-check`) | 66 s |

The bold maximum-curvature values are the ones `--update-region-mc` published to
`data/regions/<id>/region.json` (`mc`); every estimate, with its Mw-coverage note, is in
`mc_estimates`. All three passed the publication rules (maximum-curvature b ≥ 0.7 and Mw coverage
at the target ≥ 80 %).

**California under the ADR-0019 policy.** 102 940 events take their Mw from the network-preferred
scale (`assumed-equivalent:ml` 54 702, `assumed-equivalent:md` 48 238); 2 628 keep a moment
magnitude (`identity:mw` 1 553, `identity:mwr` 791, `identity:mwc` 276, `identity:mww` 8), 813 come
from Scordilis (684 `mb`, 129 `Ms`), and 4 385 still have no Mw (ComCat `mh` 3 390, ISC `M` 856,
ComCat `ma` 71, `mb` outside the Scordilis range). Coverage at M ≥ 3.95 rose from 49 % to 99 %, and
the Mw frequency–magnitude distribution now behaves like a Gutenberg–Richter population: b = 1.01
at the maximum-curvature Mc and 1.00 at the stability Mc, against 0.59 and 0.95 before. **Neither
California Mc estimator exceeds 3.95** (2.70 and 2.60), so ADR-0019 decision 3 does not trigger and
the California target threshold stays at the RELM 3.95; the decision is the architect's, and this
document does not change it. The depth fix also matters here: `depth_filtered` fell from 7 015 to
879 events, because ComCat reports small negative depths for very shallow Californian events.

Homogenised-Mw mix elsewhere: Nepal 1 678 `scordilis2006:mb`, 279 `scordilis2006:ms`, 105
`identity:mw`, 70 `identity:mwc`, 596 without Mw (ISC `mb` below 3.5, `ML`, `mb1`, `MD`); Türkiye
1 370 `identity:mw`, 674 `scordilis2006:mb`, 122 `identity:mwc`, 118 `identity:mwr`, 78
`scordilis2006:ms`, 4 675 without Mw (ISC `MD`/`Md` 2 786, `ML`/`Ml` 1 715). Largest events:
Gorkha 2015-04-25 Mw 7.88, Kahramanmaraş 2023-02-06 Mw 7.78 and 7.70, Imperial Valley 1980-11-08
Mw 7.30 and Landers 1992-06-28 Mw 7.28 — each associated from ISC + ComCat + GCMT. Records
associated from two sources: Nepal 903, Türkiye 1 114, California 38 245; from three: 70, 120, 336
(and one California event from four).

ISC coverage: the ISC FDSN service returned events through 2026-07 for all three regions, but rows
after the reviewed period carry other agencies' prime hypocentres (`Author` = IDC, GFZ, NEIC), not
ISC's reviewed solutions; the adapter records the row's `MagAuthor` and does not distinguish
reviewed from preliminary.

Outputs are DVC-tracked through the `build_catalog@<region>` stages in `dvc.yaml`
(`uv run dvc commit -f build_catalog@<region>`, recorded in `dvc.lock`; `dvc add` refuses paths
that are stage outputs). Sizes: Nepal 0.19 MB parquet + 2.6 MB log; Türkiye 0.41 MB + 4.5 MB;
California 6.0 MB + 78 MB (one `ingested` entry per source record).
`data/interim/gem_active_faults.parquet` (13 696 faults, 2.4 MB) now has a committed `.dvc`
pointer; `data/raw/eshm20/` (55 files, 40.2 MB) is DVC-free but its `manifest.json` (paths, sizes,
sha256, commit, licence text) is committed, so the fetch is reproducible and verifiable
(`openquake_sources.verify_manifest()`).

### Superseded first builds (2026-09-03, before ADR-0019 and the depth fix)

Kept because the first ETAS fits were made on them. Same window and sources; Nepal floor 3.0,
Türkiye floor 2.5, California floor 2.45, `strict` magnitude policy everywhere, and the depth
filter still dropping negative-depth events.

| Region | Events | Events with Mw | Mc maximum curvature | Mc b-value stability | Runtime |
|---|---|---|---|---|---|
| `nepal-himalaya` | 2 847 | 2 165 | 4.40 (b = 1.14) | 4.70 (b = 1.21) | 146 s |
| `turkiye-eaf` | 27 716 | 2 572 | 4.30 (b = 1.03) | 4.60 (b = 1.16) | 32 s (a first attempt failed after 324 s on a stray `?` line in the ISC 2023 page; fixed in `isc.py`) |
| `california` | 104 630 | 3 418 | 3.70 (b = 0.59) | 4.90 (b = 0.95) | 510 s |

The California figures in that table are the artefact ADR-0019 was written to remove: only 49 % of
events reported at M ≥ 3.95 carried an Mw, so the b of 0.59 described the availability of moment
tensors, not the seismicity. Under the current publication rules (§ 2) that estimate would not have
been published to `Region.mc` at all.

## 6. Known limitations

- **ISC text format carries one magnitude per event.** Other agencies' magnitudes for the same ISC
  event are not fetched; Mw comes from GCMT directly instead. ISF/QuakeML would carry them at a
  cost in parsing and volume.
- **ISC-GEM is absent** from every build so far (form-gated download; ADR-0005). The top of the
  location precedence is therefore ISC in practice.
- **ISC reviewed bulletin lags about two years**; the FDSN service still returns later events,
  but as other agencies' prime hypocentres (IDC, GFZ, NEIC), which the adapter cannot tell apart
  from reviewed ISC solutions in the text format.
- **No cited ML/Md→Mw relation.** Under the `strict` policy (Nepal, Türkiye) events reported only
  as `ML`/`Md` have `mw = None` and enter neither Mc nor fits — 596 Nepal and 4 675 Türkiye events.
  Under `network-preferred-as-mw` (California, ADR-0019) those magnitudes are *assumed*
  Mw-equivalent, which is an approximation adopted from CSEP RELM practice, not a conversion:
  93 % of the California catalogue's Mw values are assumed rather than measured or converted, and
  every one is identifiable by the `assumed-equivalent:` prefix in `mw_conversion`. A cited
  regional relation would be a new ADR and a rebuild.

  **What that share is where it matters** (recomputed 2026-09-04 from the shipped
  `data/catalogs/california/events.parquet`, 107 601 earthquakes):

  | Slice | Events | `assumed-equivalent` | `identity` (moment) | `scordilis2006` |
  |---|---|---|---|---|
  | whole catalogue | 107 601 | 100 660 (93.5 %) | 2 627 | 607 |
  | at or above the fitted Mc 2.70 | 60 103 | 56 869 (**94.6 %**) | 2 627 | 607 |
  | at or above the target 3.95 | 3 319 | 1 588 (47.8 %) | 1 124 | 607 |

  The middle row is the one to read: the published California Mc (2.70 maximum curvature, 2.60
  stability), its b = 1.01, and every ETAS fit trained above that Mc rest on a magnitude
  distribution that is 95 % assumption. The top row is what the whole file is; the bottom row shows
  the assumption thinning out at the target threshold, where moment magnitudes dominate, so the
  *scored targets* are much less affected than the *fitted rate* is. None of this is visible from
  `Region.mc.notes` in `data/regions/california/region.json`, which records only Mw coverage and b;
  naming the assumed share there is a one-line change in `commands/catalog.py::region_mc_decision`
  and belongs to that file's owner.
- **Fixed windows** merge dense cross-bulletin aftershock pairs within 16 s / 100 km; the lane
  rule protects only same-bulletin pairs. The gate verifies the algorithm's guarantee (no cross-lane
  pair within the windows survives), not that every merge is right.
- **Quick CMTs** (`qcmt.ndk`, stamp `Q-`) are used for the most recent months and may be revised;
  the `raw_type` says which flavour each Mw came from.
- **`Region.mc` may be absent by design.** `--update-region-mc` refuses to publish a
  maximum-curvature Mc whose b < 0.7 or whose Mw coverage at the target threshold is < 80 %,
  because such an estimate describes magnitude availability rather than seismicity. The estimates
  are still written to `mc_estimates`, and `--force-mc` overrides with a note on the record.
- **ComCat summary feed has no uncertainties** (`horizontalError` etc. are only in the detail
  feed), so location/time/magnitude uncertainties are `None` for ComCat-preferred events.
- **Scordilis (2006) intercepts** carry a `verify` note (ADR-0017).
- **Region polygons for Nepal and Türkiye are corridors defined by rupture**, not official regions
  (`data/regions/<id>/region.json`, `description`).
