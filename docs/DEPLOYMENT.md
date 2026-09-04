# Deployment

rupture does not predict earthquakes. This document describes the deployment unit (one plain
Docker image), the portable job manifests, and how to point them at AWS Batch/ECS or anything
else. Decisions: ADR-0016 (image + manifests), ADR-0011 and ADR-0030 (OpenQuake engine image).

## What is provided

| Artifact | Purpose |
|---|---|
| `infra/docker/Dockerfile` (+ `Dockerfile.dockerignore`) | multi-stage build of the locked `uv` environment and the `rupture` CLI on `python:3.12-slim`; non-root user; OCI labels with the git sha. Two targets: `runtime` (default, the CLI) and `api` (the HTTP service) |
| `infra/docker/compose.yml` | local development: `rupture` (`src/`, `contracts/`, `data/` mounted into `/app`), `api` (the service on 127.0.0.1:8000) and `openquake/engine:3.26.2` (named volume `oqdata`, WebUI on 127.0.0.1:8800). **Unexercised**: never brought up (no Docker here) |
| `infra/jobs/*.yaml` + `schema.json` + `README.md` | nine portable job manifests with `aws:` annotations, each carrying a core-hour estimate and the basis for it, validated in the unit suite |
| `infra/jobs/examples/turkiye-eaf-classical.json` | example `ClassicalPSHAJob` input (not run) |

## What is not provided

- No Terraform, CDK, CloudFormation or Kubernetes manifests; no hosted platform of any kind
  (non-negotiable 6). The `aws:` blocks are annotations a deployer reads, not infrastructure code.
- No scheduler implementation; `docs/SCHEDULER.md` (Phase 2B) describes the intended daily run.
  The aftershock refit schedule is a command (`rupture aftershock refit`, ADR-0045) meant to be
  run by whatever the deployment already schedules; rupture ships no scheduler and no live
  catalogue feed to point one at.
- No registry, no published image. The image has **not been built** on the development machine
  (no Docker); it was reviewed by hand and the CI does not build it yet.
- No docker CLI inside the rupture image: `rupture hazard ...` requires a host with Docker.
- No `dvc` inside the rupture image (dev-group dependency; the image is built `--no-dev`). DVC
  transfer is the deployer's init step or sidecar, outside the job container, and is unverified.

## The image

```bash
docker build -f infra/docker/Dockerfile \
  --build-arg GIT_SHA=$(git rev-parse HEAD) \
  --build-arg BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ) \
  -t rupture:$(git rev-parse --short HEAD) .
docker run --rm rupture:<sha> rupture --help
docker run --rm -v "$PWD/data:/app/data" rupture:<sha> rupture region list
```

The image has **not been built anywhere yet** (no Docker on the development machine; the CI does
not build it): the Dockerfile was reviewed by hand only.

- Build context is the repository root; `infra/docker/Dockerfile.dockerignore` (read by BuildKit
  for this Dockerfile) keeps it to `pyproject.toml`, `uv.lock`, `README.md`, `LICENSE`, `src/`,
  `contracts/`, `data/regions/`, and the two committed runtime input directories
  `tests/fixtures/risk/` and `tests/fixtures/aftershock/` (see the wart at the end of § The HTTP
  service).
- Stage 1 installs `uv` from `ghcr.io/astral-sh/uv:0.11.7`, syncs dependencies from the lock
  (`--locked --no-dev`, `git` present for the pinned ETAS dependency), then installs the project.
  Stage 2 (`runtime`) copies the venv, `src/`, `contracts/`, `data/regions/` (tracked via
  `data/regions/.gitkeep` until Phase 2A populates it) and the committed runtime inputs, sets
  `RUPTURE_REPO_ROOT=/app`, and runs as `rupture` (uid 10001). There is **no `ENTRYPOINT`**: the
  container command is the full argv (`rupture ...`), exactly as the job manifests' `command`
  lists it; the default `CMD` is `rupture --help`. Stage 3 (`api`, built with `--target api`) adds
  `EXPOSE 8000`, a `HEALTHCHECK` and the uvicorn command — no extra packages: `fastapi` and
  `uvicorn` are project dependencies already in the venv.
