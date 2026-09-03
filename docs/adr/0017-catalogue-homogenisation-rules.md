# ADR-0017 — Catalogue homogenisation rules: precedence, association windows, magnitude conversions

- **Status:** accepted
- **Date:** 2026-09-03

## Context

`rupture catalog build` merges USGS ComCat, the ISC Bulletin, Global CMT and (when the user
supplies the CSV, ADR-0005) ISC-GEM into one catalogue per test region with a homogenised
moment magnitude on every event that has an accepted route to Mw. The merge needs fixed,
documented rules for (a) which records are the same event, (b) whose location, time and depth
win, (c) how Mw is chosen or converted, and (d) how event types are tagged. These rules are
inputs to the evaluation protocol (`docs/EVALUATION_PROTOCOL.md` § 7 rule 5) and must not drift
once forecasts are issued. Implementation: `src/rupture/pipelines/build_catalog.py`,
`src/rupture/pipelines/magnitudes.py`, `src/rupture/pipelines/completeness.py`.

## Decision

### Association (duplicate identification)

- Two records are the same event when `|Δt| ≤ 16 s` **and** great-circle distance `≤ 100 km`,
  the windows Weatherill, Pagani & Garcia (2016, GJI 206, 1652–1676) use to merge global
  bulletins. Both are `MergeConfig` parameters (`--time-window-s`, `--distance-km`).
- Association is single-linkage in time order; a record joins the cluster holding its nearest
  compatible member.
- **Lane rule.** Records from the same *lane* never merge with each other: a bulletin has already
  de-duplicated its own events, and the fixed windows would otherwise collapse dense aftershock
  pairs (Ridgecrest, Gorkha) into one. The lane is the source id (`isc`, `gcmt`, `isc-gem`),
  except ComCat where it is `usgs-comcat/<net>` (the leading letters of the ComCat id), so that
  ComCat's separate copies of other agencies' origins (`iscgem…`, `us…` next to `ci…`) can be
  associated across networks.
- **GCMT is matched on its reference hypocentre** (NDK line 1, the PDE/ISC origin), not on its
  centroid: the centroid time lags the origin by the half-duration (32 s for Gorkha 2015, outside
  the 16 s window). The parser encodes the reference hypocentre in `provenance.notes`;
  `gcmt.reference_hypocentre()` decodes it; the event itself carries the centroid location and time.

### Preferred solution (location, time, depth, as-reported magnitude, provenance)

`ISC-GEM > ISC > ComCat > GCMT`. GCMT is a centroid and wins only when no hypocentral source has
the event. Within ComCat, the network's own origin is preferred over ComCat's copy of another
catalogue (`net=iscgem`). The merged event's `source_catalog`/`source_event_id` are the winner's,
and its id is `rup-<sha1('<source>:<id>')[:12]>`, stable across rebuilds.

### Homogenised Mw

Highest first, over every magnitude any contributing record reported:

1. GCMT Mw from the scalar moment, `Mw = (2/3)(log10 M0[dyne·cm] − 16.1)` (Hanks & Kanamori 1979),
   rounded to two decimals — `identity:mwc`;
2. ISC-GEM Mw — `identity:mw`;
3. a reported moment magnitude (`mww`, `mwc`, `mwb`, `mwr`, `mw`) from ISC, then ComCat —
   `identity:<type>`;
4. `mb` or `Ms` converted with **Scordilis (2006)**, J. Seismol. 10, 225–236,
   doi:10.1007/s10950-006-9012-4, inside the published validity ranges only:

   | From | Range | Relation | Stored as |
   |---|---|---|---|
   | mb | 3.5 ≤ mb ≤ 6.2 | Mw = 0.85 mb + 1.03 | `scordilis2006:mb` |
   | Ms | 3.0 ≤ Ms ≤ 6.1 | Mw = 0.67 Ms + 2.07 | `scordilis2006:ms` |
   | Ms | 6.2 ≤ Ms ≤ 8.2 | Mw = 0.99 Ms + 0.08 | `scordilis2006:ms` |

   When one source reports both, Ms is preferred over mb (it saturates later);
