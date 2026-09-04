# ADR-0037 — the Chamoli / Ronti scenario case: how a scenario without a published answer is built

- **Status:** accepted
- **Date:** 2026-09-03
- **Relates to:** ADR-0020 (two ground-motion adapters), ADR-0026 (USGS ground-failure models),
  ADR-0027 (serac slope units), ADR-0033 (GSIM coefficient provenance)

## Context

The cascade layer is specified with two input routes: published ShakeMap grids for real events, and
scenario ground-motion fields for scenarios. It is also specified with two validation regions —
Gorkha, and the Ronti / Chamoli region. Until this ADR, only the first of each existed: the Gorkha
reproduction runs on a committed slice of a real ShakeMap, and the scenario route was unreachable
from the CLI, which exited 2 for any scenario other than Gorkha.

Chamoli is not a second Gorkha, and the difference is the whole design problem:

- **The 2021 Chamoli disaster was not earthquake-triggered.** It was a rock and ice avalanche from
  the north face of Ronti Peak. No earthquake preceded it, no ShakeMap exists for it, and the USGS
  has published no `ground-failure` product for this catchment.
- rupture therefore has **no published answer to be validated against** here, in the sense that the
  Gorkha rasters are an answer.
- rupture also holds **no published rupture model** for the Garhwal Himalaya: no finite-fault
  inversion is committed, and no Vs30 raster covers the region.

The options were: skip the region and leave the brief's second validation case unbuilt; fabricate a
rupture and a Vs30 field and present the result as a validation; or build a scenario that is
honestly labelled and assert the things about it that can actually fail.

## Decision

Build the scenario, label every input as an assumption, and be explicit about what the case does
and does not establish. `src/rupture/adapters/cascade/chamoli.py`.

**1. The rupture is hypothetical and says so in its own payload.** `ScenarioRupture.hypothetical`
is `True`; its `notes` carry the word HYPOTHETICAL, the sentence "not a forecast", and the full
assumption list. The geometry is a 25 x 25 km patch of the Main Himalayan Thrust decollement with
its top at 10 km, taking the dip (7 deg), strike (293 deg) and rake (101 deg) resolved for central
Nepal and **adopting** them for Garhwal — an explicit transfer, recorded as such, not a Garhwal
inversion.

**2. The magnitude is computed, not chosen.** `Mw` follows from the patch area and a stated 0.6 m
average slip through Hanks & Kanamori (1979), the same construction the loss layer's MHT scenario
uses, so the geometry and the magnitude cannot disagree. (Mw 6.66 at the committed parameters.)
The formula is implemented locally in the cascade adapter rather than imported from
`rupture.risk`, so this layer does not depend on the loss layer; a test asserts the two agree.

**3. The location comes from serac's committed geometry, not from a typed-in coordinate.** The
evaluation window is the union of every slope-unit footprint and every exposed asset serac maps for
`chamoli-rishiganga`, buffered by 0.06 deg, and the rupture is centred beneath that window. The
question the scenario asks is "what would shaking of this size directly beneath this catchment do
to the screen", not "where is the next rupture".

**4. Vs30 is one assumed reference value, 760 m/s, and the consequence is reported rather than
tuned away.** rupture holds no Vs30 raster for Garhwal, and the ShakeMap `SVEL` band the Gorkha
case uses exists only where a ShakeMap does. 760 m/s (NEHRP B/C) is above the Zhu et al. (2017)
`vs30max` of 620 m/s, so **the liquefaction model masks every cell of this window**. That is the
published model declining to speak about a rock-site mountain catchment; the gate asserts that the
mask fires and reports why, rather than the case being quietly restricted to the landslide model.

**5. The ground motion comes from the verified native GSIM.** `BooreEtAl2014` through
`NativeGsimEngine`, which is verified against OpenQuake's own expected values (ADR-0020) and is the
only active-shallow-crust GSIM rupture ships. Median fields, one realisation: the ground-failure
models are deterministic in the shaking, and rupture does not propagate GSIM variability into a
susceptibility product it has no uncertainty model for.

**6. What the gate asserts, and what it does not.** It does **not** assert agreement with a
published product, because there is none. It asserts what can fail: the rupture is marked
hypothetical; the median PGA is inside `[0.02, 2.0]` g and the median PGV inside `[1, 300]` cm/s
(bands no unit error survives); the coverage is finite in `[0, 1]`; the landslide field still
declares its static covariates incomplete; the Vs30 mask zeroes every cell; the exposure record's
`shaking_source` is the GSIM field and not the Gorkha ShakeMap; the downstream assets and the
footprint polygon survive; and the record round-trips through GeoParquet. Every number is printed
whether or not it is asserted.

## Consequences

- The scenario route exists end to end and is reachable from the CLI
  (`rupture cascade run --scenario chamoli-ronti-mht-hypothetical`,
  `rupture cascade exposure --aoi chamoli-rishiganga --scenario ...`,
  `rupture cascade scenario`). Both of the brief's input routes now run.
- `chamoli-rishiganga` is the AOI the Gorkha ShakeMap route **cannot** serve — it is outside that
  grid, and sampling it raised — so the two routes are visibly independent.
- The case's receptors are the two hydropower projects serac maps there, not settlements; that
  drove the additive `ExposedSlopeUnit.assets_below` field (ADR-0038).
- The layer's honest position is unchanged: with no static covariate sourced, this is the shaking
  response of the published models over the catchment. `docs/CASCADE.md` §3.5 and §8 say so.

## Alternatives rejected

- **Reconstruct the 1999 Chamoli earthquake as the scenario.** A real regional event would be
  better grounded, but its source parameters are not committed to this repository and this
  implementation will not type published focal parameters in from memory. A future ADR may replace
  the hypothetical patch with a committed inversion.
- **Treat the 2021 Ronti Gad avalanche itself as the case.** It was not earthquake-triggered;
  running an earthquake-triggered ground-failure model on it would misrepresent both the event and
  the model.
- **Fabricate a Vs30 field with plausible spatial structure.** Refused. One assumed value, labelled,
  with its consequence reported.
