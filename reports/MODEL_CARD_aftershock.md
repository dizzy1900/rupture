# Model card — operational aftershock forecast service (rupture C4)

rupture does not predict earthquakes.

| | |
|---|---|
| **Component** | C4, operational aftershock forecasts (layer F1) |
| **Version** | 0 (Prompt 2) |
| **Date** | 2026-09-03 |
| **Model** | `etas-mizrahi` — the `etas` package of Mizrahi et al. at pinned commit `097f08b` (ADR-0009), fitted per aftershock zone with a moving cutoff |
| **Code** | `src/rupture/services/aftershock/` |
| **Design record** | ADR-0028 |
| **Documentation** | `docs/AFTERSHOCK.md` |
| **Validation** | `reports/aftershock/gorkha.md`, `reports/aftershock/kahramanmaras.md` |
| **Gate** | `make validate-aftershock` (offline, about 60 s) |
| **Licence of inputs** | ComCat, public domain (USGS) |

---

## What it does

Given a mainshock — a ComCat event id, or explicit time, latitude, longitude, depth and magnitude
— and a catalogue, it issues an `AftershockForecast`:

- the **expected number** of further events of magnitude at least *m* over 1, 7 or 30 days inside
  the aftershock zone, for the ladder *M*−3, *M*−2, *M*−1, *M*;
- the **probability that at least one occurs**, as `P = 1 - exp(-lambda)`;
- the **gridded `ForecastGrid`** of expected counts per cell per magnitude bin that those numbers
  summarise, which is where any location-dependent use must go.

Served as `POST /aftershock/forecast` (API key in `X-API-Key`) and as
`rupture aftershock forecast`.

## Out of scope

- **Forecasting individual earthquakes deterministically.** Nothing here states, or supports
  stating, that a particular earthquake happens, when, where, or how large. Every output is a
  rate over a population of possible events, conditioned on the sequence observed so far.
- Earthquake warning of any kind. There is no real-time feed, no seismic streaming, no alerting.
- Ground motion, shaking intensity, damage or loss. Those are F2 (`docs/HAZARD.md`, the
  avoided-loss contract).
- Foreshock discrimination: the service does not assess whether an event is a foreshock.
- Any statement about the parent region as a whole. The forecast is for one circle around one
  mainshock.

## What an operator can act on

An aftershock forecast supports decisions that are **rate-shaped and reversible**:

- staffing and shift planning for response teams over the coming days, sized to an expected count
  rather than to a single scenario;
- sequencing of building inspections and re-entry triage, using the fact that elevated rates decay
  and the 1-day / 7-day / 30-day ratios say roughly how fast;
- deciding how long to keep a temporary measure (a closed road, a propped structure, a suspended
  crane operation) in place;
- communicating a numeric probability of a further large event instead of a qualitative one,
  **with its uncertainty and its validated bias stated alongside** (see "Known bias" below);
- spatial prioritisation from the gridded forecast, where the rate is concentrated.

It does **not** support life-safety decisions — evacuation, all-clear, occupancy — and must not be
used for them. It is validated on two sequences and is biased low in the first day.

## Inputs and preprocessing

- **Catalogue**: byte-exact ComCat FDSN GeoJSON slices with recorded provenance and sha256
  (`tests/fixtures/aftershock/provenance.json`), or a built catalogue directory. Magnitudes are
  homogenised to Mw by `rupture.pipelines.magnitudes.preferred_mw` under the STRICT policy:
  moment magnitudes pass through, `mb`/`Ms` convert with Scordilis (2006) inside its validity
  ranges, and every other scale gets `mw = None` and is filtered out (not deleted).
- **Sequence window**: circle of radius `max(20 km, 1.5 x 10^(-2.44 + 0.59 M))` km about the
  epicentre, from the mainshock time on — Wells & Coppersmith (1994) subsurface rupture length,
  218 km for M7.8. Justification and alternatives in `docs/AFTERSHOCK.md` § 1 and ADR-0028.
- **Completeness, thresholds, binning, depth range**: inherited from the published parent region,
  never invented per sequence.

## Method

1. Build the aftershock zone as a `Region`.
2. Fit `MizrahiETAS` on every event in the zone with `origin_time < cutoff`, where the cutoff
   follows the refit schedule **+1, 3, 6, 12 h then daily to +30 d**. The training slice is a
   decade of pre-mainshock seismicity plus the sequence to date, so the parameters start as the
   zone's long-run parameters and become sequence-specific as the sequence grows.
3. `beta` is **fixed** to the parent region's published long-run b (1.138 Nepal, 1.026 Türkiye),
   and simulated magnitudes are capped at `Region.magnitude_max = 8.95`. Fitting b on the sequence
   gave b = 0.76 and a supercritical branching ratio of 1.07 for Kahramanmaraş at +1 d.
4. Issue a `ForecastGrid` from the stored fit, conditioned on the history strictly before the
   issue time (ADR-0018): triggered component = mean of 100 stochastic continuations, background
   and magnitude distribution analytic.
5. Summarise: `lambda` = grid mass at or above each threshold; `P = 1 - exp(-lambda)`.

## Assumptions, stated