5. otherwise `mw = None`, `mw_conversion = None`, and the log records
   `magnitude_unconvertible`. **ML, Md, `mb1` (IDC), `ms_vx` and unknown scales are not
   converted**: no regional relation for the three test regions was cited at the time of writing,
   and an uncited relation is a guess. Such events stay in the catalogue and drop out of
   magnitude-based analyses by filter (`Catalog.at_least`).

`verify` note: the slopes (0.85, 0.67, 0.99) and the ranges above were confirmed on 2026-09-03
against third-party citations of Scordilis (2006); the intercepts (1.03, 2.07, 0.08) match the
brief and the author's reading of the paper, but the paper itself could not be opened (paywall)
during this work. Anyone with access should confirm the three intercepts against Table 2 of the
paper and remove this note; if any differ, `SCORDILIS_TABLE` in `pipelines/magnitudes.py` is the
single place to change, and every rebuilt catalogue records the relation in `mw_conversion`.

### Event type

Any non-earthquake tag from any contributing record is kept (ComCat is the only source that
classifies routinely). ComCat `type` maps to `EventType` as follows: `earthquake` → earthquake;
`landslide`, `rockslide`, `avalanche`, `snow avalanche`, `debris flow` → landslide;
`explosion`, `quarry blast`, `quarry`, `mining explosion`, `mine explosion`, `nuclear explosion`,
`chemical explosion`, `experimental explosion` → explosion; `rock burst`, `mine collapse`,
`collapse`, `ice quake`, `volcanic eruption`, `sonic boom`, `induced or triggered event`,
`not reported`, `other event` and any unknown string → other. Nothing is dropped for its type;
`us7000tbwb` (landslide, 2026-08-26, Nepal) is the gate's canary.

### Filters and logging

Spatial (polygon `covers`) and depth filters run **after** association, on the preferred
solution, so a GCMT centroid just outside the polygon still contributes its Mw. Unknown depth is
kept. Every decision is a `HomogenisationLogEntry` (`ingested`, `duplicate_merged`,
`preferred_solution`, `magnitude_converted` / `magnitude_unconvertible`, `event_type_tagged`,
`outside_region_dropped`, `depth_filtered`) written to `homogenisation_log.jsonl`.

### Completeness

Both estimators are reported on the homogenised Mw of earthquakes (non-earthquake types excluded),
0.1 bins: maximum curvature + 0.2 (Wiemer & Wyss 2000; Woessner & Wiemer 2005) and b-value
stability (Cao & Gao 2002; Woessner & Wiemer 2005: first cut-off whose b is within σ_b of the mean b
of the next five 0.1 bins, ≥ 30 events per cut-off). b is the Aki (1965) MLE with the Utsu half-bin
correction; σ_b is Shi & Bolt (1982). The `etas` package KS estimate (Mizrahi et al. 2021) is a
third, optional cross-check. `Region.mc` stores the maximum-curvature estimate from the real build;
the protocol threshold rule is in `docs/EVALUATION_PROTOCOL.md` § 1.

## Consequences

- One documented, parameterised path from four bulletins to one catalogue; every event says which
  record won and how its Mw was obtained.
- Fixed windows are a compromise: dense aftershock pairs across *different* bulletins within 16 s
  and 100 km are merged into one event (the lane rule protects same-bulletin pairs only). The
  gate checks that no cross-lane pair survives within the windows, which is the algorithm's
  guarantee, not a claim that every merge is correct.
- Small events reported only with ML/Md have no Mw and do not enter Mc estimation or ETAS fits;
  for California this matters below about M 3.5, where ComCat reports `ml`/`mlr`. A regional
  ML→Mw relation would be a new ADR.
- Changing any rule here after a forecast schedule has started requires a new ADR and a rebuild
  (new catalogue hash).

## Alternatives considered

- **Magnitude-dependent windows** (larger windows for larger events). Rejected for Prompt 1:
  the GCMT reference-hypocentre key removes the main need; revisit if merge diagnostics show misses.
- **Di Giacomo et al. (2015) ISC-GEM regressions** for mb/Ms. Not rejected; Scordilis (2006) was
  the relation named in the brief. Either would be recorded per event in `mw_conversion`.
- **Trusting ComCat's own `ids` association list.** Not used: it associates only what ComCat
  ingested, and the merge must also work for ISC and GCMT records ComCat never saw.
