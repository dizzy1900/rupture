# RISK — ground motion to loss to avoided loss (F2)

rupture does not predict earthquakes. This layer answers a different question, and one that is
useful to an underwriter whether or not any forecast model has skill: **for a given rupture, what
does a portfolio lose, and what does an intervention avoid?**

Everything below was run in this worktree. Where something did not run, it says so and why.

---

## 1. Architecture

```
serac export ──┐
GEM export   ──┤──▶ ExposurePortfolio ─┐
user import  ──┘                       │
                                       ├─▶ risk.loss ────────▶ per-event MoneyRange
ScenarioRupture ──▶ GroundMotionEngine ┤                              │
   (Gorkha / MHT)                      ├─▶ VulnerabilityModel         │
                                       │    (HAZUS + assumed)         │
F1 ForecastGrid ──▶ risk.event_set ────┤                              │
   (promoted ETAS)   (rates + events)  └─▶ risk.event_based ──▶ ANNUAL MoneyRange
                                                              + exceedance curves
                                                                      │
                                                                      ▼
                                            risk.avoided_loss ──▶ AvoidedLossResponseV1
                                                                      │
                                                                      ▼
                                                                CLI / FastAPI
```

| Layer | Module | Port |
|---|---|---|
| Exposure | `adapters/exposure/{serac_export,geoparquet_import,gem_global}.py` | `ports/exposure.py` |
| Valuation | `adapters/exposure/valuation.py` | — |
| Ground motion | `adapters/groundmotion/{native,openquake_scenario,openquake_event_based}.py` | `ports/ground_motion.py` |
| GSIM logic trees | `adapters/groundmotion/logic_trees.py` | `domain/groundmotion.py` |
| Vulnerability | `adapters/vulnerability/{hazus,hydropower,library}.py` | `ports/vulnerability.py` |
| Damage / loss | `risk/{damage,loss,curves}.py` | — |
| Event sets / annual loss | `risk/{event_set,event_based}.py` | — |
| Avoided loss | `risk/avoided_loss.py` | contract `avoided-loss.v1.json` |
| Scenarios | `risk/scenarios.py` | — |
| Service | `risk/service.py` | — |
| CLI | `commands/risk.py` | — |
| Gate | `validation/risk.py`, `mk/risk.mk` | — |

---

## 2. Two ground-motion engines, and when each is used

ADR-0020 gives the `GroundMotionEngine` port two adapters.

**`native_gsim` (`rupture.native_gsim`)** evaluates a small set of published GSIMs in process. It
is what runs on this machine, in the offline gate, and in every number quoted in this document. It
is not a reimplementation of the engine: it does one calculation — a scenario field for one rupture
at a fixed set of sites — and every field it produces records that *it*, not the engine, produced
the numbers.

**`openquake.engine`** runs the authoritative scenario calculator in the pinned
`openquake/engine:3.26.2` container. `OpenQuakeScenarioEngine` subclasses the existing
`OpenQuakeDocker` so the image pin, availability check, Docker invocation and log capture are
shared rather than copied; what is new is rendering a scenario `job.ini` with a **site model** (so
each site keeps its own Vs30), writing the rupture as NRML, and parsing the `gmf_data` CSV export.

> **This path has never been observed to produce a number.** The image is `linux/amd64`-only and
> this machine is arm64 (ADR-0011 addendum). Its job rendering and its export parsers are unit
> tested; the container run itself is exercised only by
> `tests/integration/risk/test_engine_cross_check.py`, which runs in CI on amd64 and **skips
> locally with the reason printed**. Set `RUPTURE_RISK_REQUIRE_ENGINE=1` to make a skip a failure,
> which is what the CI job does so a silently skipped cross-check cannot pass for a green one.

Use the engine wherever it can run. Use `native_gsim` where it cannot, and read the `engine` field
on every `GroundMotionField` before quoting a number from it.

### GSIM verification results

A GSIM ships only if it reproduces OpenQuake's own committed expected values. The tables are
carried under `tests/fixtures/risk/gsim/<name>/` with a `provenance.json` (URL, retrieval time,
sha256 per file, licence AGPL-3.0-or-later) and are re-fetched by
`tests/fixtures/risk/gsim/refresh.py`.

| GSIM | Reference tables | Values compared | Worst mean | Worst stddev | Tolerance asserted |
|---|---|---|---|---|---|
| `AbrahamsonEtAl2015SInter` (BC Hydro interface, central ΔC1) | `BCHYDRO_SINTER_CENTRAL_*` | 22 400 | **4.9e-07 %** | **0 % (exact)** | 0.01 % / 0.01 % |
| `BooreEtAl2014` (BSSA14, global Q, no basin, sof) | `BSSA_2014_{MEAN,TOTAL_STD,INTER_STD,INTRA_STD}` | 70 200 | **1.759 %** | **0.0167 %** | 2.0 % / 0.1 % |
| `BooreEtAl2014(sof=False)` (unspecified mechanism) | `BSSA_2014_NOSOF_*` | 23 400 | **1.759 %** | **0.0167 %** | 2.0 % / 0.1 % |
| `BooreEtAl2014HighQ` (high-Q Δc3: China, Turkey) | `BSSA_2014_HIGHQ_*` | 70 200 | **1.759 %** | **0.0167 %** | 2.0 % / 0.1 % |
| `BooreEtAl2014LowQ` (low-Q Δc3: Italy, Japan) | `BSSA_2014_LOWQ_*` | 70 200 | **1.759 %** | **0.0167 %** | 2.0 % / 0.1 % |

The BSSA14 mean figure needs a sentence, because 1.76 % is much larger than the others and it would
be easy to leave that unexplained. The reference table lists 39 intensity measures; the committed
coefficient table does not list three of them (SA(0.21), SA(0.23), SA(4.5)), so their coefficients
must be interpolated in log period. Split by that:

| BSSA14 mean, split | Values | Worst discrepancy |
|---|---|---|
| At the 36 tabulated intensity measures | 16 200 | **0.00067 %** |
| At SA(0.21), SA(0.23), SA(4.5) — interpolated | 1 350 | **1.759 %** |

So rupture's implementation of the equations agrees with Boore's Fortran reference to seven
decimal places wherever the coefficients are tabulated. The 1.76 % is the cost of a coarser
coefficient table, it is inherent to the table rather than to rupture, and OpenQuake carries the
same discrepancy — its own test tolerance for BSSA14 is 2 %, which is presumably why. A test asserts
both halves separately, so the tight number cannot silently become the loose one.

**Coefficient provenance.** The coefficient tables are extracted from the `gem/oq-engine` source at
tag `engine-3.26` by `tests/fixtures/risk/gsim/refresh_coefficients.py` — never hand-typed — and
stored under `src/rupture/adapters/groundmotion/data/` with a `provenance.json`. **Licence note for
the architect:** oq-engine is AGPL-3.0-or-later and rupture is Apache-2.0. The extracted values are
numeric coefficients first published in the journal articles (Boore et al. 2014,
doi:10.1193/070113EQS184M; Abrahamson et al. 2016, doi:10.1193/051712EQS188MR); the machine-readable
transcription is upstream's. rupture does not link or ship the engine. **Resolved in
ADR-0033**, which records the position, the attribution given, and the re-derivation path if it is
ever challenged.

**Paper titles.** Both published titles contain a word the banned-language gate forbids. ADR-0034
resolved this: quoting somebody else's published title verbatim is a citation, not a claim rupture
makes, so the allowlist admits exactly those two title strings and the titles appear in full:

- Boore, Stewart, Seyhan & Atkinson (2014), doi:10.1193/070113EQS184M:
  "NGA-West2 Equations for Predicting PGA, PGV, and 5% Damped PSA for Shallow Crustal Earthquakes"
- Abrahamson, Gregor & Addo (2016), doi:10.1193/051712EQS188MR:
  "BC Hydro Ground Motion Prediction Equations for Subduction Earthquakes"

### The GSIM logic tree

Full reasoning in **ADR-0037**. One GSIM gives an interval conditional on that GSIM being right,
which is the narrowest assumption in a loss figure. `GsimLogicTree` (in `domain/groundmotion.py`)
carries the epistemic alternative as weighted branches; `NativeGsimEngine.scenario_logic_tree`
allocates realisations between them by largest remainder, so the weights are honoured **exactly**
rather than in expectation, and the OpenQuake adapter writes the same object as
`gsim_logic_tree.xml` so the two engines cannot drift apart. `RunConfig.gsim_logic_tree` threads it
through every path in the risk layer.

rupture ships one runnable tree, `rupture-asc-bssa14-q-v0`:

| Branch | GSIM | Weight | What it stands for |
|---|---|---|---|
| `global-q` | `BooreEtAl2014` | 1/3 (**assumed**) | the model's default global anelastic attenuation, Δc3 = 0 |
| `high-q` | `BooreEtAl2014HighQ` | 1/3 (**assumed**) | the paper's high-Q adjustment (China, Turkey): less loss with distance |
| `low-q` | `BooreEtAl2014LowQ` | 1/3 (**assumed**) | the paper's low-Q adjustment (Italy, Japan): more loss with distance |

**What this tree is not.** Its three branches are regional variants of **one** NGA-West2 model, not
independent models. A national or regional PSHA tree for active shallow crust carries several
independent NGA-West2 models — Chiou & Youngs 2014, Campbell & Bozorgnia 2014, Abrahamson, Silva &
Kamai 2014, Idriss 2014 — which differ far more from one another. rupture has implemented and
verified none of those four, so they are named in the tree's own `excluded` field rather than
shipped as branch names it cannot run. **The spread this tree produces is a lower bound on GSIM
epistemic uncertainty, not an estimate of it.** The weights are `assumed`: no published weighting of
the Q-region choice for the Himalaya was found, and equal weights say "rupture cannot choose", not
"these are equally right".

**And it barely moves this corridor, for an instructive reason.** The Δc3 adjustment is an
anelastic-attenuation term that only bites with distance, and the corridor sits at Rjb = 0 under a
shallow thrust:

| Site distance from the Gorkha plane | `BooreEtAl2014` | `HighQ` | `LowQ` | Spread |
|---|---|---|---|---|
| the corridor (Rjb = 0) | 0.4925 g | 0.4974 g | 0.4881 g | **1.02x** |
| ~70 km east | 0.2541 g | 0.2640 g | 0.2455 g | 1.08x |
| ~120 km east | 0.1219 g | 0.1367 g | 0.1100 g | 1.24x |
| ~170 km east | 0.0582 g | 0.0743 g | 0.0468 g | 1.59x |
| ~220 km east | 0.0317 g | 0.0464 g | 0.0226 g | 2.06x |
| ~270 km east | 0.0184 g | 0.0309 g | 0.0116 g | **2.68x** |

So for the corridor the tree changes the Gorkha-repeat expected loss from USD 631.4 M to
USD 622.3 M and *narrows* the 90 % interval by 1 %. Do not read a corridor interval as including
GSIM uncertainty: at Rjb = 0, with these three branches, there is almost none to include. This is
§ 8 item 1 seen from another angle, and the fix is the same — an independent second model.

### Distances