- Inputs and outputs live on volumes (`/app/data`, `/app/baselines`, `/app/reports`) or come and
  go through DVC; the image contains no data and no credentials. Configuration is environment
  variables named in `.env.example` (`docs/CREDENTIALS.md`).
- Labels: `org.opencontainers.image.revision=<GIT_SHA>`, `...created`, `...source`, `...licenses`.

The OpenQuake engine is a second, public image (`openquake/engine:3.26.2`); rupture's image drives
it through the host's `docker` CLI and does not contain it.

## The HTTP service

One application serves both surfaces (ADR-0045): the avoided-loss contract (`docs/RISK.md`) and
the aftershock forecast (`docs/AFTERSHOCK.md`), with one health endpoint, one OpenAPI document at
`/docs` and one API-key scheme.

```bash
docker build -f infra/docker/Dockerfile --target api \
  --build-arg GIT_SHA=$(git rev-parse HEAD) -t rupture-api:$(git rev-parse --short HEAD) .
docker run --rm -p 8000:8000 -e RUPTURE_API_KEYS=change-me rupture-api:<sha>

curl -s localhost:8000/health
curl -s -H "X-API-Key: change-me" localhost:8000/v1/scenarios
```

Without a container: `RUPTURE_API_KEYS=change-me uv run uvicorn rupture.services.app:create_app
--factory --host 0.0.0.0 --port 8000`, or `uv run rupture aftershock serve`.

| Route | Auth | Purpose |
|---|---|---|
| `GET /health`, `GET /healthz` | none | liveness, and what each surface is holding. A surface that failed to load reports `status: "unavailable"` with the reason and still returns 200 |
| `GET /v1/scenarios` | key | the scenarios a loss request may name |
| `POST /v1/avoided-loss` | key | expected loss, and what an intervention avoids |
| `POST /aftershock/forecast` | key | probability of at least one further event, for a sequence |
| `GET /aftershock/grid/{grid_id}` | key | the gridded rate forecast behind a forecast |

| Variable | Meaning |
|---|---|
| `RUPTURE_API_KEYS` | comma-separated keys accepted by both surfaces. **With none set every authenticated route answers 503** rather than serving open. `RUPTURE_RISK_API_KEYS`, `RUPTURE_AFTERSHOCK_API_KEYS` and `RUPTURE_AFTERSHOCK_API_KEY` still work per surface |
| `RUPTURE_REPO_ROOT` | where the committed scenario, exposure and sequence inputs live; `/app` in the image |
| `RUPTURE_AFTERSHOCK_CATALOGS` | `<name>=<catalog_dir>,<region_file>[,<fits_dir>];...` — built catalogues to serve beyond the two committed validation sequences |
| `RUPTURE_AFTERSHOCK_GRID_DIR` | where issued grids are kept so `GET /aftershock/grid/{id}` can answer. Unset means an in-process cache of the last 16, not shared between workers |
| `RUPTURE_AFTERSHOCK_ALLOW_REFIT` | `1` to let a request refit when no scheduled fit exists. Off by default: an EM fit takes tens of seconds |
| `SERAC_EXPORT_DIR` | the sibling's checkout, when its live export should be used instead of the committed copy |

**Sizing and operations.**

- **One worker.** The image runs `uvicorn --workers 1`. The default grid store is in-process, so a
  second worker would make `GET /aftershock/grid/{id}` 404 at random for grids another worker
  issued. To scale out, set `RUPTURE_AFTERSHOCK_GRID_DIR` to a shared volume first.
- **Memory** is dominated by the loaded catalogues (both committed sequence slices and their fits
  are read at start-up) and by a forecast's stochastic continuations; 2 GB is a sensible floor and
  has not been measured under load anywhere.
- **Latency is not a web latency.** A forecast runs `n_simulations` stochastic continuations
  inside the request: seconds to tens of seconds at the default 100. Set a generous proxy timeout,
  or lower `n_simulations` per request.
