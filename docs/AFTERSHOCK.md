# Operational aftershock forecasts (component C4)

This service answers one question, for one mainshock, as a
rate and a probability:

> Given the sequence so far, what is the expected number of further events of magnitude at least
> *m* in the next 1, 7 or 30 days inside the aftershock zone, and what is the probability that at
> least one of them occurs?

It is the one genuinely operational F1 product in rupture. Design decisions are ADR-0028; the
model card is `reports/MODEL_CARD_aftershock.md`; the code is
`src/rupture/services/aftershock/`.

---

## 1. The sequence window

The sequence of a mainshock of magnitude *M* is every event with

- `origin_time >= mainshock_time`, and
- epicentral distance `<= R(M)`,

with

```
R(M) = max(20 km, 1.5 x L(M))      capped at 600 km
L(M) = 10 ** (-2.44 + 0.59 * M) km
```

`L` is the **subsurface rupture length** of Wells & Coppersmith (1994), *BSSA* 84(4), 974–1002,
Table 2A, "all" slip type. For M7.8, `L = 145 km` and `R = 218 km`.

Why 1.5 rupture lengths. The aftershock zone scales with the rupture, not with the epicentre, and
the epicentre can sit at one end of it. At `f = 1` the 2015-05-12 M7.3 Gorkha aftershock — 139 km
from the M7.8 epicentre, because the Gorkha rupture propagated east — would sit within a few
kilometres of the boundary, and whether it counted as part of its own sequence would turn on
rounding. One to two rupture lengths is the usual convention in the aftershock-statistics
literature. Gardner & Knopoff (1974) declustering windows are smaller (about 89 km at M7.8)
because they are tuned to *remove* dependent events from a catalogue rather than to bound where
triggering can occur, and are too tight for a forecast zone.

The radius is fixed before any forecast is issued and does not depend on where the aftershocks
actually fell. It is a single number per magnitude: too generous for a compact sequence, too tight
for a very long unilateral rupture. Implementation and citations:
`src/rupture/services/aftershock/window.py`.

**The zone as a region.** The zone becomes a `Region` (a 72-vertex spherical circle) that inherits
its magnitude of completeness, target threshold, depth range and magnitude binning from the
published parent region — `data/regions/nepal-himalaya/` and `data/regions/turkiye-eaf/`. Only the
polygon and the identity are new. Nothing about what a forecast *means* is invented per sequence.

| | Gorkha 2015 | Kahramanmaraş 2023 |
|---|---|---|
| mainshock | `us20002926`, 2015-04-25T06:11:25.95Z, M7.8, 28.2305 N 84.7314 E, 8.2 km | `us6000jllz`, 2023-02-06T01:17:34.34Z, M7.8, 37.2256 N 37.0143 E, 10 km |
| parent region | `nepal-himalaya` | `turkiye-eaf` |
| zone radius | 218 km | 218 km |
| cells at 0.1° | 1366 | 1510 |
| Mc (fitting) | 4.4 | 4.3 |
| target threshold | M4.7 | M4.6 |
| long-run b (fixed) | 1.138 | 1.026 |

Both mainshock records are checked against the committed ComCat slice on every run
(`check_against_catalog`) and against the live ComCat service in
`tests/integration/aftershock/test_comcat_identifiers.py` (`make test-integration`).

---

## 2. The refit schedule

A service following this schedule refits at **+1 h, +3 h, +6 h, +12 h, then daily to +30 d**. A
forecast issued at time *T* uses the fit whose cutoff is the latest scheduled point at or before
*T*. Before the first scheduled refit it uses a fit cut at the mainshock time — purely
pre-mainshock parameters for the zone.

