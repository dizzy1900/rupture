# Catalogue build

rupture does not predict earthquakes. This document describes how `rupture catalog build` turns
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
Parameters: `--time-window-s`, `--distance-km`. Single linkage in time order, nearest member.
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
| — | ML, Md, `mb1`, `ms_vx`, unknown scales, or mb/Ms outside the ranges | `None` + `magnitude_unconvertible` in the log |

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
depth within `[depth_min_km, depth_max_km]` (`depth_filtered`; unknown depth kept). Half-open
`[from, to)` on `origin_time`.

### Completeness (`pipelines/completeness.py`)

On the homogenised Mw of earthquakes, 0.1 bins:

- **maximum curvature** (Wiemer & Wyss 2000) + 0.2 (Woessner & Wiemer 2005); ties resolved to the
  lowest bin before the correction;
- **b-value stability** (Cao & Gao 2002; Woessner & Wiemer 2005): first cut-off whose Aki b is
  within σ_b (Shi & Bolt 1982) of the mean b of the next five cut-offs; ≥ 30 events per cut-off;
  if no cut-off is stable the method is absent and the notes say so;
- **`mc_ks`** cross-check with `etas.mc_b_est.estimate_mc` (Mizrahi et al. 2021), p ≥ 0.1,
  2 000 simulated samples; reported when it passes, skipped with `--no-etas-cross-check`.

b is Aki (1965) MLE with the Utsu half-bin correction: `b = log10(e) / (mean(m) − (Mc − 0.05))`.
All estimates land in `Catalog.completeness`; `Region.mc` stores the maximum-curvature one from
the real build (`--update-region-mc`).

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
  uv run dvc add data/catalogs/$r
