# C3 — Triggered cascades

**These are susceptibility and exposure products. They are not forecasts of individual slope
failures.** Every record in this layer carries that caveat in its own payload
(`CascadeExposure.label`, `GroundFailureField.notes`) so a downstream reader cannot lose it. The
models say where ground failure is more or less likely given shaking and terrain, fitted to
inventories of past earthquakes. They do not say that a particular slope, road or parcel fails.

Layer C3 has six parts: two USGS ground-failure models; a reproduction of the real published USGS
product for 2015 Gorkha; a scenario case over the Ronti / Chamoli region, which is the layer's
non-ShakeMap route and has no published answer to check against (§3.5); a co-seismic ice/rock
avalanche exposure overlay built on the sibling `serac`'s slope units, published as GeoParquet
(§4.1); the client side of the `SourceTypeAssessment` discriminator contract shared with `serac`;
and a documented, untrained hook for a learned global model (§9).

Decisions: [ADR-0026](adr/0026-usgs-ground-failure-models.md) (model choice and coefficient
provenance), [ADR-0027](adr/0027-serac-slope-units.md) (serac integration, fixture-fallback rule,
threshold basis), [ADR-0042](adr/0042-learned-ground-failure-hook.md) (the learned-model hook),
[ADR-0043](adr/0043-chamoli-ronti-scenario.md) (the Chamoli / Ronti scenario case),
[ADR-0044](adr/0044-cascade-exposure-geoparquet.md) (CascadeExposure as GeoParquet).
Model card: [`reports/MODEL_CARD_cascade.md`](../reports/MODEL_CARD_cascade.md)
— tracked with `git add -f`, because `.gitignore` excludes `/reports/`; note that `make clean`
does `rm -rf reports` and will delete it from a working tree (`git checkout reports/` restores it).

---

## 1. The two models

### 1.1 Landslide — Nowicki Jessee et al. (2018)