`adapters/groundmotion/distances.py` derives `rjb`, `rrup`, `rx`, `ztor` and `rhypo` from a
`ScenarioRupture`. Sites and corners are projected into a local azimuthal-equidistant frame centred
on the rupture (distances from that centre are exact great-circle distances), and the metrics are
then computed **exactly** in that frame — 3-D point-to-triangle for `rrup`, 2-D point-to-polygon for
`rjb` — rather than read off a discretised mesh. A rupture with no corners is a point rupture:
`rjb` is the epicentral distance, `rrup` the hypocentral distance, `rx` zero. rupture does not
invent a fault plane from a magnitude.

Tested against analytic plane geometry: a point source, a vertical plane (Rjb = Rrup = |Rx| = the
offset), a 45-degree dipping plane over which the site sits (Rjb = 0, Rrup = offset/√2), and a
footwall site. Agreement to within 20 m at 8–30 km separations, which is the local frame's
projection error, not a tolerance chosen to make a test pass.

---

## 3. Exposure and its provenance

**serac owns this exposure; rupture reads it.** `SeracExposureSource` looks for the live export at
`$SERAC_EXPORT_DIR` (default `../serac`), at
`data/aoi/lhende-khola-trishuli/exposed_assets.geojson`. When that is absent it falls back to a
copy committed under `tests/fixtures/risk/exposure/`, cut from serac commit `7af421e0` with a
`provenance.json` recording the commit, the path, the digest and — loudly — that it is a fallback
only. Which of the two was used appears in `Provenance.source_url` and again in `Provenance.notes`,
so a portfolio can never quietly be built from a stale copy. Coordination is by file; nothing
imports serac.

`validate-risk` deliberately pins the committed fallback even when the live export is present, so
the gate's answer cannot depend on what happens to sit in a sibling directory.

### The corridor

14 features: 9 run-of-river hydropower plants (541.4 MW), 1 bridge, 1 border post, 3 settlements.

### Valuation

| | |
|---|---|
| Unit cost | **USD 2 806/kW, 2023 USD** — IRENA (2024), *Renewable power generation costs in 2023*, ISBN 978-92-9260-621-3, global weighted-average total installed cost of new hydropower |
| Corridor total | **USD 1 519 168 400** (arithmetic on the published figure; reproducible to the penny) |
| Interval | **±40 %, ASSUMED** — not a published dispersion. See ADR-0025 for why the published central value cannot carry a published interval here |
| Provenance tier | `ModelProvenance.ASSUMED`, `ConfidenceTier.LOW` |
| Assets with no cost basis | **5 of 14** (bridge, border post, 3 settlements) — carried at value zero, named in every report |

Sanity check worth recording: Upper Trishuli-1 (216 MW) prices at USD 606 M on this basis against
the USD 647 M total project cost widely reported for it. Close enough to suggest the basis is not
wildly wrong for this corridor; not a substitute for a Nepal-specific figure.

### Site conditions

The export carries no site condition. Every site is **assumed** Vs30 = 760 m/s (NEHRP B/C reference
rock), recorded in each asset's `attributes["vs30_basis"]` and in the portfolio's provenance notes.
Himalayan powerhouses are commonly founded on rock or thin alluvium, so this is not unreasonable,
but it certainly understates amplification at any soil site, and it is an assumption.

### GEM's Global Exposure Model, and why none of it is here

Full reasoning in **ADR-0039**. The brief asked for exposure from GEM's global model *where openly
licensed*. The licence was read and it fails.

| | |
|---|---|
| GEM Global **Exposure** Model (`github.com/gem/global_exposure_model`) | **CC BY-NC-SA 4.0** (read from `LICENSE.txt`, 2026-09-03) |
| GEM Global **Vulnerability** Model (`github.com/gem/global_vulnerability_model`) | **CC BY-NC-SA 4.0** (same) |
| rupture | Apache-2.0 |

CC BY-NC-SA is not an open licence under the Open Definition or the OSI: NonCommercial restricts a
field of use and ShareAlike would propagate to derived works. So **rupture redistributes none of
it** — no fixture, no slice, no derived table, and a unit test asserts the absence rather than
trusting the rule. `validate-risk` therefore does not exercise this adapter against real data.

What rupture does ship is the loader, because a consumer who has completed GEM's licence request
should not also have to write one. `GemExposureSource` reads a copy the consumer already holds, in
the OpenQuake exposure CSV format GEM distributes the disaggregated model in
(`id, lon, lat, taxonomy, number, structural, ...`); it never fetches and never caches, and the
portfolio's provenance carries GEM's licence and attribution. `fetch_summary` covers only the
*public* summary tables (`Exposure_Summary_Adm0/Adm1/Taxonomy.csv`), prints the licence before
writing, and writes outside the repository; those tables carry no coordinates, so they can be
reported but cannot become a portfolio, and `read_summary` refuses to pretend otherwise.

**The second half of the requirement is declined and stays open.** Pairing GEM exposure with a
building-class fragility set needs an openly licensed one. GEM's own vulnerability database is
CC BY-NC-SA; HAZUS 5.1's general building-stock tables are openly licensed but are not among the
blocks committed under `tests/fixtures/risk/vulnerability/hazus51/`, and rupture will not transcribe
them from memory. A GEM portfolio imported today is therefore reported **wholly unmodelled**, asset
by asset, with the reason — the same treatment the corridor's bridge, border post and settlements
already get. Committing the HAZUS building tables the way the six existing tables were committed is
the work that unblocks it.

### User-supplied portfolios

`GeoParquetExposureSource` imports GeoParquet or CSV validated against **`exposure-import.v0`**
(`risk/exposure_schema.py`). One row per asset: `id`, `taxonomy`, `value` required; location from a
GeoParquet point `geometry` or explicit `longitude`/`latitude`; optional `occupants`, `vs30`,
`component`, `parent_id`, `source_refs`. A line, polygon or multi-part geometry is refused rather
than reduced to a centroid behind the user's back, and validation reports every bad row, not the
first.

