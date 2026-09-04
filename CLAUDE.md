# CLAUDE.md — working rules for rupture

rupture does not predict earthquakes.

rupture is a standalone, open-source probabilistic seismic forecasting and cascade-loss model
(`github.com/dizzy1900/rupture`). It has no parent organisation, no internal platform and no
inherited conventions; the conventions are defined here and in `docs/adr/`. Its only sibling is
`serac` (`github.com/dizzy1900/serac`), consumed through published file contracts, never as a code
dependency. Every agent and contributor working in this tree is bound by this file.

## What rupture is and is not

Deterministic prediction of the time, place and magnitude of individual earthquakes has no
scientifically accepted method, and rupture will never claim one. rupture issues rate-based,
gridded forecasts and scores them against the operational ETAS baseline under time-forward,
likelihood-based tests in the manner of CSEP.

| Layer | Question answered | Method (settled) |
|---|---|---|
| F0 Long-term hazard | What is the exceedance probability of ground motion at a site over 50 years? | PSHA via OpenQuake engine, GEM source models and GMPEs |
| F1 Time-dependent seismicity forecast | Given the catalogue to date, what is the rate of M ≥ m events per cell over the next day / week / month / year? | ETAS (operational baseline); challenger models gated by CSEP tests |
| F2 Ground motion → loss | For a scenario or forecast, what is expected loss to a portfolio, and what is avoided by an intervention? | OpenQuake scenario/event-based risk; fragility and consequence functions; published avoided-loss contract |
| F3 Triggered cascades | What does a large event trigger — landslides, co-seismic ice avalanches, liquefaction — and where? | USGS ground-failure models; exposure overlays; shared discriminator with `serac` |

Prompt 1 built the foundations: catalogue infrastructure, the ETAS baseline, the CSEP evaluation
harness, the OpenQuake adapter, contracts and gates. Prompt 2 built the challenger models, the loss
layer (F2), the cascade layer (F3) and the operational aftershock service. **Both are complete as
of 2026-09-03**; `RELEASE_STATUS.md` is the authority on what actually ran, and this file is the
authority on the rules. No challenger was promoted, which is a result and not an omission.

## Non-negotiables

The seven items below are the brief's non-negotiables (`rupture-prompt-1-foundations.md`, section
"Non-negotiables"), reproduced word for word inside the blockquotes. **The brief itself is not
committed to this repository**, so the reproduction cannot be diffed against a source from inside a
clone; that is a limitation of this file, stated here rather than glossed. Everything outside a
blockquote — the make-target notes, the cross-references — is rupture's own editorial and is not
part of the quoted rule. An earlier revision of this file mixed the two, which is exactly the drift
verbatim reproduction exists to prevent.