Each fit is `MizrahiETAS` (ADR-0009, ADR-0018; rupture writes no second ETAS) on **every event in
the zone with `origin_time < cutoff`**: about a decade of pre-mainshock seismicity, which supplies
the auxiliary window and the background rate, plus the sequence so far. As the sequence
accumulates target events it dominates the fit, so the parameters begin as the zone's long-run
parameters and become sequence-specific. That is the usual operational shape — generic parameters
first, sequence-specific parameters later — reached by moving the ETAS cutoff rather than by
adding a second model.

**The b-value is fixed, not fitted.** `beta = b ln 10` is pinned to the parent region's published
long-run b. Fitting b on the sequence is biased low by short-term aftershock incompleteness (the
hours after a large mainshock are missing small events, which flattens the observed
frequency–magnitude distribution), and a low b inflates the large-magnitude tail. Fitting it
freely gave b = 0.76 and a **branching ratio of 1.07** for Kahramanmaraş at +1 d: a supercritical
model whose stochastic continuations do not terminate. With b fixed, every fit below is
sub-critical. `FitResult.diagnostics['beta_fixed']` records which was done. Simulated magnitudes
are additionally capped at `Region.magnitude_max` (8.95).

### Running the schedule

The schedule is executed by a command, not by the service:

```
rupture aftershock refit --sequence gorkha --through 30d      # fit every due cutoff
rupture aftershock refit --sequence gorkha --dry-run          # list what is due, fit nothing
rupture aftershock refit --catalog <dir> --region <file> --mainshock <id> --out <fits dir>
```

It walks +0, 1, 3, 6, 12 h then daily to `--through`, skips any cutoff that already has a fit
(unless `--force`), and writes `<fits>/<cutoff>/fit_result.json` as each one completes, merging the
diagnostics into that directory's `provenance.json`. A cutoff later than now — or later than the
catalogue's coverage — is refused with the reason printed, never fitted on whatever data happens
to be there. This is what a cron entry, a systemd timer or a scheduled job runs; a serving process
re-reads the fits directory, so a fit written while it is up is served by the next request without
a restart (ADR-0045).

The service does **not** refit inside a request. An EM fit takes tens of seconds and grows with
the sequence, so a request whose scheduled cutoff has no fit answers 503 naming the cutoff and the
command that produces it. `create_app(allow_refit=True)` (or
`RUPTURE_AFTERSHOCK_ALLOW_REFIT=1`) overrides that where a slow request is acceptable.

### Fits actually used

| sequence | cutoff | training events | b | branching ratio | parameters on a bound |
|---|---|---|---|---|---|
| gorkha | +0 h | 35 | 1.138 (fixed) | 0.180 | `log10_k0`, `omega` |
| gorkha | +1 h | 56 | 1.138 (fixed) | 0.346 | `log10_k0`, `omega` |
| gorkha | +3 h | 79 | 1.138 (fixed) | 0.532 | `log10_k0`, `omega` |
| gorkha | +6 h | 97 | 1.138 (fixed) | 0.599 | `log10_k0`, `omega` |
| gorkha | +12 h | 108 | 1.138 (fixed) | 0.612 | `omega` |
| gorkha | +1 d | 123 | 1.138 (fixed) | 0.646 | `omega` |
| gorkha | +7 d | 166 | 1.138 (fixed) | 0.681 | — |
| kahramanmaras | +0 h | 94 | 1.026 (fixed) | 0.942 | — |
| kahramanmaras | +1 h | 116 | 1.026 (fixed) | 0.847 | — |
| kahramanmaras | +3 h | 150 | 1.026 (fixed) | 0.773 | — |
| kahramanmaras | +6 h | 179 | 1.026 (fixed) | 0.776 | — |
| kahramanmaras | +12 h | 236 | 1.026 (fixed) | 0.744 | — |
| kahramanmaras | +1 d | 303 | 1.026 (fixed) | 0.732 | — |
| kahramanmaras | +7 d | 446 | 1.026 (fixed) | 0.811 | — |