> **Registered.** The schema now lives in `rupture.domain.exposure_import` (a published contract
> is domain, and `domain/contracts.py` may not import from `rupture.risk` without breaking the
> hexagonal rule) and is exported as `contracts/exposure-import.v0.json`, policed by
> `schema-check`. `rupture.risk.exposure_schema` re-exports it for the adapters.

---

## 4. Vulnerability: every source, and every assumption

Full reasoning in **ADR-0024**. Summary:

| Component | Value share | Fragility | Consequence |
|---|---|---|---|
| Intake | 15 % (assumed) | **ASSUMED** 0.20/0.40/0.70/1.10 g, β 0.60 | **ASSUMED** |
| Headrace tunnel | 30 % (assumed) | HAZUS 5.1 Table 7-9, bored/drilled (Slight and Moderate only) | HAZUS Table 11-10, tunnel lining |
| Penstock | 10 % (assumed) | **ASSUMED** 0.15/0.30/0.55/0.90 g, β 0.65 | **ASSUMED** |
| Powerhouse | 38 % (assumed) | HAZUS Table 8-31 (<100 MW) / 8-32 (≥100 MW), unanchored | HAZUS Table 11-18, generation plants |
| Switchyard | 7 % (assumed) | HAZUS Table 8-29, medium-voltage substation, unanchored | HAZUS Table 11-18, substations |

Source: FEMA, *HAZUS 5.1 Earthquake Model Technical Manual* (July 2022), a US Government work.
HAZUS's own stated default (unanchored components) is used. The verbatim table blocks are committed
under `tests/fixtures/risk/vulnerability/hazus51/` with a `provenance.json` carrying the PDF's
digest, and `tests/unit/risk/test_vulnerability.py` parses them and asserts that every coded median,
dispersion and damage ratio matches — so a transcription slip fails the build rather than moving a
loss figure.

Three things carried rather than smoothed over:

- HAZUS's shaking fragility for tunnels reaches only Slight and Moderate; heavier tunnel damage is
  driven by permanent ground deformation, which is C3's input. A headrace tunnel therefore cannot be
  destroyed by shaking alone in this model.
- HAZUS Table 11-18's range column for Substations/Moderate (0.15–0.40) does not contain its own
  best estimate (0.11). rupture uses the published best estimate and records the inconsistency.
- HAZUS is a United States model applied to Nepali assets. Its component inventory and construction
  practice are not Nepal's. Every model built from these curves says so in its `notes`.

**Assumption-dependent share.** For the Gorkha-repeat scenario, **27 %** of the best-estimate loss
comes from components whose fragility or consequence function is assumed. The CLI prints it and the
gate checks it exists.

**Asset classes with no model** — bridge, border post, settlement — are named as not modelled with
the reason, in the CLI output and in the gate findings. Five of fourteen, every time.

---

## 5. Scenarios

| Scenario | Magnitude | Geometry | `hypothetical` |
|---|---|---|---|
| `gorkha-2015-repeat` | M 7.82 (as inverted) | 144 × 126 km, Ztor 7.7 km, strike 293°, dip 7°, rake 108° | **False** |
| `mht-m8-hypothetical` | M 8.49 (**computed**) | 250 × 164 km, Ztor 0 (surface rupture at the MFT), strike 293°, dip 7° | **True** |

**Gorkha** is derived from the USGS NEIC finite-fault inversion for `us20002926`, committed as an
FSP file with its provenance. The inversion grid is 193 × 168 km — larger than the area that
slipped — so rupture takes the smallest rectangle in fault coordinates holding 90 % of the slip
(equivalently 90 % of the moment on a uniform grid). Ztor 7.7 km is consistent with the published
account that the rupture did not break the surface.

Threshold sensitivity, for this corridor:

| Moment fraction | Length | Width | Ztor | Rrup range at the corridor | Median PGA (BSSA14) |
|---|---|---|---|---|---|
| 0.95 | 161 km | 133 km | 6.9 km | 14.1–20.2 km | 0.492 g |
| **0.90 (default)** | **144 km** | **126 km** | **7.7 km** | **14.1–20.1 km** | **0.492 g** |
| 0.80 | 135 km | 105 km | 10.3 km | 14.1–20.1 km | 0.492 g |
| 0.70 | 110 km | 105 km | 10.3 km | 14.1–20.1 km | 0.492 g |

The threshold makes almost no difference here, for a reason worth stating plainly: the corridor sits
directly *above* the shallowly dipping thrust, so Rjb is zero at every site under every threshold,
and BSSA14 depends only on Rjb. Which brings us to the most important limitation in this document —
see §8.

**MHT** takes its extent from published constraints on the great central-Himalayan earthquakes
(Sapkota et al. 2013; Bollinger et al. 2014; Stevens & Avouac 2016) and **computes** the magnitude
from the resulting area and a 5 m average slip via Hanks & Kanamori (1979), so geometry and
magnitude cannot disagree and no unverified scaling relation was adopted.

**Stochastic event sets.** These are now built, not merely hooked: `risk.event_set` samples whole
synthetic catalogues from a promoted F1 `ForecastGrid` and each sampled event becomes a
`ScenarioRupture` through `scenarios.from_stochastic_event`. An event with a finite-fault geometry
keeps it; an event without one becomes a **point rupture** and its notes say exactly that,
including that the resulting loss is a lower estimate. § 6b has the numbers and ADR-0036 has the
sampling rule.

---

## 6. Results actually computed

`native_gsim`, PGA, 2 000 realisations, truncation 3.0, seed 20260903, Vs30 760 m/s assumed,
committed exposure fixture, 90 % intervals. Portfolio value USD 1 519.2 M.