- **Keeping fits current** is `rupture aftershock refit --sequence <name>` on a schedule (cron, a
  systemd timer, EventBridge), writing into the fits directory the service reads. The service
  re-reads it, so no restart is needed. Nothing refits on its own.
- **Key rotation**: keys are read from the environment on every request, so a process whose
  environment is re-exec'd with a new `RUPTURE_API_KEYS` (or a restarted container) rotates
  without code changes. Keep the old key in the comma-separated list until clients have moved.
  There is no user model, no session, no rate limiting and no audit log; this is not a
  public-internet service.
- **Health check**: the image's `HEALTHCHECK` polls `/health`. It reports liveness, not that a
  calculation would succeed — read `surfaces.*.status` for that.

**Not verified.** The image has never been built or run (no Docker here; CI does not build it), so
none of the above has been exercised against a running container. What is checked offline is that
every path the service reads at run time is copied into the image and not excluded from the build
context, and that the served factory imports
(`tests/unit/aftershock/test_deployment_image.py`). A CI job that builds the `api` target and
curls `/health` is the missing piece.

**A known wart.** The image copies `tests/fixtures/risk/` and `tests/fixtures/aftershock/` into
`/app` because that is where the committed runtime inputs live (the Gorkha FSP, the HAZUS and GSIM
tables, the exposure fallback, the two ComCat sequence slices and their fits). Shipping a `tests/`
directory in a runtime image is not right; moving those inputs under `src/rupture/risk/data/` and
`src/rupture/services/aftershock/data/` so the wheel carries them is the fix, and it belongs to
the owners of that model code (ADR-0045).

## Job manifests

See `infra/jobs/README.md` for field semantics. In one sentence: `image` + `command` is what runs,
`inputs`/`outputs` are DVC paths with `${RUPTURE_DVC_REMOTE_URL}/...` URIs, `resources` and
`schedule` are sizing and cadence, `env` lists variable names, and `aws:` is an annotation.

Nine manifests: the five Prompt 1 jobs (catalogue, ETAS fit, issuance, the pseudo-prospective
schedule, classical PSHA) plus full training of the Prompt 2 learned challengers
(`select-ntpp`, `train-ntpp`, `run-ensemble-protocol`) and the 10^4-event stochastic event set
that would bridge the forecasting layer to event-based loss (`stochastic-event-set`).

### What one run costs

Every manifest carries `resources.core_hours_estimate` — expected CPU-core-hours for **one**
invocation, `(user + system CPU seconds) / 3600` — next to `core_hours_basis`
(`measured` / `extrapolated` / `guess`) and a `core_hours_note` that says which run the figure came
from. This is the number to confirm against before a paid run (non-negotiable 7). It is not the
same as `cpu × timeout_minutes`, which is the ceiling the job is killed at; the two differ by one
or two orders of magnitude on most of these jobs, and the estimate is required to sit below it.

One estimate is `measured` (`evaluate-schedule`, from the timed Türkiye and Nepal schedule runs
under `reports/protocol/`), four are `extrapolated` and three are `guess`. `infra/jobs/README.md`
gives the arithmetic for each. Nothing in this repository persists elapsed time — the ensemble
protocol runner prints fit durations to stdout and drops them, and no committed report carries a
duration — so recording `elapsed_seconds` in the schedule reports and in the `Tracker` records
(ADR-0023) is what would turn the extrapolations into measurements on the next run.

### Two manifests do not start with `rupture`

`select-ntpp` and `train-ntpp` invoke `python -m rupture.commands.challenger ntpp ...` because
`src/rupture/cli.py` has not mounted the challenger sub-app, and `run-ensemble-protocol` invokes
`python -m rupture.models.ensemble.protocol_runner` because that runner is an argparse `main()`
with no verb. Both forms run today. `stochastic-event-set` is different again: its command names a
`rupture forecast simulate` verb that **does not exist**, and the manifest says so in its `status`
field. `tests/unit/hazard/test_job_manifests.py` resolves every command against the typer
application or the module path and fails if a `status` disagrees with the tree, so these three
cannot quietly become stale once the verbs land.

