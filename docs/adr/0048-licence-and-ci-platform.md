# ADR-0036: Apache-2.0 as the repository licence, GitHub Actions as the CI platform, and a gate-coverage ratchet

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

Two stack decisions were made when the repository was bootstrapped and were never written down.
ADR-0001 fixed the self-contained conventions; ADR-0003 fixed the Python toolchain and mentions
`uv sync --locked` "in CI" without saying what CI is. ADRs 0007, 0011 and 0033 discuss *third-party*
licences (CC-BY-SA-4.0 for the GEM faults, AGPL for the OpenQuake engine, the GSIM coefficient
provenance) but none records rupture's own. A contributor reading `docs/adr/` cannot find the
rationale for either, which is exactly the hole an ADR log exists to close.

A third decision is new and belongs here because it is about CI rather than about any one gate: for
most of Prompt 2, four of the ten registered gates (`cascade`, `risk`, `aftershock`, `challengers`)
ran only when someone typed `make`. `make promote` was the only place all ten ran together, and it
is manual. A gate nothing runs is a gate that rots, and it rots silently.

## Decision

**1. The repository is licensed Apache-2.0.** `LICENSE` holds the full text and
`pyproject.toml` declares it. The reasons, in order of weight:

- rupture publishes *contracts* meant to be copied into other repositories — `serac` already does
  this, and any downstream decision or financial layer is expected to. A permissive licence is the
  only kind that lets a schema be copied into a codebase of unknown licence without an argument.
- The express patent grant (§3) matters for a repository that implements published ground-motion
  and ground-failure models.
- The sibling `serac` is Apache-2.0, and the two exchange files constantly; matching removes a
  question nobody needs to answer twice.
- **A share-alike licence was not an option for the whole repository even if we had wanted one**,
  because it would have collided with what rupture consumes rather than what it publishes. The GEM
  Global Active Faults database is CC-BY-SA-4.0 and its derived GeoParquet inherits share-alike
  (ADR-0007); that obligation is scoped to that artefact and does not propagate to code that never
  redistributes it. Keeping the code permissive keeps that boundary legible.

Third-party licences are not affected by this choice and are recorded per source in
`docs/DATA_SOURCES.md`: CC-BY-SA-4.0 (GEM faults), CC-BY-4.0 (ESHM20), CC0-1.0 (USGS
ground-failure), AGPL-3.0-or-later (OpenQuake engine and the GSIM verification tables carried from
it), public domain (USGS, FEMA).

**2. CI is GitHub Actions**, one workflow at `.github/workflows/ci.yml`, for one reason that
outweighs the others: rupture is hosted on GitHub, and adding a second hosted service would break
non-negotiable 6 ("no private repo, internal package or hosted platform is a dependency") in
spirit — the fewer hosted things the project needs, the better. The workflow is deliberately thin.
Every step is `make <target>`, so the whole of CI runs identically on a laptop, and moving to
another runner means rewriting a YAML file, not rediscovering what the checks were.

**3. Every registered gate must have a CI step, enforced mechanically.** The offline job runs the
nine gates that need neither network nor Docker plus `make underwriting-check`; the
`hazard-integration` job runs `validate-hazard` in the pinned container on `main`. The last step of
the offline job imports `GATES` from `src/rupture/validation/registry.py`, compares it against the
list of gates the workflow claims to cover, and **fails if they disagree in either direction** — a
registered gate with no step, or a step for a gate that no longer exists. Registering a gate and
forgetting to run it is now a build failure rather than a discovery six months later.

**4. CI runs on every push to any branch, and on every pull request.** The brief asks for the
checks "on push and PR"; narrowing `push` to `main` satisfies the letter for `main` only and leaves
a contributor pushing a feature branch with no signal until they open a pull request. The
concurrency group cancels superseded runs on the same ref, so the cost is one cancelled run rather
than a queue.

## Consequences

- Anyone may copy `contracts/*.json` into any codebase. That is the intent.
- The share-alike obligation on the GEM-derived fault GeoParquet stands on its own and must be
  respected wherever that artefact is redistributed; the repository licence does not override it.
- CI is portable in the way that matters (every step is a make target) and not in the way that does
  not (the YAML is GitHub's dialect).
- The four Prompt 2 gates now run on every push. They cost seconds — cascade 2 s, risk 2 s,
  aftershock 7 s, challengers 2 s — because they read committed evidence rather than refitting
  anything.
- The ratchet has a maintenance cost: adding a gate means editing `ci.yml` as well as dropping
  `mk/<name>.mk`. That is the point.

## Alternatives considered

- **MIT.** Rejected: no express patent grant, and Apache-2.0's `NOTICE` mechanism is a better fit
  for a repository that carries third-party attributions.
- **AGPL-3.0**, matching the OpenQuake engine. Rejected: rupture *drives* OpenQuake as a separate
  process in a container and never imports `openquake.*` (ADR-0011), so it is not a derivative
  work; and copyleft on the published contracts would defeat their purpose.
- **Running `make validate-rupture` as a single CI step** instead of the per-gate steps and the
  ratchet. Rejected: the aggregate includes `validate-hazard`, which on a Docker-capable runner
  would pull the OpenQuake image and run the demo inside the *offline* job, duplicating the
  integration job and adding tens of minutes to every pull request.
- **Leaving the Prompt 2 gates hand-run** and recording that in `RELEASE_STATUS.md` instead.
  Rejected: an honest ledger entry about an unrun check is still an unrun check, and these four run
  in eleven seconds between them.