All fourteen converged and all are sub-critical; the tightest is Kahramanmaraş at +0 h (0.942),
the zone's pre-mainshock parameters. The Gorkha fits with `omega` on its inversion bound have
Omori `p = 2.0`, the fastest decay the package allows — an artefact of fitting the temporal kernel
on a few hours of a sequence, and part of why those forecasts are too low (§ 4). They are
reported, not hidden; the gate prints them.

The six fits at +1 h, +1 d and +7 d were written by
`uv run python -m tests.fixtures.aftershock.make_fits`; the eight early-hours fits by
`rupture aftershock refit --sequence <name> --through 12h` (about a minute per sequence). The two
routes produce the same thing: re-running the refit command over the +1 h cutoff reproduced the
committed fit's `parameter_snapshot_hash` and `training_catalog_hash` exactly.

**+2 d to +30 d are not fitted** for these two sequences — 27 more EM fits each, for issue times
nothing currently scores. A request for one of them answers 503 naming the command above.

---

## 3. From a grid to a probability — the Poisson assumption

An issuance produces a `ForecastGrid` of expected counts per cell per magnitude bin over
`[issue_time, issue_time + horizon)`, and summarises it as an `AftershockForecast` carrying a
ladder of thresholds `M-3, M-2, M-1, M` (for M7.8: 4.8, 5.8, 6.8, 7.8), snapped to the bin edges
and clipped at the region's target threshold. For each rung,

```
lambda = sum over all cells and all magnitude bins at or above the threshold
P      = 1 - exp(-lambda)
```

**`P = 1 - exp(-lambda)` assumes the events above the threshold in the window are a Poisson
process. They are not.** ETAS is a clustering process: the count is over-dispersed relative to
Poisson, so `1 - exp(-lambda)` **over-states** the probability of at least one event whenever
`lambda` is not small. (Intuitively, a clustered process puts more mass on zero *and* more mass on
large counts than a Poisson with the same mean; the formula only knows the mean.) At small
`lambda` the two agree to first order, which is the regime of the M-1 and M rungs. The assumption
is stated in the module docstring, in the `notes` of every issued forecast, in the API
description, in the model card and here. It is not corrected silently.

The triggered part of the grid is the mean over stochastic continuations of the history (100 for
the published numbers); the background part and the magnitude distribution are analytic
(ADR-0018). Monte-Carlo noise on the total is visible: 5 continuations and 100 continuations of
the same fit differed by tens of per cent in testing. A published expected count is not precise to
better than about 10 %.

---

## 4. Validation: two real sequences, pseudo-prospective

Issued at **+1 h, +1 d and +7 d** after each mainshock, over 1-, 7- and 30-day horizons, scoring
only windows that closed inside the catalogue's coverage. Leakage is refused, not filtered: the
fit sees only `origin_time < cutoff` and the issuance refuses a history that reaches the issue
time (`LeakageError`). Full tables — every rung, every CSEP test — are in
`reports/aftershock/gorkha.md` and `reports/aftershock/kahramanmaras.md`; the machine-readable
form is the `.json` beside each.

Reproduce with `uv run python -m rupture.commands.aftershock validate --sequence gorkha`
(and `--sequence kahramanmaras`), about three minutes each.

### 4.1 Counts: expected against observed

Gridded totals above each region's target threshold, and the CSEP N-test verdict.

**Gorkha 2015 (M ≥ 4.7)**

| issue | horizon | expected | observed | N-test |
|---|---|---|---|---|
| +1 h | 1 d | 3.37 | 43 | fail |
| +1 h | 7 d | 3.77 | 57 | fail |
| +1 h | 30 d | 4.01 | 107 | fail |
| +1 d | 1 d | 2.78 | 11 | fail |
| +1 d | 7 d | 4.30 | 15 | fail |
| +1 d | 30 d | 5.28 | 65 | fail |
| +7 d | 1 d | 1.27 | 0 | **pass** |
| +7 d | 7 d | 3.44 | 2 | **pass** |
| +7 d | 30 d | 4.92 | 53 | fail |