### Tracking

No manifest configures a tracker. Jobs write run records through the `Tracker` port to a local
JSONL log listed under `outputs`; the Weights & Biases mirror is opt-in via `WANDB_API_KEY` and the
`wandb` extra (ADR-0023). `WANDB_API_KEY` is not in `.env.example`, so no manifest may list it in
`env` — adding it there is the enabling step, and until the call sites use
`rupture.adapters.storage.make_tracker` setting it changes nothing.

## Pointing at AWS Batch / ECS

For each manifest:

1. Push the image to ECR; set `RUPTURE_IMAGE=<account>.dkr.ecr.<region>.amazonaws.com/rupture:<sha>`.
2. Create a Batch job definition from `aws.batch` (`vcpus`, `memory_mib`, `attempts`,
   `timeout_seconds`, log group `aws.log_group`, job role `aws.iam_role_name` with read/write on
   the S3 prefix of the DVC remote). `service: batch-fargate` jobs run on a Fargate compute
   environment; `batch-ec2` jobs (long wall clock, or `resources.docker_socket: true`) need an
   EC2-backed environment.
3. Container command: the manifest's `command` argv as-is (the image has no `ENTRYPOINT`), with
   `RUPTURE_DVC_REMOTE_URL` and the other `env` names injected from Secrets Manager / SSM.
   **DVC transfer happens outside the job container**: the image carries no `dvc`, so the
   deployer pulls `inputs` onto the job's volume before the container starts (an init container
   or a step with `dvc` installed, or `aws s3 sync` against the same prefixes) and pushes
   `outputs` after it exits. This wrapper is a description; none of it has been exercised.
4. Schedule (where `schedule` is not null) with EventBridge Scheduler using the cron in UTC; the
   `issue-forecast` job is idempotent per `(region, issue time)` so retries are safe.

`oq-classical` is the exception: it drives `openquake/engine:3.26.2` through the docker CLI, so
the job container needs `/var/run/docker.sock` mounted and a docker CLI available (an EC2 job
with the socket mounted and the CLI installed on top of the rupture image, or — simpler — run
`openquake/engine:3.26.2` as the job's own image over a staged `/work` directory on EFS and run
`rupture` afterwards to parse `out/hazard_curve-*.csv`). Neither has been exercised.

## Elsewhere

Kubernetes: one CronJob or Job per manifest (`image`, `args: command`, resources from
`resources`, env from a Secret). Plain VM: `uv sync && rupture ...` under a systemd timer with the
same cron. Nothing in the manifests is AWS-specific outside the `aws:` block.

## Local development with compose

```bash
docker compose -f infra/docker/compose.yml build
docker compose -f infra/docker/compose.yml run --rm rupture rupture --version
RUPTURE_API_KEYS=dev-key docker compose -f infra/docker/compose.yml up -d api
curl -s localhost:8000/health | python -m json.tool
docker compose -f infra/docker/compose.yml up -d openquake      # WebUI http://127.0.0.1:8800
uv run rupture hazard demo                                       # from the host, uses docker run
```

The compose file mounts only `src/`, `contracts/` and `data/` (mounting the whole checkout over
`/app` would hide the image's venv at `/app/.venv`). It has not been brought up anywhere yet.

## CI

`.github/workflows/ci.yml`: the `offline` job on every push and pull request; `hazard-integration`
(pull the pinned engine image, `rupture hazard check`, `make validate-hazard`, `pytest
tests/integration/hazard -m integration`, upload the work directory on failure) on manual dispatch
and on pushes to `main`. That job sets `RUPTURE_HAZARD_REQUIRE=1`, so a Docker-unavailable skip
fails it instead of passing silently.

Building the rupture image in CI is **not wired yet**, and neither is the smoke test that would
prove the `api` target serves: build `--target api`, run it with a throwaway `RUPTURE_API_KEYS`,
curl `/health` and one authenticated route on each surface. Until that exists, the image's
servability is a hand review plus the static checks in
`tests/unit/aftershock/test_deployment_image.py`.
