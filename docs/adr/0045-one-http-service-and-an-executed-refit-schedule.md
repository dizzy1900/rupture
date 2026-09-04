# ADR-0045 — One HTTP service, the grid over HTTP, and a refit schedule something actually runs

- **Status:** accepted
- **Date:** 2026-09-03
- **Amends:** ADR-0028 (item 7, "the HTTP surface is a self-contained application"), ADR-0016
  (the deployment unit: the image gains a second target)

## Context

Prompt 2 delivered two FastAPI applications and left the assembly to a deployer who does not
exist. `src/rupture/risk/service.py` served `GET /health`, `GET /v1/scenarios` and
`POST /v1/avoided-loss` with keys from `RUPTURE_RISK_API_KEYS`, compared in constant time;
`src/rupture/services/aftershock/service.py` served `GET /healthz` and
`POST /aftershock/forecast` with a single key from `RUPTURE_AFTERSHOCK_API_KEY`, compared with
`!=`. Nothing mounted them together, `docs/AFTERSHOCK.md` § 5 and ADR-0028 item 7 both said
"whoever assembles the deployment can mount both", and the brief asked for the aftershock forecast
to be exposed "via the same FastAPI service" as the risk contract.

Three more things were true of that surface and were not defects of modelling but of exposure:

1. **The grid was computed and thrown away.** `Issuance.grid` is a `ForecastGrid`; the response
   was `issuance.forecast`, whose only spatial content is a `forecast_grid_id` string. There was
   no route that returned a grid, so `docs/AFTERSHOCK.md` § 6 ("use the gridded `ForecastGrid`,
   not the zone-wide ladder, for anything that depends on location") was advice an HTTP client
   could not take. The gridded product existed only through the CLI's `--grid-out`.
2. **The refit schedule was a constant, not a process.** `REFIT_SCHEDULE` and
   `scheduled_fit_cutoff` say which fit a request should use; three fits per sequence were
   committed; every other scheduled cutoff answered 503 forever, because nothing walked the
   schedule and produced the fits.
3. **The image could not serve either application.** `infra/docker/Dockerfile` had no `EXPOSE`,
   no server command, and a build context that excluded `tests/fixtures/`, where the committed
   scenario, exposure, GSIM and sequence inputs live — so `scenarios.builtin()` would have raised
   on every request in the container.

## Decision

**1. One application, two routers, one key check.** `src/rupture/services/app.py::create_app()`
builds a single `FastAPI` and includes `rupture.risk.service.build_router()` and
`rupture.services.aftershock.service.build_router(state)`. Paths are unchanged, so an existing
client of either surface keeps working; there is one `/health` (with `/healthz` as an alias of the
same body, reporting each surface), one OpenAPI document, and one API-key dependency
(`rupture.services.auth.ApiKeyGuard`): `RUPTURE_API_KEYS` is accepted by both surfaces, the older
per-surface variables still work, every comparison is `secrets.compare_digest`, and a surface with
no key configured answers 503 rather than serving open. Both single-surface applications remain
(`rupture.risk.service:app`, `rupture.services.aftershock.service:create_app`) for a deployment
that wants one of them; the combined app is the deployment target.

Routers, not `app.mount()`: mounted sub-applications get their own OpenAPI documents and their own
exception handlers, which is exactly the two-services-in-a-trench-coat shape this replaces.

**2. A degraded surface is reported, not hidden.** The aftershock surface loads catalogues at
start-up. If that fails, the combined app still serves the risk surface, `/health` says
`surfaces.aftershock.status == "unavailable"` with the reason, and the aftershock routes answer
503 with the same reason. A container that exits on a missing fixture tells an operator nothing;
one that serves half a service silently is worse.

**3. The grid is fetchable: `GET /aftershock/grid/{grid_id}`.** The forecast response is unchanged
(it is the published contract `contracts/aftershock-forecast.v0.json`), so the grid is a second
resource rather than a wider response: a client reads `forecast_grid_id` and fetches the
`ForecastGrid`, which validates against `contracts/forecast-grid.v0.json`. Grids are kept as they
are issued, never recomputed on fetch — an unknown id is a 404, not a fresh forecast wearing an
old id. Two stores (`rupture.services.aftershock.grids`): a bounded in-process cache by default,
and a directory store (`RUPTURE_AFTERSHOCK_GRID_DIR`) when the grids must outlive the process or
be shared. The image therefore serves with `--workers 1`: with more, an in-process cache would
404 at random.

**4. The refit schedule is executed by a command, not by a thread in the web process.**
`rupture aftershock refit --sequence <name> [--through 30d]`
(`rupture.services.aftershock.refit`) walks +0, 1, 3, 6, 12 h then daily to +30 d, fits every
cutoff that is due and not already on disk, and writes `<fits_dir>/<cutoff>/fit_result.json` as
each completes. A serving process re-reads that directory (`FitsStore`, a `stat` per request), so
a fit written while the service is up is servable without a restart. A cutoff later than "now", or
later than the catalogue's coverage, is refused with a named reason rather than being fitted on
whatever data happens to exist.

An EM fit takes tens of seconds and grows with the sequence, so it does not belong on the request
path (`allow_refit` stays off by default) and it does not belong in a web worker's background
thread, where it would be duplicated per worker and compete for the GIL. The scheduler is whatever
the deployment already has: cron, a systemd timer, EventBridge, a job manifest.

**5. Catalogues are configuration.** `RUPTURE_AFTERSHOCK_CATALOGS=<name>=<catalog_dir>,<region_file>[,<fits_dir>];...`
(and `rupture aftershock serve --catalog/--region`) point the service at built catalogue
directories, so it is no longer limited to the two committed validation sequences. A malformed
entry refuses to start rather than quietly serving fewer sequences than configured.

**6. The image gains an `api` target.** `FROM runtime AS api` adds `EXPOSE 8000`, a `HEALTHCHECK`
against `/health` and `CMD ["uvicorn", "rupture.services.app:create_app", "--factory", ...]`. The
runtime stage now also copies `tests/fixtures/risk/` and `tests/fixtures/aftershock/` and sets
`RUPTURE_REPO_ROOT=/app`, and `Dockerfile.dockerignore` walks those paths back into the build
context. `infra/docker/compose.yml` gains an `api` service with no default key.

## Consequences

- A consumer gets one process, one port, one health endpoint and one key. The two single-surface
  applications are still built and tested, so nothing that used them breaks.
- **Runtime inputs ship from `tests/fixtures/`.** That is where the committed slices live
  (ADR-0028; `docs/AFTERSHOCK.md` limitation 11), and an image without them cannot answer a single
  request. Moving them under `src/rupture/risk/data/` and `src/rupture/services/aftershock/data/`
  so the wheel carries them is the right fix; it changes paths the risk and aftershock model code
  owns and is left to those owners. Recorded in `docs/DEPLOYMENT.md`.
- **The image has still never been built.** There is no Docker on the development machine and CI
  does not build it. What is verified here is static: the tests in
  `tests/unit/aftershock/test_deployment_image.py` assert that every path the service reads at run
  time is copied in and not excluded from the context, and that the served factory imports. A
  build-and-curl smoke test in CI is named as missing in `docs/DEPLOYMENT.md` and is not claimed.
- **Fits for the first twelve hours now exist** for both validation sequences, written by the new
  runner (`--through 12h`): +0, 3, 6 and 12 h alongside the +1 h, +1 d and +7 d that
  `make_fits` produced. The runner reproduced the committed +1 h fit's
  `parameter_snapshot_hash` and `training_catalog_hash` exactly, which is what says it is doing
  the same thing `make_fits` did. Every one of the fourteen is converged and sub-critical
  (branching ratio 0.18–0.94; the tightest is Kahramanmaraş at +0 h, 0.942).
- The remaining scheduled cutoffs (+2 d … +30 d) are still unfitted for the committed sequences:
  27 more EM fits per sequence, roughly a quarter of an hour of CPU each way, for validation
  slices nothing currently issues against. A request for one of them answers 503 naming the
  command that produces it, which is the honest state, and `rupture aftershock refit --sequence
  <name>` fills them in when someone wants them.
- Nothing in this ADR changes any number: the same fit, the same grid, the same ladder.

## Alternatives considered

- **`app.mount("/risk", risk_app)`.** Rejected: separate OpenAPI documents and separate exception
  handlers per sub-application, and every existing path would move.
- **A background refit thread (or APScheduler) inside `create_app`.** Rejected: minutes-long
  CPU-bound work inside a web worker, duplicated per worker, with no way to see whether it ran.
  A command a scheduler runs is observable and can be retried.
- **Returning the grid inside the forecast response (`include_grid: true`).** Rejected: it changes
  the published contract's response shape for a payload that is roughly a megabyte, and the id was
  already in the response — it just referred to nothing.
- **Recomputing the grid on `GET /aftershock/grid/{id}`.** Rejected: the id encodes model, region,
  issue time and horizon, but not the number of stochastic continuations or the seed, so a
  recomputed grid would differ from the one whose summary the client already holds.
- **Moving the committed runtime inputs under `src/` in this change.** Correct, and not this
  agent's files to move. Recorded above and in `docs/DEPLOYMENT.md`.