| Scenario | GSIM | Median PGA | Expected loss (USD M) | 90 % interval | Assumed share |
|---|---|---|---|---|---|
| Gorkha 2015 repeat | `BooreEtAl2014` | 0.490–0.506 g | **631.4** | 303.8 – 962.5 | 27 % |
| Gorkha 2015 repeat | `AbrahamsonEtAl2015SInter` | 0.444–0.546 g | **620.3** | 249.0 – 994.7 | 27 % |
| MHT M8.5 hypothetical | `BooreEtAl2014` | 0.532–0.549 g | **670.2** | 336.9 – 991.7 | 27 % |
| MHT M8.5 hypothetical | `AbrahamsonEtAl2015SInter` | 0.703–0.859 g | **813.9** | 430.7 – 1 114.5 | 28 % |

Per asset, Gorkha repeat with BSSA14:

| Asset | Capacity | Expected loss (USD M) | 90 % interval |
|---|---|---|---|
| upper-trishuli-1 | 216 MW | 244.9 | 62.2 – 432.7 |
| rasuwagadhi-hep | 111 MW | 125.1 | 30.2 – 224.3 |
| upper-trishuli-3a | 60 MW | 72.9 | 21.1 – 123.7 |
| sanjen-hep | 42.5 MW | 51.6 | 14.5 – 86.7 |
| upper-trishuli-3b | 37 MW | 45.0 | 13.2 – 75.3 |
| trishuli-hep | 24 MW | 29.4 | 8.2 – 49.3 |
| chilime-hep | 22 MW | 27.2 | 8.3 – 45.1 |
| sanjen-upper-hep | 14.8 MW | 17.9 | 5.3 – 30.0 |
| devighat-hep | 14.1 MW | 17.3 | 4.9 – 29.0 |

Avoided loss, Gorkha repeat with BSSA14, baseline USD 631.4 M:

| Intervention | Avoided (USD M) | 90 % interval | Effect model |
|---|---|---|---|
| `retrofit-all` (structural_retrofit) | 44.8 | 31.3 – 54.6 | HAZUS anchored/unanchored pair — **published** |
| `automated-shutdown` (15 %) | 52.6 | 28.7 – 75.3 | **assumed** fraction of the powerhouse component |
| `no-build-upper-trishuli-1` (land_use_exclusion) | 244.9 | 62.2 – 432.7 | definitional |
| `xol-400-xs-200` (insurance_layer) | 331.4 | 103.8 – 400.0 | financial, not physical |

Two of these deserve their explanation rather than being left to look like model quality. The
**retrofit** avoids only 7 % because at a median PGA near 0.5 g both the anchored and the unanchored
HAZUS curves put most plants in extensive or complete damage — anchoring buys a great deal at 0.2 g
and little at 0.5 g. The **exclusion** avoids 39 % because Upper Trishuli-1 is 40 % of the
portfolio; that is a statement about concentration, not about land-use policy.

### The shutdown is worth nothing for the rupture that matters most

`automated_shutdown` now depends on whether an alert can reach the plant before the shaking does
(**ADR-0038**), not on a flat fraction applied everywhere. The same portfolio, the same 15 %
assumed fraction, the same 2 000 realisations, two ruptures:

| Scenario | Hypocentral distance to the 14 sites | Warning time | Avoided (USD M) |
|---|---|---|---|
| Gorkha 2015 repeat | 56 – 75 km | **+1 to +6 s** at all 14 | **52.6** |
| MHT M8.5 hypothetical | 29 – 41 km, 10 km deep | **−3 to −7 s** at all 14 | **0.0** |

The corridor sits on top of the Main Himalayan Thrust. For the rupture it most needs to worry
about, the S wave arrives before a source-side alert plus the machinery's own stopping time could
have acted, so the measure avoids exactly nothing and the model now says so. All four timing
parameters (`trigger_g` 0.05 g, `s_wave_km_s` 3.5, `latency_s` 5, `stopping_time_s` 10) are
**assumed**, none is a published figure, and all four are request parameters: a consumer with a
faster plant and a faster alert (1 s and 1 s) puts all 14 sites back in time, and the avoided
figure returns.

---

## 6b. Expected annual loss, from a real ETAS forecast

**This is the figure an underwriter prices against**, and it exists because the forecasting half of
rupture feeds the loss half: `risk.event_set` samples synthetic catalogues from a promoted F1
`ForecastGrid` and `risk.event_based` reduces them to an annual number and to exceedance curves
(**ADR-0036**).

The run below is real, not illustrative. The catalogue was built from ComCat, ISC and GCMT for
`nepal-himalaya` (1976 → 2026-08-01), the ETAS baseline was fitted with a hard cutoff at
2022-01-01 (772 events above Mc 4.4, converged, branching ratio 0.69), and the grid was issued at
2026-08-01 over a 1-year horizon: **2 079 cells × 43 magnitude bins, 8.69 expected events at
M ≥ 4.7 per year**.

| | |
|---|---|
| Event set | 1 000 synthetic catalogue-years, M ≥ 5.0, seed 20260903 |
| Events sampled | **4 216**, summed rate **4.216 /yr**, largest sampled magnitude M 8.48 |
| Ground motion | `BooreEtAl2014` PGA, `native_gsim`, 40 realisations per event |
| Years with no modelled loss | 1.7 % |
| Assumption-dependent share | 20 % |
| **Expected annual loss** | **USD 4 416 057 /yr** [3 450 701 – 5 471 865] = **0.291 % of portfolio value per year** |

The interval on the AAL is a percentile bootstrap of the mean over the 1 000 catalogue-years — it
is *how well the event set pins the number down*, **not** the spread of annual loss. The spread of
annual loss is the exceedance curve, and confusing the two is the standard way an annual-loss
figure misleads. The `basis` string on the figure says this, and a test asserts the sentence is
there.

