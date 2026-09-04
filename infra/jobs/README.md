# infra/jobs — portable job manifests

rupture does not predict earthquakes. These manifests describe how its batch jobs run at scale;
they are documentation-grade (ADR-0016), validated for shape by
`tests/unit/hazard/test_job_manifests.py` against [`schema.json`](schema.json), and not required
by anything that runs locally: every `command` is an invocation you can also run with `uv run`.

| Manifest | Command | Status | Core-hours | Schedule |
|---|---|---|---|---|
| `build-catalog.yaml` | `rupture catalog build --region <r> --from <from> --to <to>` | run | 0.5 (guess) | monthly (informational) |
| `fit-etas.yaml` | `rupture forecast fit --model etas --region <r> --cutoff <cutoff>` | run | 0.2 (extrapolated) | on demand |
| `issue-forecast.yaml` | `rupture forecast issue --model etas --region <r> --horizon 30d --issue <t>` | run | 0.02 (extrapolated) | daily (informational) |
| `evaluate-schedule.yaml` | `rupture evaluate schedule --region <r> --model etas --from <from> --to <to> --step 30d` | run | 1.0 (**measured**) | on demand |
| `select-ntpp.yaml` | `python -m rupture.commands.challenger ntpp select --region <r> …` | run | 0.3 (extrapolated) | on demand |
| `train-ntpp.yaml` | `python -m rupture.commands.challenger ntpp fit --region <r> …` | run | 0.1 (extrapolated) | on demand |
| `run-ensemble-protocol.yaml` | `python -m rupture.models.ensemble.protocol_runner --region <r>` | run | 4 (extrapolated) | on demand |
| `oq-classical.yaml` | `rupture hazard classical --job <path> --work-dir reports/hazard/<job-id>` | **not-run** | 16 (guess) | on demand |
| `stochastic-event-set.yaml` | `rupture forecast simulate --model etas --region <r> --n-events 10000` | **command-not-implemented** | 1.0 (guess) | on demand |

The three learned challengers are covered by three manifests, not four: the neural
temporal point-process challenger has its own `select` and `fit` verbs, while the gridded ConvLSTM
and the log-linear ensemble have no standalone training entry point at all — they are trained
inside `run-ensemble-protocol.yaml`, which also runs the protocol that scores them.

## Fields

