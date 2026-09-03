# ADR-0016 — Deployment unit is a plain Docker image; portable job manifests with `aws:` annotations

- **Status:** accepted
- **Date:** 2026-09-03

## Context

rupture's batch jobs (catalogue builds, ETAS fits, forecast issuance, schedule evaluation,
OpenQuake runs) must run on a laptop, in CI and at scale on cloud compute, without making any
hosted platform a dependency (non-negotiable 6). The brief specifies a plain Docker image as the
unit and portable job manifests in `infra/jobs/*.yaml`, AWS-annotated.

## Decision

- **One image**, built from `infra/docker/Dockerfile`: the locked `uv` environment plus the
  `rupture` CLI. It contains no credentials and no data; inputs and outputs go through DVC paths
  or mounted volumes. The OpenQuake engine is a separate pinned public image (ADR-0011) that
  rupture drives; it is not baked in.
- **Job manifests** `infra/jobs/{build-catalog,fit-etas,issue-forecast,evaluate-schedule,oq-classical}.yaml`
  in a small portable schema: `name`, `image`, `command` (the exact `rupture ...` invocation),
  `inputs`/`outputs` (DVC paths), `resources` (cpu, memory, optional gpu = none), `schedule`
  (cron-style, informational), `env` (variable names only, never values), and an **`aws:`
  annotation block** (Batch/ECS job definition sizing, S3 bucket/prefix, IAM role *name*, region)
  that an AWS deployer reads and every other platform ignores.
- Manifests are documentation-grade and validated for shape in tests; nothing in them is required
  to run the same `command` locally with `uv run`.
- `infra/docker/compose.yml` is for local development only (rupture + engine side by side).
- The scheduler is **described** in `docs/SCHEDULER.md` (Phase 2B), not implemented in Prompt 1.

## Consequences

- The same image and command run everywhere; platform specifics are annotations, not code.
- No lock-in: moving off AWS means editing an annotation block, not the pipeline.
- Someone deploying must still write the platform glue (a Batch job definition, a cron trigger);
  the manifests tell them exactly what to write.
- Image size includes the scientific stack (pycsep, geopandas); acceptable for batch jobs.

## Alternatives considered

- **Terraform/CDK modules for AWS in the repo.** Rejected for Prompt 1: real infrastructure code
  for one provider is more than "portable manifests" and needs an account to test.
- **Kubernetes manifests as the portable format.** Rejected: assumes a cluster; the plain YAML
  schema here is smaller and can be translated to Kubernetes, Batch or cron alike.
- **A hosted workflow service (managed Airflow, Step Functions) as the source of truth.**
  Rejected: hosted-platform dependency.