| Return period | Aggregate exceedance (annual total, USD M) | Occurrence exceedance (single event, USD M) |
|---|---|---|
| 2 yr | 0.0 | 0.0 |
| 5 yr | 0.7 | 0.9 |
| 10 yr | 5.7 | 6.2 |
| 20 yr | 19.4 | 19.6 |
| 50 yr | 43.3 | 52.7 |
| 100 yr | 82.3 | 92.9 |
| 200 yr | 116.6 | 152.2 |
| 500 yr | 163.8 | 245.1 |
| **1 000 yr** | **177.1** | **326.7** |

Nothing beyond 1 000 years is reported, because 1 000 catalogue-years is what this event set
resolves; extrapolating would be reading a rare loss off the single worst sampled year.

**Read the caveats before quoting the number.** In roughly descending order of how much they move
it:

1. **Every sampled event is a point rupture at 15 km depth.** rupture does not manufacture a fault
   plane from a magnitude (ADR-0025). This is why the 1 000-year aggregate loss (USD 177 M) is well
   *below* the Gorkha-repeat scenario loss (USD 631 M) even though the event set contains an
   M 8.48: a point source 15 km down is far weaker at the site than a finite thrust plane the
   corridor sits on. The scenario figures and this curve are **not** directly comparable, and the
   annual figure is a lower estimate because of it.
2. **The ETAS grid's rate is treated as constant over the year.** A time-dependent forecast decays;
   annualising it says "if this rate persisted". Read the annual figure as a rate-equivalent, not
   as a statement about the coming year.
3. **Occurrence within a catalogue is Poisson**, which reproduces the grid's expected counts
   exactly and understates the variance of a clustered process — so the tail of the aggregate curve
   is *tighter* than the underlying process.
4. **Events below M 5.0 are not sampled**, which makes the figure a lower estimate by an amount a
   caller can bound by lowering the threshold and re-running.
5. Everything in § 8 that applies to a scenario loss applies here too: five of fourteen assets
   unpriced, cascade components zero, no spatial correlation, assumed value shares.

