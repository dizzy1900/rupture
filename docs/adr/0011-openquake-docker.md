# ADR-0011 — OpenQuake engine via the pinned Docker image `openquake/engine:3.26.2`

- **Status:** accepted
- **Date:** 2026-09-03

## Context

F0 and F2 use the OpenQuake engine (Pagani et al. 2014). Installing the engine into rupture's own
Python environment is impractical (it pins its own scientific stack and Python version and is
AGPL-3.0, whereas rupture is Apache-2.0). The engine publishes Docker images; tag `3.26.2` was
verified on Docker Hub on 2026-09-03. Docker is **not** installed on the developer machine used
for Prompt 1; GitHub's `ubuntu-latest` runners have it.

## Decision

- Run the engine only as the pinned public image `openquake/engine:3.26.2` (overridable via
  `RUPTURE_OPENQUAKE_IMAGE` for upgrade testing; changing the pin is an ADR).
- `adapters/hazard/openquake_docker.py` implements the `HazardEngine` port
  (`ports/hazard_engine.py`): the typed job models `ClassicalPSHAJob` and
  `ScenarioGroundMotionJob` (defined next to the port) are rendered to `job.ini` + input files in
  a mounted work directory; `run_classical` invokes `oq engine --run` in the container and parses
  `oq export hcurves` CSV into a `HazardCurveSet`; `run_scenario` returns the directory of
  exported ground-motion fields. rupture never imports `openquake.*`.
- `available()` returns `(False, reason)` when the Docker daemon is absent or the image cannot
  be pulled; `make validate-hazard` / `rupture hazard demo` then report `SKIPPED` **with that
  printed reason**. They never report success without running.
- CI job `hazard-integration` runs the engine's bundled demo
  (`demos/hazard/AreaSourceClassicalPSHA`); it is manual-dispatch only until the adapter lands
  in Phase 2C, which flips it to run on pushes to `main` as well. This is the proving ground for
  the adapter. `RELEASE_STATUS.md` states where the hazard gate last ran.
- Developers who want local runs install Docker Desktop or colima; this is documented, not
  assumed.

## Consequences

- Clean licence separation (AGPL engine in its own container; Apache-2.0 adapter).
- Exact reproducibility of hazard numbers by image tag (and digest, recorded in gate output).
- Local `make validate-rupture` is green with the hazard gate skipped-with-reason on machines
  without Docker; `make promote` prints the skip so it cannot be missed.
- Running the engine adds a ~1 GB image pull (well under the 5 GB rule) and container start-up
  time to integration runs.

## Alternatives considered

- **Install `openquake.engine` in the rupture venv.** Rejected: dependency and Python-version
  conflicts, licence entanglement.
- **A hosted OpenQuake service.** Rejected: hosted-platform dependency (non-negotiable 6).
- **Skip hazard until Prompt 2.** Rejected: the adapter and demo are Prompt 1 deliverables; the
  gap is Docker locally, and CI covers it.
