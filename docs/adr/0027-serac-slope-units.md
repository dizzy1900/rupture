# ADR-0027 — serac slope units: the file contract, the fixture-fallback rule, and the threshold

- **Status:** accepted
- **Date:** 2026-09-03

## Context

The co-seismic ice/rock avalanche layer needs terrain units to overlay shaking on. rupture does
not build them: that is `serac`'s L0 susceptibility inventory, published as
`contracts/slope-unit.v0.json` (ADR-0014 fixed the rule that the two repositories share file
contracts and never code).

On 2026-09-03 `serac` exists and has AOIs — `lhende-khola-trishuli` (the Langtang / Trishuli
corridor, i.e. the Langtang 2015 mechanism), `chamoli-rishiganga`, `blatten-lotschental` — but has
**not exported any slope-unit.v0 records**. What it has per AOI is `aoi.json`, `corridor.geojson`,
`river_centreline.geojson`, `source_zone.geojson`, `transects.geojson` and
`exposed_assets.geojson`, all with its own source refs and geometry-quality labels. There is no
DEM-derived terrain anywhere in it yet.

So rupture must implement `SlopeUnitSource` against a contract that has no data behind it, without
either (a) waiting, or (b) inventing terrain attributes that look like serac's.

## Decision

**Resolution order.** `SeracSlopeUnitSource` looks, in order, for:

1. a real serac export — `$SERAC_EXPORT_DIR/slope-units/<aoi>.geojson` (and three spelling
   variants) — which is used as-is and marked `is_fallback = False`;
2. serac's AOI build under `$SERAC_EXPORT_DIR/data/aoi/<aoi>/`;
3. the committed copy of (2) under `tests/fixtures/cascade/serac/<aoi>/`, so the offline suite
   runs with no serac checkout present.

Routes 2 and 3 produce the **fallback**.

**The fallback rule.** The fallback emits one unit per serac source-zone polygon, using serac's own
geometry, its `geometry_quality` and its `source_refs`, and leaves **every terrain attribute null**
— `mean_slope_deg`, `aspect_deg`, `elevation_band_m`, `glacier_cover`, `permafrost_index`,
`lithology_tag`, `area_m2`. serac's AOI build carries no DEM, so rupture has no basis for any of
them and does not manufacture one. Consequences that follow, and are enforced by tests:

- the resulting `CascadeExposure.slope_unit_source` reads `serac-aoi-fallback:<aoi>`, never
  `serac-slope-unit-v0`;
- its `provenance` is `ModelProvenance.ASSUMED` and its `confidence` is
  `ConfidenceTier.UNQUALIFIED` (a real export gets `PUBLISHED` / `LOW`);
- the terrain screens that would have used those attributes are **not applied**, and the record's
  `notes` say how many units that affected.

**serac's data stays serac's.** The committed fixture is a byte-verbatim copy of serac's files
with a `provenance.json` recording the repository, the commit (`8eee940`), the licence
(Apache-2.0) and an explicit statement that rupture does not present them as its own. rupture never
edits them and never re-derives them; when serac exports slope units, `SERAC_EXPORT_DIR` takes
precedence and the fallback stops being used.

**The contract mismatch is mapped, and the mapping is recorded.** serac's `slope-unit.v0` and
rupture's `ExposedSlopeUnit` disagree on two field types:

| serac `slope-unit.v0` | rupture `ExposedSlopeUnit` | Mapping |
|---|---|---|
| `glacier_cover: boolean` | `glacier_cover: float [0, 1]` | `true -> 1.0`, `false -> 0.0` |
| `elevation_band_m: [low, high]` | `elevation_band_m: string` | `[a, b] -> "a-b m"` |

The `1.0` means *glacierised*, not *fully glacierised*: a boolean carries no fraction and the
mapping cannot invent one. rupture does not ask serac to change its contract; the adapter absorbs
the difference and this ADR is where the semantics are written down.

**The threshold and its basis.** `--pga-threshold` defaults to **0.02 g (2 %g)**. Basis: the USGS
ground-failure landslide model declines to evaluate at all below 2 %g
(`defaultconfigfiles/models/jessee_2018.ini`: `minpga = 2. # %g (Jibson and Harp, 2016)`,
committed under `tests/fixtures/cascade/usgs_groundfailure/`). It is a floor below which a
published model says nothing — **not** a level at which a slope fails.

There is no established shaking threshold for co-seismic ice/rock avalanche release, and rupture
does not invent one. The threshold is a screening device, it is configurable, and every record
says so in its `notes`. A secondary steepness screen defaults to 30 degrees — the conventional
lower bound for rapid rock and ice avalanche source areas — and is applied **only** to units that
actually carry a slope, which under the fallback is none of them.

**What "settlements below" means today.** `ExposedSlopeUnit.settlements_below` is populated from
the settlements serac maps in the AOI's river corridor. serac's asset records carry no elevation,
so "below" is corridor membership and not a verified elevation relation; the exposure record says
exactly that. Fixing it needs elevations from serac, not a guess from rupture.

## Consequences

- The exposure product exists and runs end to end on the 2015 Gorkha ShakeMap over the Langtang
  corridor, which is the mechanism the brief names. What it currently says is thin — one unit, one
  PGA, screens not applied — and it is labelled thin rather than dressed up.
- The moment serac exports `slope-unit.v0`, the fallback disappears with no code change, the
  screens start applying, and the provenance and confidence tiers rise on their own.
- rupture carries a copy of a sibling's data. That is a maintenance cost and a licence obligation,
  discharged by the provenance record and the Apache-2.0 attribution, and revisited when serac
  publishes.
- `SERAC_EXPORT_DIR` is now a real integration point for two things — slope units and
  `SourceTypeAssessment` records — and is documented in `docs/CASCADE.md`.

## Alternatives considered

- **Wait for serac.** Rejected: it leaves `SlopeUnitSource` unimplemented and untested, and the
  contract unexercised in the direction that matters.
- **Derive slope units from a DEM in rupture.** Rejected: that is serac's job (ADR-0014), it would
  create a second inventory that disagrees with serac's, and rupture holds no DEM.
- **Fill the terrain attributes with regional typical values** so the screens can run. Rejected:
  fabricated data presented as real. A screen that cannot be applied is reported as not applied.
- **Import serac as a Python dependency.** Forbidden by CLAUDE.md and ADR-0014.
- **A threshold from the ice-avalanche literature.** None was found that gives a shaking level for
  release; using a landslide threshold from a different mechanism would have been a fabricated
  citation. The USGS 2 %g floor is used for what it actually is — the floor of a published model —
  and the record says the mechanism differs.