**Kahramanmaraş 2023 (M ≥ 4.6)**

| issue | horizon | expected | observed | N-test |
|---|---|---|---|---|
| +1 h | 1 d | 13.64 | 166 | fail |
| +1 h | 7 d | 26.21 | 268 | fail |
| +1 h | 30 d | 42.05 | 312 | fail |
| +1 d | 1 d | 14.84 | 42 | fail |
| +1 d | 7 d | 29.84 | 109 | fail |
| +1 d | 30 d | 36.85 | 150 | fail |
| +7 d | 1 d | 4.35 | 3 | **pass** |
| +7 d | 7 d | 25.82 | 17 | **pass** |
| +7 d | 30 d | 44.96 | 53 | **pass** |

**This is the main result, and it is not a good one.** At +1 h and +1 d the forecast under-counts
by roughly a factor of 3 to 12. By +7 d, when the fit has 166 (Gorkha) or 446 (Kahramanmaraş)
training events of which most are aftershocks, the counts are consistent with what happened —
every +7 d N-test passes except the Gorkha 30-day window, which contains the M7.3 of 12 May and
its own aftershocks.

The reason is structural, not a coding error. In the first hours the training slice is a decade of
mostly isolated background seismicity in the zone plus a handful of sequence events, so the EM has
almost nothing from which to estimate aftershock productivity, and the fitted productivity is that
of a quiet region. Operational aftershock forecasting solves this with *generic* parameters
estimated across many sequences (Reasenberg & Jones 1989; van der Elst & Page 2018) and updated
towards the sequence as data arrive. rupture has no multi-sequence parameter set, so the early
forecasts are what a regional ETAS fit gives, and that is too low. See ADR-0028, "Alternatives
considered".

Two further contributions, both in the same direction: short-term aftershock incompleteness means
the observed counts are themselves an undercount of what occurred, so the true discrepancy is
larger; and the Gorkha +1 h and +1 d fits sit on the Omori bound `p = 2.0`, which decays the
triggered rate away almost immediately.

### 4.2 The magnitude ladder against the events that mattered

Selected rows; the complete tables are in `reports/aftershock/`.

**Kahramanmaraş — the M7.5 doublet, 9 h 07 m after the mainshock.** The +1 h forecast is the only
one issued before it.

| issue | horizon | M ≥ | lambda | P | observed | verdict |
|---|---|---|---|---|---|---|
| +1 h | 1 d | 4.8 | 8.50 | 0.9998 | 90 | too low |
| +1 h | 1 d | 5.8 | 0.801 | 0.551 | 5 | too low |
| +1 h | 1 d | **6.8** | **0.0752** | **0.072** | **1** (`us6000jlqa`, M7.5) | consistent with Poisson |
| +1 h | 1 d | 7.8 | 0.0067 | 0.007 | 0 | consistent |
| +1 h | 7 d | 6.8 | 0.1445 | 0.135 | 1 | consistent |

One hour after the mainshock the service put the probability of at least one M ≥ 6.8 in the next
day at **7.2 %**, and one occurred nine hours later. That is a small probability attached to an
event that happened; it is not a hit and not a miss, and it is exactly the shape of statement an
aftershock forecast can make. The count rungs at 4.8 and 5.8 in the same forecast are badly too
low.

**Gorkha — the M7.3 of 2015-05-12, 17 days after the mainshock.**

| issue | horizon | M ≥ | lambda | P | observed | verdict |
|---|---|---|---|---|---|---|
| +1 h | 30 d | 6.8 | 0.0163 | 0.016 | 1 (`us20002ejl`, M7.3) | flagged: P(N ≥ 1) = 0.016 |
| +1 d | 30 d | 6.8 | 0.0214 | 0.021 | 1 | flagged: P(N ≥ 1) = 0.021 |
| +7 d | 30 d | 6.8 | 0.0200 | 0.020 | 1 | flagged: P(N ≥ 1) = 0.020 |
| +7 d | 7 d | 4.8 | 2.649 | 0.929 | 2 | consistent |
| +7 d | 1 d | 4.8 | 0.977 | 0.624 | 0 | consistent |
| any | any | 7.8 | 0.001–0.0015 | ≈0.001 | 0 | consistent |

