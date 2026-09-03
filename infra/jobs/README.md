# infra/jobs — portable job manifests

rupture does not predict earthquakes. These manifests describe how its batch jobs run at scale;
they are documentation-grade (ADR-0016), validated for shape by
`tests/unit/hazard/test_job_manifests.py` against [`schema.json`](schema.json), and not required
by anything that runs locally: every `command` is the same `rupture ...` verb you run with
`uv run`.

| Manifest | Command | Schedule | Needs |
|---|---|---|---|
| `build-catalog.yaml` | `rupture catalog build --region <r> --from <from> --to <to>` | monthly (informational) | network to ComCat/ISC/GCMT |
| `fit-etas.yaml` | `rupture forecast fit --model etas --region <r> --cutoff <cutoff>` | on demand | `data/catalogs/<r>` |
| `issue-forecast.yaml` | `rupture forecast issue --model etas --region <r> --horizon 30d --issue <t>` | daily (informational) | catalogue + fit |
| `evaluate-schedule.yaml` | `rupture evaluate schedule --region <r> --model etas --from <from> --to <to> --step 30d` | on demand | catalogue + fit; long wall clock |
| `oq-classical.yaml` | `rupture hazard classical --job <path> --work-dir reports/hazard/<job-id>` | on demand | docker socket on the host; ESHM20 inputs; **not run yet** |

## Fields

- `manifest_version`: `"0"`.
- `name`: equals the file stem.
- `image`: `${RUPTURE_IMAGE}` — the image built from `infra/docker/Dockerfile` and pushed to a
  registry of your choice (the tag is the git sha; see `docs/DEPLOYMENT.md`).
- `command`: argv, one token per list item. Angle-bracket tokens (`<r>`, `<from>`, `<t>`,
  `<path>`) are placeholders the submitter fills in.
- `inputs` / `outputs`: repository-relative paths with the DVC remote URI they are pulled from or
  pushed to (`${RUPTURE_DVC_REMOTE_URL}/<path>`). `kind` is `dvc` (tracked by `dvc.yaml`),
  `source` (git-tracked, listed for completeness) or `report`.
- `resources`: `cpu`, `memory_gib`, `timeout_minutes`, `gpu: none`, and `docker_socket: true`
  only for the OpenQuake job, which drives a second container.
- `schedule`: cron in UTC with a note, or `null`. Nothing here is wired to a scheduler;
  `docs/SCHEDULER.md` (Phase 2B) describes the intended daily issuance.
- `env`: names only, all present in `.env.example`. Values come from the platform's secret store.
- `aws`: a Batch/ECS sketch — `service` (`batch-fargate` for network-only jobs, `batch-ec2` when a
  docker socket or a long wall clock is needed), `batch.job_definition_name`, `vcpus`,
  `memory_mib`, `attempts`, `timeout_seconds`, an S3 prefix under the DVC remote bucket, an IAM
  role **name** placeholder (`rupture-batch-job-role`) and a CloudWatch log group. Every other
  platform ignores this block.

## Translating to a platform

The manifests contain what a job definition needs and nothing platform-specific in the top-level
keys. For AWS Batch: create one job definition per manifest from `aws.batch`, mount nothing (DVC
pulls inputs at start: `dvc pull <inputs> && <command> && dvc push <outputs>` is the container
command wrapper the deployer writes), pass `env` names from Secrets Manager / SSM, and use the IAM
role for S3 read/write on the DVC remote prefix. For cron, Kubernetes or a plain VM the same
fields map onto a CronJob or a systemd timer. There is no Terraform or CDK in this repository.

## Example job input

`examples/turkiye-eaf-classical.json` is a `ClassicalPSHAJob` for a coarse 50-year classical PSHA
over the East Anatolian Fault bounding box from ESHM20 (ADR-0008). It has **not** been run: the
ESHM20 files it points at are fetched by `adapters/sources/openquake_sources.py` and their exact
file names must be confirmed against what that adapter writes. See `docs/HAZARD.md`.