Magnitudes within a bin follow a Gutenberg-Richter density using the region's **fitted** b-value
(1.138, Aki 1965 MLE from the region's own Mc estimate), not an assumed one.

**Reproducing it needs network**, because `data/forecasts/` is DVC-tracked and empty in a fresh
clone:

```bash
uv run rupture catalog build --region nepal-himalaya --from 1976-01-01 --to 2026-08-01
uv run rupture forecast fit --model etas --region nepal-himalaya --cutoff 2022-01-01T00:00:00Z
uv run rupture forecast issue --model etas --region nepal-himalaya --horizon 1y \
    --issue 2026-08-01T00:00:00Z
```

The **offline** tests run instead on a committed **real slice** of that same grid — the 156 cells
around the corridor, counts carried through unchanged, under
`tests/fixtures/risk/forecast/` with a `provenance.json` naming the parent grid, its fit cutoff and
its parameter snapshot hash. A slice's rate is a fraction of the region's, so an annual loss from
it is not the corridor's annual loss; it proves the F1→F2 join runs offline on real forecast
output.

**Avoided annual loss** is the catalogue-by-catalogue difference against the same events and the
same ground-motion realisations (ADR-0025's shared-realisation rule, carried into the event-based
path). One finding worth recording: over an event set full of small earthquakes, the retrofit is
*not* uniformly beneficial. HAZUS's anchored generation-facility curve for plants under 100 MW is
fractionally worse than its unanchored counterpart between about 0.006 g and 0.051 g, by at most
0.02 % of plant value, so a synthetic year containing only very small events comes out marginally
worse with the retrofit in place. That is a property of the published pair, not a defect; a test
pins the crossing, the response reports the share of catalogues affected and the worst shortfall,
and `MoneyRange` cannot be negative so the note says what the truncation at zero hid (ADR-0038).

---

## 7. How to run it

`rupture risk ...` and `rupture validate risk` are **registered and working**: `cli.py` carries
`app.add_typer(risk.app, name="risk")` and `"risk"` is in the `GATES` tuple of
`validation/registry.py`. (An earlier draft of this section said otherwise and was wrong; the
`python -m rupture.commands.risk ...` form still works and does the same thing.)

```bash
uv sync

# the gate: offline, no Docker, no network
make validate-risk          # or: uv run rupture validate risk

# a scenario: the loss and the avoided loss, with intervals
uv run rupture risk run --scenario gorkha-2015-repeat --realisations 2000
uv run rupture risk run --scenario mht-m8-hypothetical \
    --gsim AbrahamsonEtAl2015SInter --allow-tectonic-mismatch
uv run rupture risk run --portfolio my_portfolio.parquet \
    --scenario gorkha-2015-repeat --interventions measures.json --json

# a forecast: expected ANNUAL loss from a stochastic event set (§ 6b)
# needs the grid to have been issued first; data/forecasts/ is DVC-tracked and empty in a clone
uv run rupture risk run --forecast etas-mizrahi-nepal-himalaya-20260801T000000Z-365d

uv run rupture risk scenarios
uv run rupture risk gsims

# use the sibling's live export instead of the committed copy
SERAC_EXPORT_DIR=../serac uv run rupture risk run --scenario gorkha-2015-repeat

# the container paths, scenario and event_based (amd64 only; skip locally with a printed reason)
make test-integration
```

> **For the architect**, three requests, none of them blocking:
>
> 1. `rupture risk run --forecast` prints `scenario: <id>` and a per-event framing for what is now
>    an **annual** figure. `commands/risk.py` should label the forecast path as such and print the
>    exceedance curve, which `avoided_loss.respond_with_detail` returns alongside the response.
> 2. The event-set knobs (`n_catalogues`, `min_magnitude`, `catalogue_duration_years`,
>    `n_gm_realisations`) are function parameters with stated defaults and are not exposed as CLI
>    options; the CLI therefore always runs 500 catalogue-years.
> 3. `avoided-loss.v1` has no field for an expected-annual-loss curve. The AAL is returned in
>    `baseline_total` with a `basis` that says which window it covers, and the exceedance curve is
>    returned out of band by `respond_with_detail`. A **v1.1** adding
>    `annual_expected_loss: MoneyRange | None` and `exceedance_curve` (additive, per ADR-0013)
>    would let a consumer read it from the contract. Likewise `ground-motion-field.v0` has no field
>    for a GSIM logic-tree id, so a mixed field records the tree in `notes` and in its provenance.
>
> And four stale claims outside this document that say the opposite of what the code does, left
> here rather than edited from a parallel worktree:
>
> - the module docstring of `src/rupture/commands/risk.py` still says the sub-application "is not
>   wired into `cli.py` yet". It is (`app.add_typer(risk.app, name="risk")`).
> - `mk/risk.mk`'s header comment says the same, and the recipe invokes
>   `python -m rupture.validation.risk` rather than the now-available `$(RUN) rupture validate risk`.
> - the `Makefile` help text for `underwriting-check` says it "exits non-zero: not implemented
>   (Prompt 2)". It exits **zero** and prints a loss and an avoided loss with intervals.
> - `RELEASE_STATUS.md` records forecast and long-term-hazard triggers as not implemented. The
>   forecast trigger is implemented (§ 6b); the hazard trigger is still not, for the reason in
>   § 8 item 10.

### Deployment

The service is a FastAPI app: `rupture.risk.service:app`, with `create_app()` as a factory.

```bash
RUPTURE_RISK_API_KEYS=key1,key2 \
  uv run uvicorn rupture.risk.service:app --host 0.0.0.0 --port 8000
```

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` | none | liveness only; says nothing about whether a calculation would succeed |
| `GET /v1/scenarios` | `X-API-Key` | the scenarios a request may name |
| `POST /v1/avoided-loss` | `X-API-Key` | `AvoidedLossRequestV1` → `AvoidedLossResponseV1` |

| Variable | Meaning |
|---|---|
| `RUPTURE_RISK_API_KEYS` | comma-separated keys. **With none set the service refuses every request** (503) rather than running open |
| `RUPTURE_REPO_ROOT` | where the committed scenario and exposure fixtures live |
| `SERAC_EXPORT_DIR` | the sibling's checkout, when the live export should be used |

The security model is one API key header, compared in constant time, and nothing else: no user
model, no sessions, no rate limiting, no audit log. This is not a public-internet service.

**What the existing `infra/docker` image needs** (`infra/` is the hazard-engineer's; this is a
request, not a change): the image already installs the locked environment, so `uvicorn` and
`fastapi` are present as project dependencies. To serve the API it needs (a) `EXPOSE 8000` or the
equivalent port documentation, (b) the ability to pass `RUPTURE_RISK_API_KEYS` through, and (c) the
committed fixtures under `tests/fixtures/risk/` to be present in the image, or `RUPTURE_REPO_ROOT`
pointed at a mounted copy — a `--only-group main` build that excludes `tests/` will make every
scenario lookup fail. A job manifest for a batch loss run would want the same three.

---

## 8. Limitations

Read this section before quoting any number above.

1. **An Rjb-only GSIM cannot discriminate across this corridor.** The corridor sits directly above
   a shallowly dipping thrust, so Rjb is **zero at every site** for both scenarios. BSSA14 depends
   only on Rjb, so it gives every site the same median PGA and the spread in the table above comes
   only from Vs30 and sampling. The BC Hydro model, which uses Rrup, does discriminate
   (0.444–0.546 g for Gorkha). For the Main Himalayan Thrust, an Rrup-based model is the one that
   sees the geometry.
2. **BC Hydro is a subduction-interface model applied to a continental thrust.** The MHT is a
   collisional decollement, not a subduction interface. Using `AbrahamsonEtAl2015SInter` here is a
   deliberate sensitivity alternative, requires `strict_tectonic_region=False`, and is recorded on
   the resulting field's `notes`. It is not a claim that the MHT is a subduction zone.
3. **These numbers over-state Gorkha's observed shaking.** The single strong-motion station in the
   Kathmandu valley (KATNP) recorded about 0.16 g in the 2015 mainshock, and the event is widely
   reported as deficient in high-frequency radiation — observed PGA came in below active-crustal
   GMPE medians while long-period response exceeded them. The model here gives ~0.49 g on rock at
   Rjb = 0 and captures none of that. Treat the loss figures as what these GSIMs say, not as what a
   Gorkha repeat would do.
4. **27 % of the loss rests on assumed fragility functions** (intake, penstock) and **all of it on
   assumed component value shares**. ADR-0024.
5. **The valuation interval is assumed.** The central figure is IRENA's published global weighted
   average; the ±40 % band is a judgement (ADR-0025).
6. **Five of fourteen assets are unpriced and unmodelled.** The portfolio total is not the
   corridor's total exposure.
7. **No spatial correlation of intra-event residuals.** They are drawn independently per site, which
   is OpenQuake's default too, and it **narrows** the portfolio interval relative to a correlated
   field. The intervals above are therefore optimistic about how tight they are.
8. **Cascade components are still not modelled, and this pass did not change that.** Landslide,
   liquefaction and ice-rock avalanche appear in every decomposition as an explicit `0.0` with a
   note, so the zero cannot be read as "modelled and small". In a Himalayan gorge the landslide
   contribution is unlikely to be small. Wiring the C3 seam was considered and **declined** here
   for a specific reason: `GroundFailureField` (contract `ground-failure-field.v0`) gives a
   *probability of failure per cell*, not a permanent ground deformation, and HAZUS's permanent-
   ground-deformation fragility curves are defined on displacement in inches. The two do not join
   without either (a) the HAZUS PGD tables committed as fixtures the way Tables 7-9, 8-29, 8-31,
   8-32, 11-10 and 11-18 were, plus a sourced probability-to-displacement relation, or (b) an
   invented conditional damage ratio. (b) would be a fabricated model wearing a decomposition's
   clothes, so nothing was wired. The explicit zero and its note remain the honest report.
9. **Loss types.** Only `structural` is computed. Business interruption, contents and casualties are
   not, despite the enum carrying them.
10. **A long-term-hazard trigger is still not implemented.** A `TriggerKind.FORECAST` request is
    now answered (§ 6b, ADR-0036). `TriggerKind.HAZARD` returns `status = not_implemented` with a
    stub `MoneyRange` and a message naming what is missing: rupture ships the engine-side
    `event_based` job rendering and export parsing (ADR-0037) but **no long-term (F0) source model
    for the corridor**, so there is nothing to run it on. It never returns a guess.
11. **Only PGA is used.** The GSIMs support spectral acceleration and the code accepts `SA(T)`, but
    every fragility function shipped is defined on PGA, so no spectral loss calculation has been
    run.
12. **The container path is unverified on this machine.** §2.
13. **Vs30 is assumed everywhere.** §3.
14. **`ScenarioGroundMotionJob` cannot carry a site model**, so the engine adapter renders its own
    `job.ini` rather than reusing `job_builder.scenario_job_ini`. That duplication would disappear if
    the port gained a `site_model_file`; it is a port change and belongs to the architect. The
    event-based adapter renders its own `job.ini` for the same reason.
15. **The shipped GSIM logic tree is a lower bound on model uncertainty, not an estimate of it.**
    Its three branches are Q-region variants of one NGA-West2 model. A tree with independent models
    (Chiou & Youngs 2014, Campbell & Bozorgnia 2014, Abrahamson/Silva/Kamai 2014, Idriss 2014)
    would be far wider; rupture has verified none of them, so they are named on the tree as
    excluded rather than shipped. At Rjb = 0 the shipped tree changes the corridor's answer by
    about 1 %; at 200 km its branches span a factor of 2.7. § 2 and ADR-0037.
16. **An annual loss and a scenario loss are not comparable as they stand.** Every event of a
    sampled event set is a point rupture at 15 km depth, so the 1 000-year aggregate loss
    (USD 177 M) sits well below the Gorkha-repeat scenario loss (USD 631 M) even though the set
    contains an M 8.48. Fixing it needs a magnitude-area scaling relation and a fault-attachment
    rule, neither of which this pass verified. § 6b and ADR-0036.
17. **The event set's occurrence process is Poisson, not clustered.** It reproduces an ETAS grid's
    expected counts exactly and understates the variance of a clustered process, so the tail of the
    aggregate exceedance curve is tighter than the underlying process. Drawing from
    `etas.simulation` instead of from binned expected counts would fix it; it needs the forecasting
    adapter to expose simulated catalogues, which it does not today.
18. **rupture ships no building-class fragility**, so GEM exposure (and any general portfolio)
    imports but prices at zero, asset by asset, with the reason. The blocking item is a sourced
    fragility set, not the exposure. § 3 and ADR-0039.
19. **The shutdown's timing parameters are four more assumptions.** Trip threshold, S-wave speed,
    alert latency and stopping time are all stated defaults, none published, all overridable per
    request. The model is a source-side regional alert, not a per-plant on-site sensor; an on-site
    trigger would have a shorter geometry and would look more favourable, so the reported avoided
    loss is a lower estimate. ADR-0038.

---

## 9. What the gate checks

`make validate-risk` (`validation/risk.py`), offline, no Docker:

1. every committed reference table still matches the sha256 its `provenance.json` records — GSIM
   vectors, coefficient tables and the HAZUS blocks;
2. every registered GSIM reproduces OpenQuake's expected values within its stated tolerance;
3. `native_gsim` produces a scenario field for the Gorkha-repeat rupture at the corridor's sites,
   finite and positive throughout;
4. the Nepal portfolio run completes, and the portfolio's provenance carries a digest, a source URL
   and its valuation basis;
5. loss intervals are finite, ordered and inside their `best`, with a stated basis, for the total
   and for every asset;
6. the avoided-loss contract round-trips: a request with all four implemented measures is answered,
   and `{request, response}` validates against `contracts/avoided-loss.v1.json`;
7. no avoided figure is a stub, and the response carries provenance.

It pins the committed exposure fixture, so pointing `SERAC_EXPORT_DIR` elsewhere cannot change its
answer. A test corrupts a fixture digest in a copied tree and asserts the gate fails.

Check 2 now covers **five** GSIMs, the two logic-tree branches included (§ 2).

**What the gate does not yet cover, and a request to the gate's owner.** The annual-loss path is
exercised by the offline unit tests (`tests/unit/risk/test_event_set.py`,
`test_event_based.py`) against the committed real ForecastGrid slice, but not by `validate-risk`
itself. Three checks would close that, all offline and all fast on the committed slice:

1. sample an event set from `tests/fixtures/risk/forecast/trishuli-corridor-slice.json` and assert
   the summed occurrence rate matches the slice's own rate within Poisson error;
2. run `event_based.run_event_based` over it and assert the AAL is finite and positive, that its
   interval is ordered, and that no exceedance point exceeds the resolvable return period;
3. assert the slice still matches the sha256 its `provenance.json` records (the same check
   `_check_fixture_digests` already does for the GSIM and HAZUS fixtures — the forecast directory
   just needs adding to its list).
