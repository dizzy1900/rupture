# RISK — ground motion to loss to avoided loss (F2)

rupture does not predict earthquakes. This layer answers a different question, and one that is
useful to an underwriter whether or not any forecast model has skill: **for a given rupture, what
does a portfolio lose, and what does an intervention avoid?**

Everything below was run in this worktree. Where something did not run, it says so and why.

---

## 1. Architecture

```
serac export ──┐
               ├─▶ ExposurePortfolio ──┐
user import  ──┘                       │
                                       ├─▶ risk.loss ──▶ MoneyRange (+ interval)
ScenarioRupture ──▶ GroundMotionEngine ┤                       │
   (Gorkha / MHT / stochastic)         │                       ▼
                                       └─▶ VulnerabilityModel  risk.avoided_loss
                                            (HAZUS + assumed)        │
                                                                     ▼
                                          AvoidedLossResponseV1 ──▶ CLI / FastAPI
```

| Layer | Module | Port |
|---|---|---|
| Exposure | `adapters/exposure/{serac_export,geoparquet_import}.py` | `ports/exposure.py` |
| Valuation | `adapters/exposure/valuation.py` | — |
| Ground motion | `adapters/groundmotion/{native,openquake_scenario}.py` | `ports/ground_motion.py` |
| Vulnerability | `adapters/vulnerability/{hazus,hydropower,library}.py` | `ports/vulnerability.py` |
| Damage / loss | `risk/{damage,loss}.py` | — |
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

**Stochastic event sets.** `scenarios.from_stochastic_event` is the hook the forecasting layer plugs
an ETAS catalogue into. An event with a finite-fault geometry keeps it; an event without one becomes
a point rupture and its notes say exactly that, including that the resulting loss is a lower
estimate. The event sets themselves are not in C2.

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

---

## 7. How to run it

```bash
uv sync

# the gate: offline, no Docker, no network
make validate-risk

# the loss and the avoided loss, with intervals
uv run python -m rupture.commands.risk run --scenario gorkha-2015-repeat --realisations 2000
uv run python -m rupture.commands.risk run --scenario mht-m8-hypothetical \
    --gsim AbrahamsonEtAl2015SInter --allow-tectonic-mismatch
uv run python -m rupture.commands.risk run --portfolio my_portfolio.parquet \
    --scenario gorkha-2015-repeat --interventions measures.json --json

uv run python -m rupture.commands.risk scenarios
uv run python -m rupture.commands.risk gsims

# use the sibling's live export instead of the committed copy
SERAC_EXPORT_DIR=../serac uv run python -m rupture.commands.risk run --scenario gorkha-2015-repeat

# the container path (amd64 only; skips locally with a printed reason)
make test-integration
```

> **For the architect:** `rupture risk ...` and `rupture validate risk` are the conventional entry
> points and both are two lines away. `src/rupture/cli.py` needs
> `app.add_typer(risk.app, name="risk")` (and `risk` in the `from rupture.commands import ...`
> line), and `src/rupture/validation/registry.py` needs `"risk"` in `GATES`. The gate module is
> already the conventional shape — `validation/risk.py` exposing `run(repo_root) -> GateResult` —
> so nothing else changes. Until then `mk/risk.mk` invokes it as
> `python -m rupture.validation.risk`, which behaves identically.

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
8. **Cascade components are not modelled.** Landslide, liquefaction and ice-rock avalanche appear in
   every decomposition as an explicit `0.0` with a note, so the zero cannot be read as "modelled and
   small". This is the seam C3 fills, and in a Himalayan gorge the landslide contribution is
   unlikely to be small.
9. **Loss types.** Only `structural` is computed. Business interruption, contents and casualties are
   not, despite the enum carrying them.
10. **Forecast and long-term-hazard triggers are not implemented.** A `TriggerKind.FORECAST` or
    `HAZARD` request returns `status = not_implemented` with a stub `MoneyRange` and a message
    saying what is missing. It never returns a guess.
11. **Only PGA is used.** The GSIMs support spectral acceleration and the code accepts `SA(T)`, but
    every fragility function shipped is defined on PGA, so no spectral loss calculation has been
    run.
12. **The container path is unverified on this machine.** §2.
13. **Vs30 is assumed everywhere.** §3.
14. **`ScenarioGroundMotionJob` cannot carry a site model**, so the engine adapter renders its own
    `job.ini` rather than reusing `job_builder.scenario_job_ini`. That duplication would disappear if
    the port gained a `site_model_file`; it is a port change and belongs to the architect.

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