1. > **No prediction claims.**

   Deterministic prediction of the time, place and magnitude of individual earthquakes has no
   scientifically accepted method, and rupture will never claim one (see "What rupture is and is
   not" above). `make validate-language` greps for banned phrasing.
2. > **No leakage.** All forecast evaluation is time-forward (pseudo-prospective) with a hard cut; any data after the cut is unavailable to the model. Assert this in tests with catalogue timestamps.
3. > **ETAS is a first-class citizen**, not a straw man. It must be fitted properly (magnitude of completeness, time-varying if warranted, region-specific) and its parameters and fit diagnostics published.
4. > **No fabricated data.** Adapters fetch or fail loudly; unit tests run offline on committed fixtures; unknowns are null.
5. > **Provenance on every record** (source, retrieval time, checksum, licence). Catalogue homogenisation steps are logged per event.
6. > **Self-contained repo conventions**: no private repo, internal package or hosted platform is a dependency. Define and document rupture's own conventions: DVC-versioned `data/` and `baselines/`, `src/validation/`, Makefile `validate-*`, `promote`, `underwriting-check`, honest `RELEASE_STATUS.md`, a plain Docker image as the deployment unit, and portable job manifests in `infra/jobs/*.yaml` (AWS-annotated) for scaled runs. Downstream consumers integrate through the versioned JSON Schemas in `contracts/`.
7. > **Ask before downloads > 5 GB or paid API calls.** Credentials via `.env`; documented in `docs/CREDENTIALS.md`.

## Repository conventions

Recorded as ADR-0001 and ADR-0002; summarised here.

- **Hexagonal layout** (see `README.md` § Layout). `src/rupture/domain/` holds pure pydantic v2
  models and imports nothing from any outer layer; `src/rupture/ports/` holds `Protocol` classes
  and imports only `domain`; `adapters/` implement ports. All three rules are import-linter
  contracts in `pyproject.toml` (`make lint` runs `lint-imports`) and fail CI. `commands/` holds
  the typer sub-applications (one per CLI noun), `pipelines/` the orchestration they call,
  `risk/`, `cascade/`, `models/` and `services/` the Prompt-2 layers, and `reporting/` the code
  that draws committed evidence into figures.
  **Two things the contracts do not cover, stated rather than implied.** The adapter-independence
  contract lists five families (`catalogs`, `sources`, `forecasting`, `evaluation`, `hazard`); the
  newer families — `groundmotion`, `exposure`, `vulnerability`, `cascade`, `storage` — are not in
  it. And nothing forbids `cascade` importing `models`, or `models` importing `pipelines`, which it
  already does in four places. Both are recorded in `RELEASE_STATUS.md` § Known gaps. Do not read
  a green `lint-imports` as a statement about those edges.
- **Tests** are split into `tests/unit` (offline; `make test` passes `--disable-socket
  --allow-unix-socket` so any network call fails), `tests/integration` (network or Docker; marked
  `integration`, opt-in via `make test-integration`) and `tests/contract` (JSON Schema round-trips
  and the fixtures shared with `serac`).
- **Fixtures are real slices**, never synthesised. Every fixture directory under `data/fixtures/`
  and `tests/fixtures/` carries a `provenance.json` and is never edited by hand; regenerate it with
  the adapter and re-record provenance instead. Some fixtures are third-party source files
  vendored verbatim (the USGS ground-failure reference implementation under
  `tests/fixtures/cascade/usgs_groundfailure/`, renamed `.py` → `.py.txt` so ruff and mypy skip
  it). Their `provenance.json` records the source URL, sha256 and the rule "never edited by hand".
  Because they are never edited, rupture's rules about the *contents* of rupture's own files — the
  no-`TODO` rule below included — do not apply to them.
- **Provenance fields** on every ingested record: `source`, `source_url`, `retrieved_at`, `sha256`,
  `licence`, `adapter_version`. Unknown values are `null`, never guessed.
- **Timestamps** are UTC and timezone-aware everywhere (ruff rule `DTZ` is on). Cutoffs and
  windows are half-open `[from, to)`.
- **Decisions are ADRs** in `docs/adr/` (index in `docs/adr/README.md`). A settled ADR is not
  relitigated in a PR; write a new ADR that supersedes it. The repository's own licence
  (Apache-2.0) and CI platform are ADR-0048; how report figures are produced is ADR-0049.
- **Honesty in `RELEASE_STATUS.md`.** Under-claim. If it did not run, say so, and say why.
- No `TODO` without an issue reference. One `TODO` exists in the tree and it is not rupture's:
  `tests/fixtures/cascade/usgs_groundfailure/jessee_2018.py.txt:113`, inside the USGS reference
  implementation vendored verbatim under the fixture rule above. A tree-wide `rg TODO` returns that
  line plus the places where this rule is *stated* (this file, `CONTRIBUTING.md`, ADR-0001); no
  file under `src/`, `tests/**/*.py`, `docs/` or the build configuration carries one. Any hit
  outside that set is a violation.

## Make targets

Copied from `Makefile`. Every `validate-*` target must be runnable offline from a fresh clone
after `uv sync`.

| Target | What it does |
|---|---|
| `help` | list targets |
| `setup` | install the locked environment (dev group included) |
| `lint` | ruff check + format check + import-linter |
| `typecheck` | mypy --strict |
| `test` | offline unit + contract suite (sockets disabled) |
| `test-integration` | opt-in: network / Docker tests |
| `validate-language` | banned-phrase scan (rupture does not predict earthquakes) |
| `validate-catalog` | catalogue schema, provenance, Mc present, no duplicates, landslide events retained |
| `validate-etas` | ETAS fit diagnostics present, parameters plausible, forecast sums finite |
| `validate-eval` | CSEP harness runs on fixtures; leakage assertion passes |
| `validate-hazard` | OpenQuake demo runs in the pinned Docker image (skips with a printed reason when the container cannot run here: Docker absent, or the amd64-only image on an arm64 host) |
| `validate-cascade` | Gorkha ground-failure reproduction, discriminator accounting, cascade contracts (`mk/cascade.mk`) |
| `validate-risk` | ground motion → loss → avoided loss, offline: GSIM verification against OpenQuake's committed vectors, finite ordered loss intervals, the `avoided-loss.v1` round-trip, provenance on every figure (`mk/risk.mk`) |
| `validate-aftershock` | the operational aftershock service's fits, horizons and refusals (`mk/aftershock.mk`) |
| `validate-challengers` | challenger leakage controls and fit honesty (`mk/challengers.mk`) |
| `schema-export` | regenerate contracts/*.json from the domain models |
| `schema-check` | fail if contracts/*.json drift from the domain models |
| `validate-rupture` | everything, offline (`lint typecheck test` + `$(VALIDATE_GATES)`); with every `mk/*.mk` fragment present that is ten gates |
| `promote` | refuse unless every gate is green **and** `PROMOTE_APPROVED_BY` names a human approver; then print the promotion record, naming each skipped gate and its reason |
| `underwriting-check` | run the serac Nepal corridor portfolio through the MHT scenario and print expected and avoided loss with intervals; exits non-zero if any figure is missing or the response is a stub |
| `clean` | remove caches; `git clean -fdX reports` removes the *ignored* files under `reports/` and leaves the committed evidence and model cards alone |

How the gates are wired:

- Each `validate-<name>` target runs `uv run rupture validate <name>` (equivalently `rupture
  validate gate <name>`). Gate names are the `GATES` tuple in
  `src/rupture/validation/registry.py`, which as of Prompt 2 holds ten: `language`, `schema`,
  `catalog`, `etas`, `eval`, `hazard`, `cascade`, `risk`, `aftershock`, `challengers`. That
  tuple is the single source of truth — if this list and the tuple ever disagree, the tuple is
  right and this file is stale. Each gate is a module `src/rupture/validation/<name>.py` exposing
  `run(repo_root: Path) -> GateResult` (`rupture.validation.result.GateResult`, with
  `GateStatus` in `{PASSED, FAILED, SKIPPED, NOT_IMPLEMENTED}`); the registry imports it by
  name, so adding a gate means adding that module and its `mk/<name>.mk` line. `SKIPPED` is
  legal only with a printed `reason`; a silent skip is a bug. Gates whose module does not exist
  yet report `NOT_IMPLEMENTED`, exit 2 and name the phase that delivers them. `make schema-check`
  runs the same drift check as the `schema` gate through `rupture schema export --check`.
- The `validate-rupture` aggregate depends on `$(VALIDATE_GATES)`, initialised to
  `validate-language schema-check`; the Makefile then does `-include mk/*.mk`. Phase-2 gates
  register themselves by dropping a `mk/<name>.mk` file containing
  `VALIDATE_GATES += validate-<name>`; they do not edit the Makefile itself, so several parallel
  worktrees can each add a gate without merge conflicts. A gate whose *name* is new to the
  Makefile also defines its own `.PHONY` target in that fragment (see `mk/cascade.mk`). Gates must
  be offline-safe or skip with a printed reason.
- `make promote` refuses unless `validate-rupture` is green and prints the reason for any gate
  that was skipped.
- **Every registered gate runs in CI.** `.github/workflows/ci.yml` runs the nine offline gates plus
  `underwriting-check` on every push and pull request, and `validate-hazard` in the
  `hazard-integration` job on `main` (it needs the pinned OpenQuake container). The last step of
  the offline job compares `GATES` against the list of gates the workflow claims to cover and fails
  if they disagree, so a gate added without a CI step breaks the build rather than rotting quietly.
  If you add a gate: add its `mk/<name>.mk`, add a step to the offline job, and add its name to
  `covered` in that step.

## CLI verbs

`rupture` is a typer application (`src/rupture/cli.py`); each noun is a sub-application in
`src/rupture/commands/<noun>.py`. Sub-commands not yet implemented exit 2 and say which phase
delivers them, rather than pretending to run. **The implementing module is always authoritative
over this table**; where an option list here is shorter than the module's, read the module.

| Verb | Purpose | Owner |
|---|---|---|
| `rupture catalog build --region <r> --from <utc> --to <utc> [--sources comcat,isc,gcmt,isc-gem] [--offline-fixtures] [--out DIR] [--min-magnitude M] [--time-window-s 16] [--distance-km 100] [--update-region-mc [--force-mc]] [--no-etas-cross-check]` | merge sources, homogenise magnitudes, estimate Mc, write GeoParquet + homogenisation log; `--update-region-mc` writes every estimate to `Region.mc_estimates` and sets `Region.mc` only when maximum-curvature b ≥ 0.7 and Mw coverage at the target ≥ 80 % (else leaves it null and prints why; `--force-mc` overrides) | catalog-engineer |
| `rupture catalog inspect <dir> [--json]` | summarise a built catalogue directory (counts by type, Mw coverage, bounds, Mc estimates, log size) | catalog-engineer |
| `rupture catalog refresh-fixtures` | re-cut the committed ComCat/ISC/GCMT fixtures from the live services and rewrite each `provenance.json` (network) | catalog-engineer |
| `rupture region list` / `rupture region show <r>` / `rupture region init [--force]` | list the test regions; print one `Region` record (polygon, thresholds, fitted Mc); write the three default region files (refuses to overwrite a fitted `mc` without `--force`) | catalog-engineer |
| `rupture forecast fit --model etas --region <r> --cutoff <utc> [--mc M] [--auxiliary-years 2.0] [--max-iterations 200] [--max-seconds 1800]` | fit the baseline on events with `origin_time < cutoff`; persist the `FitResult` + diagnostics to `baselines/etas/<region>/` and archive them under `fits/<cutoff>/`. The EM caps stop a runaway fit and persist it with `converged=false`; California needs `--max-seconds 21600` | forecast-engineer |
| `rupture forecast issue --model etas --region <r> --horizon 30d --issue <utc>` | issue a `ForecastGrid` at `issue_time` from the persisted fit | forecast-engineer |
| `rupture evaluate run --forecast <id>` | N/M/S/L(CL) tests + plot bundle → `reports/eval/<forecast_id>/` | forecast-engineer |
| `rupture evaluate schedule --region <r> --model etas --from <utc> --to <utc> --step 30d` | rolling pseudo-prospective issue-and-evaluate; aggregates to `reports/eval/schedule-<region>-<model>.json` | forecast-engineer |
| `rupture hazard demo` / `rupture hazard classical` / `rupture hazard check` | run the OpenQuake bundled demo / a classical PSHA job in the pinned image; `check` exits 3 if the container cannot run here | hazard-engineer |
| `rupture cascade run` / `exposure` / `reproduce` / `discriminate` | ground-failure susceptibility for a scenario; slope-unit and asset exposure overlays; the Gorkha reproduction against the published USGS product; the mass-movement discriminator | cascade-engineer |
| `rupture risk scenarios` / `gsims` / `run` / `validate` | list the scenario ruptures and the native GSIM registry; price a portfolio against a scenario and report what an intervention avoids; validate an `avoided-loss.v1` payload | risk owner (worktree `../rupture-wt-risk`) |
| `rupture aftershock forecast` / `validate` / `serve` | issue aftershock probabilities by magnitude and horizon for a mainshock; check a sequence pseudo-prospectively; serve the FastAPI app | ops-forecaster |
| `python -m rupture.commands.challenger ntpp select \| fit \| issue \| schedule \| ablate` | the challenger pipeline, in the order it must be run in: freeze hyperparameters on validation windows, fit before the cutoff, issue, run the whole pseudo-prospective schedule, run the deliberately leaky ablations. **Not mounted on `rupture`** — `cli.py` has no `challenger` sub-app, so this noun is reached through `python -m` | npp-researcher |
| `python -m rupture.reporting.challenger_plots` | redraw the figures in `reports/CHALLENGER_EVALUATION.md` from committed evidence; loads no model and issues no forecast | docs owner |
| `rupture schema export [--out DIR] [--check]` | write (or drift-check) JSON Schema for every domain contract into `contracts/` | architect |
| `rupture validate <gate>` | run one gate; `<gate>` is any name in the `GATES` tuple (`language`, `schema`, `catalog`, `etas`, `eval`, `hazard`, `cascade`, `risk`, `aftershock`, `challengers`), and `rupture validate gate <name>` is the same by argument | gate owner |
| `rupture promote --approved-by <person>` | re-run every gate and print the promotion record, naming each skipped gate and its reason; refuses if any gate blocks **or** if no approver is named | architect |
| `rupture underwriting-check [--portfolio trishuli-corridor] [--scenario mht-m8-hypothetical]` | price the serac Nepal corridor portfolio against the MHT scenario and print expected loss and avoided loss, each with its interval, confidence tier and provenance; exits non-zero if a figure is missing or the response is a stub | architect |

## Subagent roles and the worktree rule

| Agent | Owns | Notes |
|---|---|---|
| `architect` | D1 governance docs, D2 domain + ports + contracts, layout, merges, ledger | runs serially on `main` |
| `catalog-engineer` | D3 catalogue adapters, homogenisation, Mc, regions, fixtures; D4 faults and source models | worktree `../rupture-wt-catalog` |
| `forecast-engineer` | D5 ETAS baseline, D6 CSEP harness and pseudo-prospective runner, `docs/SCHEDULER.md` | worktree `../rupture-wt-forecast` |
| `hazard-engineer` | D7 OpenQuake Docker adapter, `infra/docker`, `infra/jobs` | worktree `../rupture-wt-hazard` |
| `npp-researcher` | C1a the neural temporal point process, `src/rupture/models/challengers/ntpp/`, `docs/CHALLENGER_NTPP.md` | worktree `../rupture-wt-npp`; named in `registry.PHASE_FOR_GATE` |
| `deep-grid` | C1b the gridded ConvLSTM and the log-linear ensemble, `src/rupture/models/{data,ensemble}/`, `docs/CHALLENGER_GRIDDED.md`, `docs/CHALLENGER_ENSEMBLE.md` | worktree `../rupture-wt-grid`; named in `registry.PHASE_FOR_GATE` |
| risk owner | C2 `src/rupture/risk/`, the ground-motion, exposure and vulnerability adapter families, `docs/RISK.md` | worktree `../rupture-wt-risk`. **No role name for this owner is recorded anywhere in the tree**; it is left unnamed here rather than invented |
| `cascade-engineer` | C3 `src/rupture/cascade/`, `adapters/cascade/`, `docs/CASCADE.md` | worktree `../rupture-wt-cascade`; named in `registry.PHASE_FOR_GATE` |
| `ops-forecaster` | C4 `src/rupture/services/aftershock/`, `docs/AFTERSHOCK.md` | worktree `../rupture-wt-aftershock`; named in `registry.PHASE_FOR_GATE` |
| `qa-reviewer` | read-only review after each merge and before push | **veto** on: leakage (any path where post-cutoff events reach a fit or forecast), banned language, fabricated or synthetic data presented as real, network access in `tests/unit`, silent skips, docs that disagree with code, an over-claiming `RELEASE_STATUS.md` |

Worktree rule: parallel agents work in separate `git worktree`s branched from the same commit,
each with its own `uv` venv, and touch only their own subtrees plus their own tests, docs and
`mk/<name>.mk` gate file. Shared files (`Makefile`, `pyproject.toml`, `cli.py`, `dvc.yaml`) are
pre-sectioned so additions are append-only. Merges are real merges (not `format-patch`), performed
serially by `architect`, and `make validate-rupture` is run after **each** merge before the next
one starts. A qa-reviewer finding must be fixed before the next merge.

## Banned language

`make validate-language` (`src/rupture/validation/language.py`) scans every `.py .md .json .yaml
.yml .toml .txt .cfg .ini` file in the tree, case-insensitively, for:

- `predict` and every derivative (`-s`, `-ed`, `-ing`, `-ion(s)`, `-or(s)`, `-ive`, `-ability`);
- `early warning` / `early-warning` used as a capability (rupture is not an EEW system);
- the deterministic phrasings `will occur`, `will strike`, `will hit`, `will happen`, `imminent`, `next big one`.

Use *forecast*, *rate*, *expected count*, *probability of exceedance*. The only permitted
exceptions are the exact fragments in `src/rupture/validation/banned_language_allowlist.txt`:
the sentence "rupture does not predict earthquakes", the definitional sentence quoted in
"What rupture is and is not" above, the gate's own vocabulary, the lines of this banned list
itself, the two glossary headings that define what rupture is not, and the traditional expansion
of the acronym GMPE as a term of art (rupture itself says GSIM). **An allowlisted fragment exempts
only itself, not the line it sits on**: the gate deletes each matching fragment from the line and
re-scans what is left, so a banned claim cannot ride along beside an allowlisted sentence in the
same markdown table row. A fragment must therefore sit on one line to match at all. Do not extend
the allowlist without an ADR. The inline marker
`# lang-gate: allow` exempts a single line and is for test strings that must spell out a
violation; it is never used in docs, model
outputs or identifiers.

CSEP's full name contains a banned word; refer to it by acronym.

## Data, credentials and money

- **Ask before downloads > 5 GB or paid API calls.** Everything in Prompt 1 (ComCat, ISC, GCMT,
  GEM Global Active Faults, ESHM20, the OpenQuake image) is well under that and free; see
  `docs/DATA_SOURCES.md` for sizes.
- Credentials via `.env` (never committed; loaded with python-dotenv); nothing is required for
  the offline suite. See `docs/CREDENTIALS.md`.
- Adapters fetch or fail loudly. No adapter ever returns synthesised rows; no test ever passes on
  data it invented.

## Sibling `serac`

`serac` is a separate standalone repository. The two share **file contracts only**. Coordination is
by copying schema files, never by importing code; `serac` is not, and must never become, a Python
dependency of rupture (ADR-0014).

| Contract | Direction | State |
|---|---|---|
| `contracts/source-type-assessment.v0.json` | serac → rupture | published by rupture first |
| `contracts/avoided-loss.v0.json` | rupture → consumers | superseded in practice by v1; kept published because a version is never withdrawn |
| `contracts/avoided-loss.v1.json` | rupture → consumers, shared shape with serac | the reconciled shape (ADR-0021); this is what `rupture underwriting-check` and `rupture risk` produce |
| serac's `contracts/slope-unit.v0.json` | serac → rupture | consumed by `SeracSlopeUnitSource`; **serac has exported no slope-unit records yet**, so rupture runs on a labelled fallback built from serac's own AOI files, with every terrain attribute null (ADR-0027) |

`serac` is **not** empty: as of 2026-09-03 it has AOIs (`lhende-khola-trishuli`,
`chamoli-rishiganga`, `blatten-lotschental`) and rupture ships a byte-verbatim copy of the ones it
uses under `tests/fixtures/cascade/serac/` with serac's attribution, licence and commit recorded.
What it has not published is any DEM-derived terrain. Anything in this tree still saying "serac is
empty" is stale.