done
```

Add `--sources comcat,isc,gcmt,isc-gem` with `RUPTURE_ISC_GEM_CSV` set to include ISC-GEM; without
the variable the build proceeds and records `source isc-gem not included` in the catalogue notes.
`--min-magnitude` overrides the floor; `--no-etas-cross-check` skips the KS estimate (used for
California, where the simulation on ~10^5 magnitudes is slow).

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
windows 16 s / 100 km, source magnitude floor = target − 1.5 (California 2.45, Nepal 3.0,
Türkiye 2.5). ISC-GEM was **not** included (no CSV configured). Results are what the commands
above printed; nothing here is adjusted.

| Region | Events (earthquake / explosion / other) | Preferred source (ISC / ComCat / GCMT) | Events with Mw | Mc maximum curvature (+0.2) | Mc b-value stability | Mc KS (`etas`) | Runtime |
|---|---|---|---|---|---|---|---|
| `nepal-himalaya` | 2 847 (2 846 / 1 / 0) | 2 812 / 35 / 0 | 2 165 | **4.40** (b = 1.14 ± 0.04, n = 1 037) | 4.70 (b = 1.21 ± 0.06, n = 500) | 4.20 (n = 1 670) | 146 s |
| `turkiye-eaf` | 27 716 (27 446 / 269 / 1) | 27 632 / 82 / 2 | 2 572 | **4.30** (b = 1.03 ± 0.03, n = 915) | 4.60 (b = 1.16 ± 0.05, n = 494) | 4.70 (n = 387) | 32 s (second attempt; the first, 324 s, failed on a stray `?` line in the ISC 2023 page, fixed in `isc.py`, and its pages were reused from `data/raw/isc/`) |
| `california` | 104 630 (103 535 / 1 068 / 27) | 42 852 / 61 778 / 0 | 3 418 | **3.70** (b = 0.59 ± 0.01, n = 2 358) — see caveat | 4.90 (b = 0.95 ± 0.04, n = 486) | not run (`--no-etas-cross-check`) | 510 s |

The bold maximum-curvature values were written to `data/regions/<id>/region.json` (`mc`) by
`--update-region-mc`. Homogenised-Mw mix: Nepal 1 663 `scordilis2006:mb`, 306 `scordilis2006:ms`,
126 `identity:mw` (ISC's GCMT Mw), 70 `identity:mwc`, 682 without Mw (ISC `ML`, `mb1`, `MD`, and
`mb` < 3.5); Türkiye 1 570 `identity:mw`, 672 `scordilis2006:mb`, 122 `identity:mwc`, 118
`identity:mwr`, 89 `scordilis2006:ms`, 25 144 without Mw (ISC `ML`, `MD`/`Md`); California 1 534
`identity:mw`, 788 `identity:mwr`, 683 `scordilis2006:mb`, 276 `identity:mwc`, 129
`scordilis2006:ms`, 8 `identity:mww`, 101 212 without Mw (ISC `ML`, ComCat `md`/`ml`/`mc`/`mh`).
Largest events: Gorkha 2015-04-25 Mw 7.88 (ISC + ComCat + GCMT), Kahramanmaraş 2023-02-06
Mw 7.78 and 7.70 (three sources each), Imperial Valley 1980-11-08 Mw 7.30 and Landers 1992-06-28
Mw 7.28 (three sources each). Records associated from two sources: Nepal 921, Türkiye 1 172,
California 38 233; from three: 70, 120, 336.

**California caveat.** Only 3 211 of 103 535 California earthquakes have a homogenised Mw, because
ComCat `ml`/`md`/`mc` and ISC `ML`/`MD` have no accepted conversion (ADR-0017). Of the 3 056
earthquakes with *any* reported magnitude ≥ 3.95, only 1 487 (49 %) carry Mw; the rest are
`ml`-only (ComCat `ml` 717, ISC `ML`/`mL` 636, ComCat `mlr` 45, ...). The Mw frequency-magnitude
distribution is therefore not a Gutenberg–Richter population (moment tensors exist mainly above
about M 3.5), the maximum-curvature b of 0.59 is a symptom of that, and **the California Mc of
3.70 must not be read as the completeness of California seismicity**. Until a cited ML→Mw relation
for California is adopted (a new ADR), the homogenised California catalogue is unfit for a
M ≥ 3.95 target at the RELM convention: about half of the target-size events would be missing.
The Nepal and Türkiye catalogues are less affected because ISC's preferred magnitude there is
`mb` (convertible) for most M ≥ 4 events.

**Thresholds against the protocol rule** (`EVALUATION_PROTOCOL.md` § 1 rule 3, both methods at or
below the target): Nepal target 4.5 vs. Mc 4.40 / 4.70 — the b-value-stability estimate is
*above* the provisional threshold; Türkiye target 4.0 vs. 4.30 / 4.60 — both estimates are above
the provisional threshold; California target 3.95 vs. 3.70 / 4.90 — the b-value-stability estimate
is above it and the catalogue has the Mw-coverage problem above. Under the protocol's own rule the
Nepal and Türkiye thresholds would rise (to ≥ 4.7 and ≥ 4.6) and an ADR must record that;
this document does not change them.

ISC coverage: the ISC FDSN service returned events through 2026-07 for all three regions, but rows
after the reviewed period carry other agencies' prime hypocentres (`Author` = IDC, GFZ, ...), not
ISC's reviewed solutions; the adapter records the row's `MagAuthor` and does not distinguish
reviewed from preliminary. ISC-GEM was not included in any build.

Outputs are DVC-tracked through the `build_catalog@<region>` stages in `dvc.yaml`
(`uv run dvc commit -f build_catalog@<region>`, recorded in `dvc.lock`; `dvc add` refuses paths
that are stage outputs). Sizes: Nepal 0.2 MB parquet + 2.7 MB log; Türkiye 1.5 MB + 15.9 MB;
California 5.6 MB + 80 MB (one `ingested` entry per source record). `data/interim/` and
`data/raw/` are git-ignored as whole directories, so `dvc add` could not place `.dvc` pointers
for `gem_active_faults.parquet` (13 696 faults, 2.4 MB) or `data/raw/eshm20/` (55 files, 40.2 MB,
`manifest.json` verified); both were fetched on 2026-09-03 and are reproducible from the
functions in § 4.

## 6. Known limitations

- **ISC text format carries one magnitude per event.** Other agencies' magnitudes for the same ISC
  event are not fetched; Mw comes from GCMT directly instead. ISF/QuakeML would carry them at a
  cost in parsing and volume.
- **ISC-GEM is absent** from every build so far (form-gated download; ADR-0005). The top of the
  location precedence is therefore ISC in practice.
- **ISC reviewed bulletin lags about two years**; the FDSN service still returns later events,
  but as other agencies' prime hypocentres (IDC, GFZ, NEIC), which the adapter cannot tell apart
  from reviewed ISC solutions in the text format.
- **No ML/Md conversion**: California events reported only as `ml`/`mlr` (most below about M 3.5
  in the RELM region) have `mw = None` and do not enter Mc or fits; the effective floor of the
  homogenised California catalogue is therefore set by the availability of `mw`/`mwr` and `mb`,
  not by the fetch floor. A regional relation is a new ADR.
- **Fixed windows** merge dense cross-bulletin aftershock pairs within 16 s / 100 km; the lane
  rule protects only same-bulletin pairs. The gate verifies the algorithm's guarantee (no cross-lane
  pair within the windows survives), not that every merge is right.
- **Quick CMTs** (`qcmt.ndk`, stamp `Q-`) are used for the most recent months and may be revised;
  the `raw_type` says which flavour each Mw came from.
- **ComCat summary feed has no uncertainties** (`horizontalError` etc. are only in the detail
  feed), so location/time/magnitude uncertainties are `None` for ComCat-preferred events.
- **Scordilis (2006) intercepts** carry a `verify` note (ADR-0017).
- **Region polygons for Nepal and Türkiye are corridors defined by rupture**, not official regions
  (`data/regions/<id>/region.json`, `description`).