- `manifest_version`: `"0"`.
- `name`: equals the file stem.
- `status`: `run`, `not-run` or `command-not-implemented` — see [Status](#status) below.
- `image`: `${RUPTURE_IMAGE}` — the image built from `infra/docker/Dockerfile` and pushed to a
  registry of your choice (the tag is the git sha; see `docs/DEPLOYMENT.md`).
- `command`: argv run as the container command, one token per list item (the image has no
  `ENTRYPOINT`, only a default `CMD`). Either a mounted CLI verb, starting with the token
  `rupture`, or the module form `python -m rupture.<module> …` for a training entry point that
  `src/rupture/cli.py` has not mounted yet. Angle-bracket tokens (`<r>`, `<from>`, `<t>`,
  `<path>`) are placeholders the submitter fills in.
- `inputs` / `outputs`: repository-relative paths with the DVC remote URI they are pulled from or
  pushed to (`${RUPTURE_DVC_REMOTE_URL}/<path>`). `kind` is `dvc` (tracked by `dvc.yaml`),
  `source` (git-tracked, listed for completeness) or `report`.
- `resources`: `cpu`, `memory_gib`, `timeout_minutes`, the three core-hour fields below,
  `gpu: none`, and `docker_socket: true` only for the OpenQuake job, which drives a second
  container.
- `schedule`: cron in UTC with a note, or `null`. Nothing here is wired to a scheduler;
  `docs/SCHEDULER.md` (Phase 2B) describes the intended daily issuance.
- `env`: names only, all present in `.env.example`. Values come from the platform's secret store.
- `aws`: a Batch/ECS sketch — `service` (`batch-fargate` for network-only jobs, `batch-ec2` when a
  docker socket or a long wall clock is needed), `batch.job_definition_name`, `vcpus`,
  `memory_mib`, `attempts`, `timeout_seconds`, an S3 prefix under the DVC remote bucket, an IAM
  role **name** placeholder (`rupture-batch-job-role`) and a CloudWatch log group. Every other
  platform ignores this block.

## Core-hour estimates

Non-negotiable 7 is *ask before paid API calls*. A confirmation needs something concrete to
confirm, so every manifest states what one run costs and how it knows. Three required fields:

- **`core_hours_estimate`** — expected cost of ONE invocation in CPU-core-hours, defined as
  `(user + system CPU seconds) / 3600` summed over every core the job uses. It is a **cost**, not
  a wall clock and not a ceiling. `cpu × timeout_minutes / 60` is the ceiling, and the test suite
  requires the estimate to stay at or below it. The two differ by a lot on purpose: `fit-etas` is
  allowed 24 core-hours and expected to use 0.2.
- **`core_hours_basis`** — `measured`, `extrapolated` or `guess`.
  - `measured`: this job, as written, was timed, and the note cites the log.
  - `extrapolated`: something comparable was timed, and the note gives the arithmetic that carries
    it here.
  - `guess`: nothing comparable was timed. The note says so and gives the reasoning.
- **`core_hours_note`** — the basis in prose: which run, on what host, for which region and
  placeholder values, and what was assumed. The test suite requires a `measured` or `extrapolated`
  note to name a path under `reports/`, `baselines/` or `tests/fixtures/`, and a `guess` to admit
  in the note that it is one.

Every figure in this directory traces to one of three sources: the timed schedule runs under
`reports/protocol/*.log`, the timed anchor fit of the committed NTPP fixture
(`tests/fixtures/models/ntpp-fit-2019-07-01`, 7.4 CPU-seconds for 214 events over 538 epochs on an
arm64 laptop), or an argued guess. One is measured; four are extrapolated; three are guesses. All
timings come from one arm64 laptop, single-threaded in practice, so they are indicative for a
Batch queue rather than authoritative on one.

**What would make more of them measured.** Nothing in the tree records how long a run took: the
ensemble protocol runner logs each fit's duration to stdout and drops it, and the committed
schedule reports (`reports/challenger/<r>/schedule-*.json`,
`reports/protocol/<r>/eval/schedule-*.json`) carry no elapsed time at all. Adding an
`elapsed_seconds` to those reports, and to the `RunRecord` outputs written through the Tracker
port (ADR-0023), would turn every `extrapolated` and `guess` here into a `measured` on the next
run. Those files belong to other slices; see `docs/DEPLOYMENT.md`.

## Status

`status` is a claim about *this tree*, and the test suite checks it against the tree:

- `run` — the entry point exists and has been executed at least once here.
- `not-run` — the entry point exists; nothing has run it. `oq-classical` is the case: OpenQuake's
  image is amd64-only and the development host is arm64 (ADR-0011 addendum).
- `command-not-implemented` — the entry point named in `command` does not exist yet, so the
  manifest is a sized proposal and nothing can run it. `stochastic-event-set` is the case: there is
  no `rupture forecast simulate` verb. The manifest is committed anyway so the compute is on the
  record before anyone pays for it.

`test_status_matches_whether_the_entry_point_exists` resolves each `rupture …` command against the
typer application and each `python -m` command against the module path, and fails if the status
disagrees. So the day someone adds `rupture forecast simulate`, or mounts the challenger sub-app,
the suite says the manifests need updating rather than letting them drift.

**Why two manifests use the module form.** `src/rupture/cli.py` does not mount
`rupture.commands.challenger` (`app.add_typer(challenger.app, name="challenger")` is the one line
missing; see the note at the top of that module), and the ensemble protocol runner is an argparse
`main()` with no verb at all. Both are runnable today as written. The module form is a statement
that the verb is missing, not a substitute for adding it.

## Translating to a platform

The manifests contain what a job definition needs and nothing platform-specific in the top-level
keys. For AWS Batch: create one job definition per manifest from `aws.batch`, run `command` as
the container command, pass `env` names from Secrets Manager / SSM, and use the IAM role for S3
read/write on the DVC remote prefix. **DVC transfer happens outside the job container**: the
rupture image is built `--no-dev` and carries no `dvc`, so `inputs` must be pulled onto the job's
volume before the container starts and `outputs` pushed after it exits (an init step or sidecar
with `dvc` installed, or `aws s3 sync` against the same prefixes). None of this has been
exercised. For cron, Kubernetes or a plain VM the same fields map onto a CronJob or a systemd
timer. There is no Terraform or CDK in this repository.

## Experiment tracking

Nothing in these manifests configures a tracker. Every job writes its run records through the
`Tracker` port to a local JSONL log under its `outputs` (ADR-0023); a W&B mirror is opt-in through
`WANDB_API_KEY` and the `wandb` extra. `WANDB_API_KEY` is deliberately **not** listed in any
`env` block: `env` names must all exist in `.env.example`, and that variable is not there yet.

## Example job input

`examples/turkiye-eaf-classical.json` is a `ClassicalPSHAJob` for a coarse 50-year classical PSHA
over the East Anatolian Fault bounding box from ESHM20 (ADR-0008). It has **not** been run: the
ESHM20 files it points at are fetched by `adapters/sources/openquake_sources.py` and their exact
file names must be confirmed against what that adapter writes. See `docs/HAZARD.md`.