> Nowicki Jessee, M.A., Hamburger, M.W., Allstadt, K.E., Wald, D.J., Robeson, S.M., Tanyas, H.,
> Hearne, M., Thompson, E.M. (2018). A Global Empirical Model for Near Real-time Assessment of
> Seismically Induced Landslides. *Journal of Geophysical Research: Earth Surface*, **123**,
> 1835-1859. doi:[10.1029/2017JF004494](https://doi.org/10.1029/2017JF004494)

Logistic in log-transformed PGV with slope, lithology, land cover and the compound topographic
index:

```
X = -6.30 + 1.65 ln(PGV) + 0.06 s + 1.0 lith + 0.03 CTI + 1.0 lc + 0.01 ln(PGV) s
P = 1 / (1 + exp(-X))
coverage = exp(-7.592 + 5.237 P - 3.042 P^2 + 4.035 P^3)
```

PGV in cm/s clipped to `[0, 211]`; `s` slope in degrees; CTI clipped to `[0, 19]`. `lith` and `lc`
are **per-class coefficients**, not scalars: the USGS pre-substitutes fitted values into two global
rasters, which is why the model coefficient for both is `1.0`. Masks: slope in `(2, 90]` degrees;
PGA at or above 2 %g. Maximum reported coverage 0.256.

### 1.2 Liquefaction — Zhu et al. (2017), general (global) model

> Zhu, J., Baise, L.G., Thompson, E.M. (2017). An Updated Geospatial Liquefaction Model for Global
> Application. *Bulletin of the Seismological Society of America*, **107**, 1365-1385.
> doi:[10.1785/0120160198](https://doi.org/10.1785/0120160198)

```
X = 8.801 + 0.334 ln(PGV * m(Mw)) - 1.918 ln(Vs30) + 5.408e-4 precip
      - 0.2054 min(d_coast, d_river) - 0.0333 wtd
m(Mw) = 1 / (1 + 2.71828^(-2 (Mw - 6)))
P = 1 / (1 + exp(-X))
coverage = 0.4915 / (1 + 42.4 exp(-9.165 P))^2
```

PGV in cm/s clipped to `[0, 150]`; precipitation in mm clipped to `[0, 2500]`; distances in km;
water-table depth in m. Masks: slope in `[0, 5]` degrees; PGV at or above 3 cm/s; PGA at or above
10 %g; Vs30 at or below 620 m/s. Maximum reported coverage 0.487.

The `2.71828` is the literal the USGS operational code uses in place of `e`. rupture reproduces it
exactly, because the object is the operational product; the difference is about 1e-6.

### 1.3 Where the coefficients come from

Not retyped from the papers. Taken from the USGS `groundfailure` reference implementation
(`code.usgs.gov/ghsc/esi/groundfailure/groundfailure`, US public domain + CC0 1.0), whose relevant
files are committed under `tests/fixtures/cascade/usgs_groundfailure/` with provenance and licence:

| Committed file | Upstream | Carries |
|---|---|---|
| `jessee_2018.py.txt` | `src/gfail/models/jessee_2018.py` | `COEFFS`, `CLIPS`, `COV_COEFFS` |
| `zhu_2017.py.txt` | `src/gfail/models/zhu_2017.py` | `COEFFS`, `CLIPS`, `COV_COEFFS` |
| `jessee_2018.ini` | `defaultconfigfiles/models/jessee_2018.ini` | slope band, `minpga`, `maxprob` |
| `zhu_2017_general.ini` | `defaultconfigfiles/models/zhu_2017_general.ini` | slope band, `minpgv`, `minpga`, `vs30max` |

`src/rupture/cascade/coefficients.py` restates them; `tests/unit/cascade/test_coefficients.py` and
the `validate-cascade` gate **re-parse the committed files** and fail on any divergence.
`tests/integration/cascade/test_upstream_fixtures.py` re-fetches them over the network and fails if
the USGS changes them.

### 1.4 Two things this implementation could not settle

Recorded in `coefficients.OPEN_QUESTIONS` and asserted by a test, so they cannot be quietly
dropped.

1. **The interaction sign.** The operational USGS code carries `b6 = 0.01` for `ln(PGV) x slope`
   and *adds* it (`X += term * coeff`), in both `jessee_2018.py` and its `slim` variant. Secondary
   descriptions of the paper give the interaction as negative. rupture implements `+0.01`, because
   that is the value the published Gorkha product it reproduces was computed with and the only one
   verifiable against a primary machine-readable source. **This implementation has not read the
   paper's own table.** Anyone with the paper to hand should check it; if it is negative, the
   operational product and the paper disagree and that disagreement should be reported upstream,
   not silently reconciled here.
2. **The per-class lithology and land-cover coefficients.** They live inside two USGS global
   rasters that are not published at a fetchable URL. rupture does not carry them at all.

---

## 2. The covariate situation, stated plainly

Neither model can be run as published from anything rupture holds.

**Sourced** — from the same published ShakeMap Atlas grid the USGS ground-failure product was
computed from (`shakemap_version` 1 for Gorkha, matching the product's own `info.json`):

- PGA (%g → g), PGV (cm/s), Vs30 (the ShakeMap `SVEL` band).

One caveat on Vs30: the USGS ground-failure product does **not** use ShakeMap `SVEL`; it uses the
Wald and Allen (2007) topographic-slope raster. The two are close but not the same, and the
difference is visible in the reproduction numbers below (a handful of cells fall on the other side
of the `vs30max = 620` mask).

**Not sourced** — these are the declared gap:

| Model | Covariate | Upstream dataset | Why not |
|---|---|---|---|
| Landslide | slope (gradient) | GMTED2010 (`global_grad.tif`) | global raster, not published at a fetchable URL by either `groundfailure` repository |
| Landslide | lithology coefficient | GLiM, pre-substituted (`GLIM_replace.tif`) | as above; the per-class table is also not machine-readable to this implementation |
| Landslide | land-cover coefficient | GlobCover/MODIS, pre-substituted | as above |
| Landslide | CTI | HYDRO1k (`global_cti_fil.grd`) | as above |
| Liquefaction | mean annual precipitation | WorldClim | as above |
| Liquefaction | distance to coast / river | NASA Ocean Color, HydroSHEDS | as above |
| Liquefaction | water-table depth | Fan et al. (2013) | as above |

**Nothing was substituted for them.** `src/rupture/cascade/covariates.py` makes that structural: a
covariate is either sourced with provenance, or absent, in which case its term is zero and every
output record names it. The default source is `UnsourcedCovariates`, which sources nothing, and a
field computed that way carries `static conditioning factors INCOMPLETE (...); not sourced and
treated as zero: cti, landcover_coefficient, lithology_coefficient, slope_deg` in its `notes`.

Consequence, stated bluntly: **rupture cannot currently produce a conditioned ground-failure
susceptibility map.** It can produce the shaking response of the published models, and it can show
that its implementation of those models matches the operational one. Those are different claims.

---

## 3. Validation against the real USGS product — 2015 Gorkha

ComCat `us20002926` (Mw 7.8, 2015-04-25, 28.2305 N 84.7314 E) is one of the events for which the
USGS published a `ground-failure` product, so the implementation can be held against a real answer.

**What is committed** (`tests/fixtures/cascade/gorkha-2015/`, ~1.5 MB, provenance and parent
sha256 recorded for each):

| File | Real slice of | Cells |
|---|---|---|
| `shakemap_grid_slice.csv` | ShakeMap Atlas `grid.xml` (LON, LAT, PGA, PGV, SVEL, verbatim) | 20 410 |
| `usgs_zhu_2017_general_coverage_slice.csv` | published `zhu_2017_general_model.tif`, every 4th cell | 15 300 |
| `usgs_jessee_2018_coverage_slice.csv` | published `jessee_2017_model.tif`, every 8th cell | 15 402 |
| `usgs_ground_failure_info_preferred.json` | the product's `info.json`, Summary + the two preferred models | — |

Window 84.0–86.5 E, 26.3–28.0 N (the ShakeMap slice extends to 28.40 N so the serac Langtang AOI
is inside it). Cell values and coordinates are the parent rasters' own, unmodified, at the
product's own four-decimal rounding.

### 3.1 Three comparisons, and what each is worth

`rupture cascade reproduce` runs all three and reports all three.

- **`link`** — invert the published coverage raster to recover `X`, feed it back through rupture's
  coverage transform and masks. Tests the logistic link, the published coverage polynomial or
  saturating curve, the masks and the rounding. Must be exact.
- **`shaking`** — recover the static (non-shaking) part of `X` from the published product, then
  recompute the field from the ShakeMap PGV, PGA and Vs30 with rupture's coefficients. Tests the
  intercept, the shaking coefficients, the magnitude scaling, the clips and the masks. **Does not
  test the static covariates**: they were taken from the answer.
- **`unconditioned`** — run rupture's model with no static covariate at all, which is what rupture
  can actually do today. This is the number that describes present capability.

Cells at or below each model's own `maskthreshold` are excluded, because the published raster is
rounded to four decimals and the coverage transform cannot be inverted stably there. That is a
conditioning limit, not a disagreement.

### 3.2 The numbers actually achieved

Liquefaction, **Zhu et al. (2017) general**, 6 636 of 15 300 published cells (coverage > 0.005),
published mean coverage 0.15933:

| Comparison | Pearson r | MAD | max abs diff | within 0.01 | bias |
|---|---|---|---|---|---|
| `link` | 1.0000 | 0.00000 | 0.00000 | 1.0000 | +0.00000 |
| `shaking` | **0.9956** | **0.00064** | 0.31740 | 0.9917 | −0.00064 |
| `unconditioned` | **0.4534** | **0.10170** | 0.35320 | 0.0895 | −0.08639 |

Landslide, **Nowicki Jessee et al. (2018)**, 5 246 of 15 402 published cells (coverage > 0.002),
published mean coverage 0.03694:

| Comparison | Pearson r | MAD | max abs diff | within 0.01 | bias |
|---|---|---|---|---|---|
| `link` | 1.0000 | 0.00000 | 0.00000 | 1.0000 | +0.00000 |
| `shaking` | 1.0000 | 0.00000 | 0.00000 | 1.0000 | +0.00000 |
| `unconditioned` | **0.1624** | **0.03310** | 0.24710 | 0.4453 | −0.03280 |

**Read these carefully.**

- The **landslide `shaking` row is degenerate** and the report says so at runtime. No
  shaking-dependent mask fires in this window, and without slope the interaction term vanishes, so
  every shaking term is absorbed by the static term recovered from the product and the comparison
  collapses onto `link`. Its perfect score is arithmetic, not validation. The liquefaction
  `shaking` row is not degenerate: it exercises three masks and the magnitude scaling, which is
  why it is 0.9956 and not 1.0000.
- The liquefaction `shaking` max abs diff of 0.317 with a MAD of 0.00064 is the Vs30 source
  difference: a small number of cells sit on the other side of `vs30max = 620` when Vs30 comes
  from ShakeMap `SVEL` rather than the Wald and Allen raster.
- **The `unconditioned` rows are the honest headline.** With no static covariate sourced, rupture
  reproduces the published Gorkha liquefaction raster at r = 0.45 and the landslide raster at
  r = 0.16, both strongly biased low. That is poor, it is exactly what the covariate gap costs,
  and it is what rupture can do today.

### 3.3 A check that could have failed

The `shaking` comparison would look good even with a wrong coefficient table, because the static
term is recovered from the answer and absorbs errors. So the reproduction also tests
**admissibility**: the recovered static term must lie inside the range the published coefficients
and clips permit. For the liquefaction model, precipitation is clipped at 2 500 mm and enters with
`+5.408e-4`, while distance-to-water and water-table depth enter with negative coefficients on
non-negative quantities — so the static term cannot exceed `5.408e-4 x 2500 = 1.352`.

Observed over the well-conditioned cells: **98.87 %** are at or below 1.352; median 0.3927
(≈ 730 mm of precipitation net of the negative terms, which is what the Ganges plain should look
like); maximum 2.1646. A wrong coefficient, a units error or a mis-ordered term would have pushed
this well outside the band. The residual ~1 % tail is consistent with the Vs30 source difference.

No such bound exists for the landslide model: its lithology and land-cover coefficients are
unbounded above and rupture does not carry them. The report says so rather than inventing a bound.

### 3.4 Reproducing it

```bash
uv run rupture validate cascade                 # the gate; offline
uv run rupture cascade reproduce --out reports/cascade/gorkha.json
```

### 3.5 The second region — Chamoli / Ronti, and what it is *not*

The brief names two validation regions. Gorkha is a reproduction against a published answer.
Chamoli is not, and the difference has to be stated before the numbers.

**The 2021 Chamoli disaster was not earthquake-triggered.** It was a rock and ice avalanche from
the north face of Ronti Peak, on 7 February 2021. No earthquake preceded it, no ShakeMap exists for
it, and the USGS has published no `ground-failure` product for this catchment. rupture also holds
no published rupture model for the Garhwal Himalaya and no Vs30 raster covering it.

So the Chamoli case is a **scenario**, and it is what the scenario route is *for*
([ADR-0043](adr/0043-chamoli-ronti-scenario.md), `src/rupture/adapters/cascade/chamoli.py`):

| | |
|---|---|
| Rupture | a **HYPOTHETICAL** 25 x 25 km patch of the Main Himalayan Thrust decollement, top at 10 km, centred beneath serac's `chamoli-rishiganga` extent. Dip 7 deg, strike 293 deg, rake 101 deg, adopted from the central-Nepal MHT geometry and stated as an adoption |
| Magnitude | **Mw 6.66, computed** from that area and 0.6 m average slip through Hanks & Kanamori (1979) — an output of the geometry, not an input |
| Window | 79.570–79.860 E, 30.270–30.553 N at 1/240 deg — the union of serac's AOI footprints and its two exposed assets, buffered by 0.06 deg. No coordinate is typed in by hand |
| Ground motion | `BooreEtAl2014` through the native GSIM engine, verified against OpenQuake's own expected values ([ADR-0020](adr/0020-ground-motion-two-adapters.md)); median field, one realisation |
| Vs30 | **760 m/s assumed at every site** (NEHRP B/C). rupture holds no Vs30 raster here and does not manufacture a spatially varying one |

Numbers on the committed inputs: median PGA **0.4274 g** (0.2547–0.4274 over the window), median
PGV **36.06 cm/s** (21.33–36.06), 4 899 cells. Landslide areal coverage **0.0015–0.0033**, mean
0.0031, and — as everywhere else in this layer — **unconditioned**: no static covariate is sourced
here either, so this is the shaking response of the published model, not a susceptibility map.

The liquefaction model masks **every cell**. 760 m/s is above Zhu's `vs30max` of 620, so the model
declines to speak about a rock-site mountain catchment. That is the right answer for this setting,
it is asserted by the gate rather than worked around, and it is the one mask in this layer that
demonstrably fires.

**What this case establishes, and what it does not.** It establishes that the scenario route runs
end to end — a documented rupture, a verified GSIM, both models, the slope-unit overlay, the
GeoParquet output — over the region the brief names, and it gives the gate checks that can fail: a
unit error in either intensity measure, an unwired mask, a lost caveat, an exposure record that
silently fell back to the Gorkha ShakeMap. It establishes **no** agreement with a published
product, because there is none to agree with. It is not evidence that the models are right in the
Garhwal Himalaya, and no number in §3.5 should be quoted as if it were.

```bash
uv run rupture cascade scenario                             # the rupture and its assumptions
uv run rupture cascade run --scenario chamoli-ronti-mht-hypothetical --model landslide
uv run rupture cascade exposure --aoi chamoli-rishiganga \
    --scenario chamoli-ronti-mht-hypothetical --out-parquet reports/cascade/chamoli.parquet
```

---

## 4. Co-seismic ice/rock avalanche exposure, and the serac integration

`SlopeUnitSource` reads `serac`'s `slope-unit.v0` contract from `$SERAC_EXPORT_DIR`. As of
2026-09-03 **serac has not exported any slope units**, so rupture falls back to serac's own AOI
build — see [ADR-0027](adr/0027-serac-slope-units.md) for the full rule.

**What serac data is used.** For `lhende-khola-trishuli` (the Langtang / Trishuli corridor, i.e.
the Langtang 2015 mechanism) and `chamoli-rishiganga`, rupture reads serac's `source_zone.geojson`
and `exposed_assets.geojson`, committed byte-verbatim under `tests/fixtures/cascade/serac/` with
serac's repository, commit `8eee940`, Apache-2.0 licence and an explicit statement that they are
serac's, not rupture's.

**What the fallback does and does not claim.** One unit per source-zone polygon, using serac's
geometry, `geometry_quality` and `source_refs`, with **every terrain attribute null** — slope,
aspect, elevation band, glacier cover, permafrost index, lithology, area. serac's AOI build carries
no DEM; rupture has no basis for any of them and manufactures none. The record therefore reports
`slope_unit_source = serac-aoi-fallback:<aoi>`, `provenance = assumed`,
`confidence = unqualified`, and names the screens it could not apply.

**The threshold.** `--pga-threshold` defaults to **0.02 g (2 %g)**, the floor below which the USGS
ground-failure landslide model declines to evaluate at all (`jessee_2018.ini`:
`minpga = 2. # %g (Jibson and Harp, 2016)`). It is a floor below which a published model says
nothing, **not** a level at which a slope fails. No established shaking threshold exists for
co-seismic ice/rock avalanche release and rupture does not invent one. A secondary steepness screen
defaults to 30 degrees, the conventional lower bound for rapid rock and ice avalanche source areas,
and is applied only to units that carry a slope — under the fallback, none of them.

**Contract mismatch**, absorbed by the adapter and documented in ADR-0027: serac's
`glacier_cover` is a boolean and rupture's is a fraction (`true -> 1.0`, meaning *glacierised*, not
*fully glacierised*); serac's `elevation_band_m` is `[low, high]` and rupture's is a string
(`"4200-5600 m"`).

**`settlements_below`** is populated from the settlements serac maps in the AOI's river corridor
(`timure`, `syabrubesi`, `betrawati` for Langtang). serac's asset records carry no elevation, so
"below" is corridor membership and not a verified elevation relation; the record's `notes` say so.

**`settlements_below` is not the only receptor.** serac maps **no settlement at all** in
`chamoli-rishiganga`: the assets it carries there are the Rishi Ganga and Tapovan Vishnugad
hydropower projects, both hit in 2021 by an avalanche of exactly this mechanism. Calling them
settlements would be wrong and dropping them would lose the AOI's only receptors, so
`ExposedSlopeUnit.assets_below` carries them separately, with the same corridor-membership caveat
([ADR-0044](adr/0044-cascade-exposure-geoparquet.md)).

```bash
uv run rupture cascade exposure \
    --aoi lhende-khola-trishuli --scenario us20002926 --pga-threshold 0.02 \
    --out-parquet reports/cascade/langtang.parquet
```

Output on the committed fixtures: 1 slope unit, PGA sampled from the Gorkha ShakeMap at the
source-zone centroid, above the 0.02 g screen, both terrain screens reported as not applied.

### 4.1 The output format: GeoParquet with provenance

`--out-parquet` writes the record as GeoParquet, one row per slope unit, EPSG:4326
(`src/rupture/adapters/cascade/geoparquet.py`, [ADR-0044](adr/0044-cascade-exposure-geoparquet.md)).

- **`geometry`** is the unit's footprint polygon — `ExposedSlopeUnit.polygon`, the exterior ring
  carried through from the slope-unit source. Where the source has no polygon the geometry is the
  representative point the PGA was sampled at; where it has neither, the geometry is **null**, not
  invented.
- Scalar unit fields are columns of the same name; `settlements_below`, `assets_below` and
  `source_refs` are `*_json` strings, as in the catalogue writer.
- The **record-level fields and the caveat are Parquet key-value metadata** under `rupture:`:
  scenario, AOI, kind, threshold, slope-unit source, shaking source, provenance tier, confidence
  tier, `computed_at`, notes, unit counts, the susceptibility `label`, and `rupture:statement`. A
  consumer that opens only the schema still sees what the file is and is not.
- The round trip is exact — `read_cascade_exposure(write_cascade_exposure(x)) == x` — and the gate
  asserts it every run for both the Gorkha and the Chamoli records.

---

## 5. Discriminator client

`src/rupture/cascade/discriminator.py` reads serac's `SourceTypeAssessment` records from
`$SERAC_EXPORT_DIR/source-type-assessments/` and applies them:

- an event with `p_mass_movement >= 0.5` (configurable) is retagged `EventType.LANDSLIDE`, which
  is what `Catalog.earthquakes()` already excludes — so it leaves the tectonic ETAS fit and is
  counted in the cascade layer;
- **retagging is one-way.** rupture will move an event *out* of the tectonic set on serac's
  evidence and will never move one back in. A discriminator false negative would put a mass
  movement into an earthquake rate model, which is the failure mode this exchange exists to
  prevent;
- assessments within 0.1 of the threshold are reported as borderline; assessments matching no
  catalogue event are reported, not dropped; a record that fails contract validation raises rather
  than being skipped.

**Accounting.** `DiscriminatorAccounting` separates two routes out of the tectonic set:
`already_tagged` (the source catalogue typed it, e.g. ComCat `type=landslide`) and `reclassified`
(serac's evidence moved it), and reports both plus the total.

**Fixture case.** `us7000tbwb` — ComCat `type=landslide`, M 5.2, 2026-08-26, Nepal — reusing the
fixture already committed at `data/fixtures/comcat/nepal-2026-landslide-us7000tbwb.geojson` from
Prompt 1. The gate asserts it is tagged `landslide`, is excluded by `Catalog.earthquakes()`, and is
counted as excluded from tectonic fitting. On that fixture: **2 of 2 events excluded from tectonic
fitting (2 already tagged, 0 reclassified)** — there is no serac export to reclassify from yet, and
the accounting says exactly that rather than reporting a zero that looks like agreement.

---

## 6. CLI

```
rupture cascade cases
rupture cascade scenario  [--out FILE]
rupture cascade run       --scenario <id> --model landslide|liquefaction [--out FILE]
rupture cascade run       --grid-xml <grid.xml> [--stride N] [--magnitude M]
rupture cascade run       --pgv-field <gmf.json> [--pga-field <gmf.json>] [--magnitude M]
rupture cascade exposure  --aoi <id> --scenario <id> [--pga-threshold <g>]
                          [--pga-field <gmf.json> | --grid-xml <grid.xml>]
                          [--out FILE] [--out-parquet FILE]
rupture cascade fetch-shakemap --event <comcat id> --out-dir <dir> [--url URL]   # network
rupture cascade reproduce [--model ...] [--out FILE]
rupture cascade discriminate --catalog <geojson> [--export-dir <serac>] [--threshold p]
```

`src/rupture/cli.py` mounts the sub-application, so `rupture cascade ...` works directly
(`python -m rupture.commands.cascade ...` still works and is equivalent).

### 6.1 The four input routes

`src/rupture/adapters/cascade/cases.py` holds them, and `rupture cascade cases` lists the two that
run offline from committed inputs. Nothing in the layer manufactures shaking; a request that cannot
be satisfied exits 1 and names what would satisfy it.

| Route | How to reach it | What it is |
|---|---|---|
| `committed-shakemap` | `--scenario us20002926` | the committed slice of the published Gorkha ShakeMap Atlas grid |
| `scenario-gsim` | `--scenario chamoli-ronti-mht-hypothetical` | a documented hypothetical rupture through the verified native GSIM (§3.5) |
| `shakemap-grid-xml` | `--grid-xml <path>` | any real ShakeMap `grid.xml` on disk, parsed by `read_grid_xml`; `--stride N` subsamples a large grid |
| `supplied-field` | `--pgv-field` / `--pga-field` | a `ground-motion-field.v0` JSON from anywhere else in rupture (the loss layer's scenario calculation, an OpenQuake run) |

For a real event rupture does not already carry:

```bash
uv run rupture cascade fetch-shakemap --event us6000jllz --out-dir data/raw/shakemap/us6000jllz
uv run rupture cascade run --grid-xml data/raw/shakemap/us6000jllz/grid.xml --model landslide
```

`fetch-shakemap` reads the USGS event API, takes the preferred `shakemap` product's
`download/grid.xml`, and writes it beside a `provenance.json` recording the URL, retrieval time,
sha256 and licence. It fetches or fails: an event with no ShakeMap product, or a response that is
not a grid, raises and writes nothing. It is the only networked verb in this layer, and the offline
tests exercise every path in it with an injected fetcher.

## 7. Gate

`make validate-cascade` (`src/rupture/validation/cascade.py`, registered by `mk/cascade.mk`) runs
offline and checks:

1. every coefficient still equals its value in the committed USGS source, and every mask still
   equals its value in the committed `.ini`;
2. every file listed in a cascade `provenance.json` exists and matches its sha256;
3. the Gorkha `link` round trip is exact for both models (tolerance 1e-9), and the recovered
   static term is admissible for at least 95 % of cells where a bound exists (observed 98.87 %);
4. `us7000tbwb` is tagged `landslide`, is excluded by `Catalog.earthquakes()`, and is counted;
5. a `CascadeExposure` validates against `contracts/cascade-exposure.v0.json` and a
   `GroundFailureField` against `contracts/ground-failure-field.v0.json`;
6. every emitted probability is finite and in `[0, 1]`;
7. every emitted record still carries the susceptibility caveat;
8. **the scenario route** (§3.5): the Chamoli rupture is marked hypothetical; the median PGA is
   inside `[0.02, 2.0]` g and the median PGV inside `[1, 300]` cm/s — bands chosen so that a
   units error cannot pass, not as a claim about the ground motion; the landslide field is finite
   and still declares its static covariates incomplete; the Zhu `vs30max` mask zeroes every cell at
   the assumed rock Vs30; the exposure's `shaking_source` is the GSIM field and not the Gorkha
   ShakeMap; the downstream assets and the footprint polygon survive;
9. **the GeoParquet round trip** is exact for both the Gorkha and the Chamoli exposure records, and
   the file's key-value metadata still carries the susceptibility label.

The `unconditioned` agreement is **reported, never asserted**. A gate that asserted a poor number
would make the poor number look intentional; a gate that hid it would be worse. The same rule
applies to every scenario number in check 8: the observed values are printed each run, and only the
bands and the structural facts are asserted.

---

## 8. Limitations

Read this section before using anything in this layer.

1. **No conditioning covariates.** rupture holds none of the seven static rasters the two models
   need. Everything it produces today is the shaking response of the published models with the
   static term at zero, and it reproduces the published Gorkha product at r = 0.45 (liquefaction)
   and r = 0.16 (landslide), biased low in both cases. This is the single limitation that matters
   most; the rest follow from it.
2. **The slope-band masks never fire.** Both models are defined only inside a slope band (2–90
   degrees for landslide, 0–5 for liquefaction). Without a slope raster rupture cannot apply
   either, so the ~47 % of published cells that are exactly zero for that reason are not
   reproducible here. The output names the mask as not applied.
3. **Vs30 provenance differs from the product's.** rupture uses the ShakeMap `SVEL` band; the USGS
   product uses Wald and Allen (2007). Visible as ~1 % of cells falling on the other side of the
   `vs30max` mask.
4. **The landslide `shaking` comparison is degenerate** in this window and proves nothing beyond
   the link round trip. There is no independent falsifiable check on the landslide coefficients
   comparable to the liquefaction admissibility band, because the lithology and land-cover terms
   are unbounded above.
5. **One event, one window — and one scenario with no answer to check against.** The reproduction
   against a published product is Gorkha only, over 84.0–86.5 E / 26.3–28.0 N. The second region
   the brief names, Chamoli / Ronti, is a **scenario**: the 2021 disaster there was not
   earthquake-triggered, no ShakeMap and no published ground-failure product exist for the
   catchment, and rupture holds no published rupture model or Vs30 raster for the Garhwal
   Himalaya. §3.5 runs the scenario route end to end over that region and asserts what can fail;
   it establishes no agreement with any published product, and its numbers must not be quoted as
   validation. Nothing here says how the implementation behaves for a different tectonic setting,
   magnitude range, or ShakeMap version.
6. **The interaction sign is unresolved** (§1.4). If the operational `+0.01` is wrong, the
   landslide model is wrong wherever slope is sourced — which is nowhere today, so it currently
   changes nothing, and it will matter the moment slope arrives.
7. **Uncertainty is not propagated.** The USGS publishes a standard-deviation raster per model and
   rupture computes none. `GroundFailureCell` has no uncertainty field and the layer makes no
   interval claim.
8. **The exposure product is one polygon per AOI.** Until serac exports `slope-unit.v0`, the
   co-seismic avalanche layer for an AOI is a single source-zone unit with null terrain and both
   terrain screens unapplied — for `lhende-khola-trishuli` and for `chamoli-rishiganga` alike. It
   demonstrates the contract and now carries real geometry into a GeoParquet a GIS can overlay; it
   is still not an inventory, and the "glacierised steep slope units" filter the mechanism is
   about **cannot fire on any real unit** until serac publishes terrain attributes. rupture holds
   no copy of serac's `slope-unit.v0` schema under `contracts/` either, so the export parser is
   written against an uncommitted contract.
9. **`settlements_below` means corridor membership**, not a verified elevation relation (§4).
10. **The threshold is a screening device.** 0.02 g is the floor of a published *landslide* model,
    applied to an *ice/rock avalanche* mechanism for want of anything better. It is not a release
    criterion and no number in this layer should be read as one.
11. **No discriminator has run.** serac has exported no `SourceTypeAssessment` records, so zero
    events have been reclassified. The client is implemented and tested against synthetic
    assessments and the real `us7000tbwb` record; it has never seen a real serac assessment.
12. **Aggregate statistics are not reproduced.** The USGS publishes aggregate hazard (km²) and
    population exposure per event. rupture computes neither, so its output cannot be compared to
    the product's alert levels.
13. **The scenario rupture is hypothetical in every parameter.** Its geometry is adopted from
    central Nepal, its extent and depth are modelling choices, its Vs30 is one assumed reference
    value, and its magnitude — though computed rather than chosen — is computed from assumed
    inputs. `hypothetical=True` and the assumption list travel in the record. It is not a forecast
    and not a statement that an event of this size occurs beneath that catchment.
14. **No learned model is trained, shipped or scored.** §9 is a hook and nothing more.
15. **`fetch-shakemap` has not been run against the live USGS API in this environment.** Its URL
    selection, provenance record and every failure path are exercised offline with an injected
    fetcher; the networked call itself is untested here.

---

## 9. The learned-model hook — documented, not trained

The brief asks for a documented hook for a learned global earthquake-triggered landslide model as
the v1 candidate, and asks that it **not** be trained. Decision:
[ADR-0042](adr/0042-learned-ground-failure-hook.md); code: `src/rupture/cascade/learned.py`.

**rupture trains nothing here.** Nothing in this repository is fitted on a landslide inventory, no
weights are shipped, and no learned model is scored. `LearnedGroundFailureModel` raises
`NotImplementedError` on construction, and the reserved id `learned_global_landslide_v1` is
deliberately **absent** from `MODEL_CLASSES` and `ALIASES`, so `build()` refuses it. A registered
stub returning zeros would be an untrained model shipping with a susceptibility record attached.

What an implementation owes, asserted by `tests/unit/cascade/test_learned_hook.py`:

1. satisfy `rupture.ports.cascade.CascadeModel` — `model_id`, `model_version`, `source_refs`, and
   `evaluate(field, *, scenario_id) -> GroundFailureField`;
2. emit a `GroundFailureField` whose cells are in `[0, 1]`, whose `provenance` names the weights
   (source, URL, sha256, licence), and whose `notes` still carry the susceptibility label;
3. name every covariate it consumes — `rupture.cascade.covariates`' rule is unchanged: sourced with
   provenance, or absent and declared. Silent imputation is not admissible;
4. ship or fetch weights with provenance; weights are data and obey the data rules;
5. obey [ADR-0022](adr/0022-leakage-engineering-for-learned-models.md) **if it is fitted or
   fine-tuned in this repository** — training events disjoint from scoring events, half-open
   cutoffs, the assertion in the test that fits it. (Evaluating a model fitted elsewhere carries no
   cutoff, which is why the two incumbents carry none.);
6. be scored by the same code on the same targets — `adapters.cascade.reproduction` against the
   published Gorkha rasters and `adapters.cascade.chamoli` on the scenario route — and report the
   same comparisons;
7. be registered under its own id, and take the `landslide` alias only after it beats the incumbent
   on those targets.

**rupture does not name the paper.** The brief identifies the candidate as the 2025 deep-learning
earthquake-triggered landslide model; this implementation does not have its primary source and will
not restate a citation it has not read — the same rule §1.4 applies to the interaction sign. The
implementer commits the citation, the weights and the licence with the code.
