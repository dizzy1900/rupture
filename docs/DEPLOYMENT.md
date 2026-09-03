# Deployment

rupture does not predict earthquakes. This document describes the deployment unit (one plain
Docker image), the portable job manifests, and how to point them at AWS Batch/ECS or anything
else. Decisions: ADR-0016 (image + manifests), ADR-0011 and ADR-0030 (OpenQuake engine image).

## What is provided

| Artifact | Purpose |
|---|---|
| `infra/docker/Dockerfile` (+ `Dockerfile.dockerignore`) | multi-stage build of the locked `uv` environment and the `rupture` CLI on `python:3.12-slim`; non-root user; OCI labels with the git sha |
| `infra/docker/compose.yml` | local development: `rupture` (`src/`, `contracts/`, `data/` mounted into `/app`) next to `openquake/engine:3.26.2` (named volume `oqdata`, WebUI on 127.0.0.1:8800). **Unexercised**: never brought up (no Docker here) |
| `infra/jobs/*.yaml` + `schema.json` + `README.md` | five portable job manifests with `aws:` annotations, validated in the unit suite |
| `infra/jobs/examples/turkiye-eaf-classical.json` | example `ClassicalPSHAJob` input (not run) |

## What is not provided

- No Terraform, CDK, CloudFormation or Kubernetes manifests; no hosted platform of any kind
  (non-negotiable 6). The `aws:` blocks are annotations a deployer reads, not infrastructure code.
- No scheduler implementation; `docs/SCHEDULER.md` (Phase 2B) describes the intended daily run.
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
  `contracts/`, `data/regions/`.
- Stage 1 installs `uv` from `ghcr.io/astral-sh/uv:0.11.7`, syncs dependencies from the lock
  (`--locked --no-dev`, `git` present for the pinned ETAS dependency), then installs the project.
  Stage 2 copies the venv, `src/`, `contracts/` and `data/regions/` (tracked via
  `data/regions/.gitkeep` until Phase 2A populates it); runs as `rupture` (uid 10001). There is
  **no `ENTRYPOINT`**: the container command is the full argv (`rupture ...`), exactly as the job
  manifests' `command` lists it; the default `CMD` is `rupture --help`.
- Inputs and outputs live on volumes (`/app/data`, `/app/baselines`, `/app/reports`) or come and
  go through DVC; the image contains no data and no credentials. Configuration is environment
  variables named in `.env.example` (`docs/CREDENTIALS.md`).
- Labels: `org.opencontainers.image.revision=<GIT_SHA>`, `...created`, `...source`, `...licenses`.

The OpenQuake engine is a second, public image (`openquake/engine:3.26.2`); rupture's image drives
it through the host's `docker` CLI and does not contain it.

## Job manifests

See `infra/jobs/README.md` for field semantics. In one sentence: `image` + `command` is what runs
(the `command` is the exact `rupture ...` verb from `CLAUDE.md`), `inputs`/`outputs` are DVC paths
with `${RUPTURE_DVC_REMOTE_URL}/...` URIs, `resources` and `schedule` are sizing and cadence, `env`
lists variable names, and `aws:` is an annotation.

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
fails it instead of passing silently. Building the rupture image in CI is not wired yet.