Every 30-day window issued for Gorkha put the probability of an M ≥ 6.8 at about **2 %**, and one
occurred. Under the Poisson check that is inconsistent at alpha = 0.05 — the forecast was too low
on the large-magnitude rung too, by roughly the same factor as on the counts. A 2 % statement is
not falsified by a single event in any strong sense, but three independent windows all giving
about 2 % for something that happened is a consistent under-forecast, and the count tables above
say the same thing.

### 4.3 Where the ladder and the grid disagree, and why

For Kahramanmaraş at +7 d the gridded N-test passes (25.82 expected against 17 observed at
M ≥ 4.6) while the M ≥ 4.8 rung is flagged as a gross over-forecast (16.1 expected against 3
observed). The cause is magnitude quantisation, not the model. Most ComCat entries in these boxes
are teleseismic `mb`, reported to 0.1, and Scordilis (2006) maps them with `Mw = 0.85 mb + 1.03`,
so the homogenised Mw values land on a lattice with 0.085 spacing: 4.60, 4.68, 4.77, 4.86, …
Fourteen of the seventeen observed events fall below 4.8 on that lattice, while the model's
continuous Gutenberg–Richter distribution puts 62 % of M ≥ 4.6 events above 4.8 (16.1 of 25.8).
The ladder thresholds are on the 0.1 magnitude-bin grid; the observations are on the Scordilis
lattice; the two do not line up. **Read the M-3 rung of the ladder with this in mind for any
catalogue dominated by converted `mb`.**

---

## 5. Interfaces

### CLI

```
rupture aftershock forecast --mainshock us20002926 --horizon 7d --issue 2015-04-26T06:11:26Z
rupture aftershock refit --sequence gorkha --through 30d
rupture aftershock validate --sequence gorkha
rupture aftershock serve --host 127.0.0.1 --port 8000
```

The sub-application is `src/rupture/commands/aftershock.py`, mounted in `src/rupture/cli.py`.
`forecast` accepts `--catalog <dir> --region <file>` to use a built catalogue instead of the
committed slice, and `--grid-out <path>` to write the `ForecastGrid` behind the summary. `refit`
is § 2. `serve` runs the combined service by default (`--surface aftershock` for this surface
alone, with `--catalog/--region` to add a built catalogue and `--allow-refit` to permit refitting
inside a request).

### HTTP

**One service, both surfaces** (ADR-0045). `uvicorn rupture.services.app:create_app --factory`
serves the aftershock forecast and the avoided-loss contract in one process, with one `/health`,
one OpenAPI document at `/docs`, and one `X-API-Key` scheme. This is what the `api` target of
`infra/docker/Dockerfile` runs; `docs/DEPLOYMENT.md` § The HTTP service has the deploy notes. The
aftershock surface alone is still available as
`uvicorn rupture.services.aftershock.service:create_app --factory`, on the same paths.

| Route | Auth | Purpose |
|---|---|---|
| `GET /health`, `GET /healthz` | none | liveness; the loaded sequences, the fits on disk, where grids are kept, whether a key is configured, and the Poisson assumption |
| `POST /aftershock/forecast` | `X-API-Key` | issue a forecast for a sequence |
| `GET /aftershock/grid/{grid_id}` | `X-API-Key` | the `ForecastGrid` behind an issued forecast |
| `GET /v1/scenarios`, `POST /v1/avoided-loss` | `X-API-Key` | the loss surface (`docs/RISK.md`) |

