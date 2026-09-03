# ADR-0030 — OpenQuake runner: docker CLI via subprocess, demo-first validation, skip semantics

- **Status:** accepted
- **Date:** 2026-09-03
- **Builds on:** ADR-0011 (pinned image), ADR-0016 (deployment unit and manifests)

## Context

ADR-0011 fixed the engine to the public image `openquake/engine:3.26.2` and required an adapter
behind the `HazardEngine` port. Implementing it raised three design questions: how rupture talks
to Docker, what the first proof that the adapter works should be, and what happens on a machine
without Docker (the development machine for Prompt 1 has none; GitHub's `ubuntu-latest` has it).

Facts about the image were verified on 2026-09-03 from the `engine-3.26` branch of
`gem/oq-engine` (`docker/Dockerfile.engine`, `docker/scripts/oq-start.sh`, `setup.py`,
`openquake/commands/{engine,export}.py`, `openquake/server/db/actions.py`) and the manual: the
image runs as `openquake` (uid 1000), `HOME=/home/openquake`, venv at `/opt/openquake`; its
`ENTRYPOINT` is the *relative* `./oq-start.sh`, which starts the dbserver, waits for port 1908 and
then `exec`s the command when no TTY is attached; `oq engine --run <job.ini>` runs a calculation;
`oq export hcurves -e csv -d <dir>` exports the hazard curves of the last calculation (calc id
`-1` resolves to the latest job in the dbserver); the demos are installed as setuptools
`data_files` relative to the venv prefix. The install path of the demos inside the image
(`/opt/openquake/demos`) is inferred from that mechanism, not observed.

## Decision

1. **Docker through the `docker` CLI and `subprocess`**, never the Docker SDK (no new Python
   dependency) and never `openquake.*` imports. The runner is an injectable callable so staging,
   argv construction and parsing are unit-tested offline with a fake that writes the engine's own
   QA expected CSVs into the work directory.
2. **One bind mount, absolute paths, no `-w`.** The work directory is mounted at `/work`; the
   container is invoked as `docker run --rm --name rupture-oq-<id> -v <work>:/work <image>
   bash -c '<script>'` with the script `set -e; umask 000; mkdir -p /work/out; oq engine --run
   /work/job.ini; oq export hcurves -e csv -d /work/out`. `-w /work` is not used because it would
   break the image's relative entrypoint. Run and export happen in the **same** container because
   `--rm` discards the datastore. The host makes the work directory world-writable and the
   container runs with `umask 000` so uid 1000's files can be read and deleted by the host user
   (uid 1001 on GitHub runners). stdout/stderr go to `<work>/oq.log`; a timeout kills the named
   container.
3. **Demo first.** The gate `validate-hazard`, the CLI `rupture hazard demo` and the integration
   test all run the engine's bundled `demos/hazard/AreaSourceClassicalPSHA`, copied out of the
   image in a first container (`cp -R`, with a `find / -path '*/demos/<demo>/job.ini'` fallback
   when the assumed demos directory is wrong) and run in a second. Passing means: the pinned
   image pulls, the entrypoint and dbserver work headless, `oq engine --run` and `oq export`
   behave as read from the source, and the CSV parser accepts real 3.26 output. Only then is a
   rupture-authored `ClassicalPSHAJob` worth running.
4. **Skip semantics.** `available()` returns `(False, reason)` when the `docker` binary is
   missing or `docker info` fails. The gate then returns `GateStatus.SKIPPED` with the reason
   `"Docker not available: <why>; CI job hazard-integration runs this demo"`; the CLI prints
   `SKIPPED: ...` and exits 3; the integration test `pytest.skip`s with the same reason. There is
   no code path that reports success without a container having run. A failed run is `FAILED`
   with the last lines of `oq.log` in the findings.
5. **Parsing contract.** `hazard_curve-*.csv` exports are parsed from their `#` metadata line
   (`kind`, `imt`, `investigation_time`, `generated_by`) and `poe-<IML>` columns; `mean` curves are
   published when present. `HazardCurveSet.engine_version` is the version the header reports;
   `job_hash` is sha256 over `job.ini` and every staged input; `Provenance.sha256` is the digest
   of the exported CSV text; `source_url` is `docker://<repo digest>`.
6. **CI.** The `hazard-integration` job runs on `workflow_dispatch` and on pushes to `main`,
   after the offline job: `docker pull`, `make validate-hazard`, the integration tests, and an
   artifact upload of the work directory on failure.

## Consequences

- The adapter is fully exercised offline except for the container itself; the container path is
  exercised in CI on every push to `main`. `RELEASE_STATUS.md` must say whether that job has run.
- The assumed demos path is a single constant (`RUPTURE_OPENQUAKE_DEMOS_DIR` overrides it) with a
  `find` fallback, so a wrong guess costs seconds, not a failure.
- Two container starts per demo run (copy, then run); acceptable for a proving run.
- Fargate cannot run the OpenQuake job (no docker socket); the `oq-classical` manifest is
  annotated `batch-ec2`.

## Alternatives considered

- **Docker SDK for Python.** Rejected: a new dependency for four CLI invocations.
- **`--user $(id -u)` instead of chmod + umask.** Rejected: the image's `HOME` and `oqdata` are
  owned by uid 1000 and `getpass.getuser()` in the engine needs a passwd entry; more moving parts.
- **Export with `oq engine --run --exports csv` into `export_dir`.** Viable, but the demo's
  `job.ini` has no `export_dir`, so exports would land in the container's `$HOME`; the explicit
  `oq export ... -d /work/out` is uniform for demo and rupture jobs.
- **Start with a rupture-authored job instead of the demo.** Rejected: no verified source model
  is present in this worktree, and a first failure would be impossible to attribute.