1. **Poisson.** `P = 1 - exp(-lambda)` is exact only for a Poisson process. ETAS clusters, so the
   count is over-dispersed and this formula **over-states** P(at least one) whenever `lambda` is
   not small. At small `lambda` — the *M*−1 and *M* rungs — the two agree to first order.
2. **Fixed sequence window.** One radius per magnitude, chosen in advance, ignoring rupture
   geometry and directivity.
3. **Fixed b**, from the region's long-run catalogue rather than the sequence.
4. **Fixed Mc**, the region's long-run value. Short-term aftershock incompleteness is real and is
   not modelled, so both the training slice and the observed counts are incomplete after a large
   mainshock.
5. **Two-dimensional.** Depth enters only as the region's depth filter.
6. **ETAS is the process.** No fault geometry, no static or dynamic stress transfer, no
   afterslip.

## Evaluation

Pseudo-prospective on two real sequences, issued at +1 h, +1 d and +7 d, scored over 1-, 7- and
30-day horizons against the windows that closed inside the catalogue's coverage. Gridded forecasts
scored with `PyCSEPEvaluator` (N/M/S/L/CL); ladder rungs scored with a direct Poisson count check.
Leakage is refused, not filtered, and a negative test injects a post-issue event and asserts the
refusal.

**Counts, expected against observed (gridded total above the region's target threshold):**

| sequence | +1 h / 1 d | +1 h / 7 d | +1 d / 7 d | +7 d / 1 d | +7 d / 7 d | +7 d / 30 d |
|---|---|---|---|---|---|---|
| Gorkha (M ≥ 4.7) | 3.37 vs 43 | 3.77 vs 57 | 4.30 vs 15 | 1.27 vs 0 | 3.44 vs 2 | 4.92 vs 53 |
| Kahramanmaraş (M ≥ 4.6) | 13.6 vs 166 | 26.2 vs 268 | 29.8 vs 109 | 4.35 vs 3 | 25.8 vs 17 | 45.0 vs 53 |

Every N-test at +1 h and +1 d **fails**. The +7 d N-tests pass except the Gorkha 30-day window
(which contains the M7.3 of 12 May).

**The two events the forecasts are judged on:**

| | forecast | outcome |
|---|---|---|
| Kahramanmaraş M7.5 doublet, +9 h 07 m | issued at +1 h: P(M ≥ 6.8 within 1 d) = **7.2 %** (lambda 0.075) | occurred; consistent with the Poisson check |
| Gorkha M7.3, +17 d | every 30-day window: P(M ≥ 6.8) ≈ **2 %** (lambda 0.016–0.021) | occurred; flagged inconsistent at alpha = 0.05 in all three |

Full tables, including every rung and every CSEP test, in `reports/aftershock/`.

## Known bias

**The service under-forecasts the first 24 hours by a factor of roughly 3 to 12.** This is
structural: in the first hours the ETAS fit is dominated by a decade of mostly isolated background
seismicity in the zone, so the estimated aftershock productivity is that of a quiet region.
Operational practice solves this with generic parameters estimated across many sequences
(Reasenberg & Jones 1989; van der Elst & Page 2018) and updated towards the sequence; rupture has
no multi-sequence parameter set and this is the largest known gap. Short-term aftershock
incompleteness pushes the same way, and the Gorkha +1 h and +1 d fits sit on the Omori bound
`p = 2.0`, decaying the triggered rate away almost immediately.

A secondary artefact: `mb` → Mw conversion via Scordilis (2006) puts observed magnitudes on a
0.085-spaced lattice, so the *M*−3 rung of the ladder (M4.8) can disagree sharply with the gridded
N-test at M4.6 in a catalogue dominated by converted `mb`. See `docs/AFTERSHOCK.md` § 4.3.

## Fairness, harm and misuse

The output is a geophysical rate, not a judgement about people, and carries no protected
attributes. The realistic harms are misuse:

- **Over-reading a small probability as an assurance.** Both sequences delivered an event the
  forecast gave a few per cent to. The card states the direction of the bias so a reader cannot
  take a low number as safety.
- **Over-reading a high count as a specific event.** The zone-wide expected count says nothing
  about any one earthquake.
- **Use for evacuation or all-clear decisions.** Out of scope, stated in `docs/AFTERSHOCK.md` § 6.
- **Quoting the gate's numbers.** `make validate-aftershock` runs at 0.2 degrees with 5
  stochastic continuations to fit its time budget; its expected counts can differ from the
  published ones by a factor of several and are not the numbers to cite. The published validation
  is `reports/aftershock/`.

## Maintenance and reproducibility

- Catalogue slices: `uv run python -m tests.fixtures.aftershock.make_fixtures` (network).
- ETAS fits: `uv run python -m tests.fixtures.aftershock.make_fits` (offline, about 4 minutes,
  deterministic — the adapter uses a fixed EM starting point).
- Validation: `uv run python -m rupture.commands.aftershock validate --sequence <name>`
  (about 3 minutes each; seeded, so it reproduces).
- Gate: `make validate-aftershock`.

## Status

Prompt 2 deliverable, validated on two sequences and honest about failing on both in the first
day. Not deployed anywhere. Not connected to any live feed. The FastAPI application is
self-contained and has never been served outside tests.