Keys come from `RUPTURE_API_KEYS` (both surfaces) or `RUPTURE_AFTERSHOCK_API_KEY(S)`, compared in
constant time. **With no key configured the authenticated routes answer 503**, never open.

`POST /aftershock/forecast` takes `mainshock_id` **or** an explicit `mainshock` object
(`origin_time`, `latitude`, `longitude`, `magnitude`, optional `depth_km`), plus `sequence`,
`issue_time`, `horizon` (`1d` / `7d` / `30d`) and optional `n_simulations`:

```json
{
  "mainshock_id": "us20002926",
  "issue_time": "2015-04-26T06:11:26Z",
  "horizon": "7d"
}
```

The response body is the published contract `contracts/aftershock-forecast.v0.json`; a unit test
validates a real response against it. An issue time whose scheduled fit cutoff has no persisted
fit is refused with **503** naming the cutoff and the refit command (§ 2).

`GET /aftershock/grid/{grid_id}` returns the gridded rate forecast behind a response, keyed by its
`forecast_grid_id`, as `contracts/forecast-grid.v0.json`. **This is the route to use for anything
that depends on location** (§ 6): the ladder in the forecast is a statement about the whole zone —
a circle 218 km across for an M7.8. Grids are kept as they are issued, never recomputed on fetch,
so an id the process never issued is a 404. By default they are held in a bounded in-process cache
(the last 16), which is **not shared between uvicorn workers**; set
`RUPTURE_AFTERSHOCK_GRID_DIR` to a directory to share them across workers and restarts. The image
serves with one worker for exactly this reason.

Which catalogues are served is configuration, not code:
`RUPTURE_AFTERSHOCK_CATALOGS="<name>=<catalog_dir>,<region_file>[,<fits_dir>];..."` adds built
catalogue directories to (or replaces) the two committed validation sequences. A malformed entry
refuses to start rather than serving fewer sequences than it was told to.

### Gate

`make validate-aftershock` (`src/rupture/validation/aftershock.py`), about 60 s offline. It
verifies the fixture digests and the declared mainshocks, checks that each committed fit's
`training_catalog_hash` recomputes from the committed slice and that its branching ratio is
sub-critical, issues and scores both sequences at all three issue times over a 7-day horizon,
checks that every probability is in [0, 1] and non-increasing with magnitude, and requires a
`LeakageError` when a post-issue event is injected. Reports go to `reports/validate-aftershock/`.

To stay inside its budget the gate uses a coarser 0.2° cell and **5** stochastic continuations,
where the published numbers above use 0.1° and 100. Five continuations is far too few for a
stable mean: the gate's Gorkha +7 d / 7 d expected count came out at 0.51 against the published
2.65, a factor of five. **The gate proves the pipeline runs, refuses leakage and produces
well-formed probabilities; its expected counts are not the numbers to quote.** It also does not
fail when a forecast scores badly — a gate that did would be a gate against reporting the truth.

---

## 6. What an operator may and may not conclude

**May.**

- Treat the expected counts and probabilities as *conditional rates given the sequence so far and
  this model*, over the stated window and inside the stated circle.
- Use the shape of the decay — the ratio between the 1-day, 7-day and 30-day numbers — to reason
  about how long elevated rates persist.
- Use the gridded `ForecastGrid` (not the zone-wide ladder) for anything that depends on location:
  `GET /aftershock/grid/{forecast_grid_id}` over HTTP, or `--grid-out` from the CLI (§ 5).
- Take the M-1 and M rungs at face value as *small* probabilities, while remembering § 4.2: for
  these two sequences they were too small.

**May not.**

- Conclude anything about an individual future earthquake: its time, its place, its magnitude, or
  whether one happens at all. This is a rate statement about a population of possible events.
- Read the absence of a large rung as safety. A 2 % 30-day probability of M ≥ 6.8 is a real 2 %,
  and one of the two sequences here delivered that event.
