# ADR-0020: A `GroundMotionEngine` port with two adapters

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

Prompt 2's loss layer needs ground-motion fields for scenarios and for stochastic event sets. The
authoritative producer is the OpenQuake engine, pinned in ADR-0011. But OpenQuake cannot run on
this project's development machine at all:

- `openquake.engine` depends on `gdal`, which publishes only a source tarball; it fails to build
  on arm64 macOS.
- `openquake.hazardlib` is not published as a separate distribution, so the scientific core cannot
  be installed on its own.
- The `openquake/engine` Docker image is single-platform `linux/amd64`; under emulation on arm64
  the bundled demo exceeds the run timeout (ADR-0011 addendum).

If ground motion could only come from the container, then `validate-risk`, `underwriting-check`
and the whole loss layer would be unrunnable and untestable outside CI, on a project whose stated
convention is that every gate runs offline from a fresh clone.

## Decision

Introduce a `GroundMotionEngine` port with two adapters.

1. **`openquake_docker`** — authoritative. Scenario and event-based calculations through the pinned
   image. Runs in CI (amd64) and on any amd64 host.
2. **`native_gsim`** — a direct evaluator for a small set of **published** GSIMs, implemented in
   rupture and **verified against OpenQuake's own committed test vectors**
   (`gem/oq-engine`, `openquake/hazardlib/tests/gsim/data`, 184 GSIM directories), carried as
   fixtures with provenance. Runs anywhere.

Rules that keep this honest:

- A GSIM ships only if its implementation reproduces OpenQuake's published expected values within
  a stated tolerance. A GSIM that cannot be verified against a fetched vector table is not shipped.
  The verification is a test, not a claim in prose.
- Every `GroundMotionField` records `engine`, `engine_version` and `gsim`. Every report says which
  engine produced its numbers.
- Where both engines can run, CI cross-checks them on the same rupture and sites.

## Consequences

- The loss layer is developable and testable on any machine, and the offline-gate convention
  survives contact with a hard platform constraint.
- rupture now carries a small amount of GSIM implementation, which is a maintenance cost and a
  correctness risk. The cost is bounded by shipping few GSIMs; the risk is bounded by verifying
  each against the reference implementation's own vectors.
- Two engines can disagree. That is a finding to report, not a bug to hide: the cross-check exists
  precisely to surface it.

## Alternatives considered

- **Container only.** Rejected: it makes the headline deliverable unrunnable on the development
  machine and unverifiable offline.
- **Hand-rolled GMPEs without verification vectors.** Rejected outright: unsourced ground-motion
  science presented as usable is exactly the fabrication the non-negotiables forbid.
- **Install GDAL via system packages.** Rejected as a project dependency: it makes a fresh clone
  depend on non-Python system state, which the conventions rule out.