- Use the numbers for evacuation, all-clear or life-safety decisions. The service is not an
  earthquake warning system, has no real-time data feed, and is validated on two sequences.
- Trust the first 24 hours quantitatively. § 4.1 shows counts too low by a factor of 3 to 12 in
  that period. Use them as a lower bound at best.
- Compare a number from `reports/validate-aftershock/` (the gate, coarse) with one from
  `reports/aftershock/` (the published validation). They are different resolutions.

---

## 7. Limitations

1. **Early forecasts are too low**, by a factor of roughly 3–12 in the first day, for the
   structural reason in § 4.1. A generic multi-sequence parameter set is the known fix and is not
   implemented.
2. **No time-varying Mc.** The fitting Mc is the region's long-run value (4.4 / 4.3). Real
   completeness after a M7.8 is far higher for hours to days (Helmstetter, Kagan & Jackson 2006),
   so early target counts are themselves undercounts and the fit is trained on an incomplete
   slice.
3. **b is fixed**, so a sequence whose true b differs from the regional value is mis-forecast in
   the tail. The alternative was a supercritical model (§ 2).
4. **The Poisson summary over-states P(at least one)** where `lambda` is not small (§ 3).
5. **Magnitude quantisation** from `mb` → Mw conversion distorts the low rungs of the ladder
   (§ 4.3).
6. **One zone radius per magnitude**, fixed in advance, ignoring rupture geometry, aspect ratio
   and directivity (§ 1).
7. **Two sequences.** Both are continental M7.8 events. Nothing here says how the service behaves
   for a subduction megathrust, a swarm, or a moderate mainshock.
8. **Monte-Carlo noise** of order 10 % on the triggered component at 100 continuations (§ 3).
9. **Depth is ignored** beyond the region's depth filter: the forecast is two-dimensional.
10. **Committed fits, and no live feed.** The refit schedule is now executed by
    `rupture aftershock refit` and the service picks up what it writes without a restart (§ 2,
    ADR-0045), but what it refits is a committed slice: rupture has **no live catalogue feed**, so
    nothing keeps a sequence current on its own. Against the committed slices the schedule is
    fitted out to +12 h; +2 d to +30 d are unfitted and answer 503 until someone runs the command.
    Wiring the runner to a feed, and to a scheduler, is a deployment's job and has not been done
    anywhere.
11. **The offline catalogues live under `tests/fixtures/aftershock/`** rather than
    `data/catalogs/`, because the DVC-tracked catalogues were not present in this worktree. The
    slices are byte-exact ComCat responses with recorded provenance and digests, and
    `--catalog`/`--region` takes a built catalogue directory when one exists.

## References

- Wells, D. L. & Coppersmith, K. J. (1994). New empirical relationships among magnitude, rupture
  length, rupture width, rupture area, and surface displacement. *BSSA* 84(4), 974–1002.
- Gardner, J. K. & Knopoff, L. (1974). Is the sequence of earthquakes in southern California, with
  aftershocks removed, Poissonian? *BSSA* 64(5), 1363–1367.
- Reasenberg, P. A. & Jones, L. M. (1989). Earthquake hazard after a mainshock in California.
  *Science* 243, 1173–1176.
- van der Elst, N. J. & Page, M. T. (2018). Nonparametric aftershock forecasts based on similar
  sequences in the past. *SRL* 89(1), 145–152.
- Helmstetter, A., Kagan, Y. Y. & Jackson, D. D. (2006). Comparison of short-term and
  time-independent earthquake forecast models for southern California. *BSSA* 96(1), 90–106.
- Mizrahi, L., Nandan, S. & Wiemer, S. (2021). The effect of declustering on the size distribution
  of mainshocks. *SRL* 92(4), 2333–2342. (The `etas` package; ADR-0009.)
- Scordilis, E. M. (2006). Empirical global relations converting MS and mb to moment magnitude.
  *Journal of Seismology* 10, 225–236.
