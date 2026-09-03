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

Prompt 1 (this phase) builds the foundations: catalogue infrastructure, the ETAS baseline, the
CSEP evaluation harness, the OpenQuake adapter, contracts and gates. Prompt 2 builds challenger
models, the loss layer (F2) and the cascade layer (F3).

## Non-negotiables

Quoted verbatim from the brief (`rupture-prompt-1-foundations.md`, section "Non-negotiables").

1. **No prediction claims.** See above. `make validate-language` greps for banned phrasing.
2. **No leakage.** All forecast evaluation is time-forward (pseudo-prospective) with a hard cut; any data after the cut is unavailable to the model. Assert this in tests with catalogue timestamps.
3. **ETAS is a first-class citizen**, not a straw man. It must be fitted properly (magnitude of completeness, time-varying if warranted, region-specific) and its parameters and fit diagnostics published.
4. **No fabricated data.** Adapters fetch or fail loudly; unit tests run offline on committed fixtures; unknowns are null.
5. **Provenance on every record** (source, retrieval time, checksum, licence). Catalogue homogenisation steps are logged per event.
6. **Self-contained repo conventions**: no private repo, internal package or hosted platform is a dependency. Define and document rupture's own conventions: DVC-versioned `data/` and `baselines/`, `src/validation/`, Makefile `validate-*`, `promote`, `underwriting-check`, honest `RELEASE_STATUS.md`, a plain Docker image as the deployment unit, and portable job manifests in `infra/jobs/*.yaml` (AWS-annotated) for scaled runs. Downstream consumers integrate through the versioned JSON Schemas in `contracts/`.
7. **Ask before downloads > 5 GB or paid API calls.** Credentials via `.env`; documented in `docs/CREDENTIALS.md`.

## Repository conventions

Recorded as ADR-0001 and ADR-0002; summarised here.

- **Hexagonal layout** (see `README.md` § Layout). `src/rupture/domain/` holds pure pydantic v2
  models and imports nothing from `adapters/`, `pipelines/`, `cli` or `validation/`;
  `src/rupture/ports/` holds `Protocol` classes and imports only `domain`; `adapters/` implement
  ports and never import each other across families (`catalogs`, `sources`, `forecasting`,
  `evaluation`, `hazard`). All three rules are import-linter contracts in `pyproject.toml`
  (`make lint` runs `lint-imports`) and fail CI. `commands/` holds the typer sub-applications
  (one per CLI noun) and `pipelines/` the orchestration they call.
- **Tests** are split into `tests/unit` (offline; `make test` passes `--disable-socket
  --allow-unix-socket` so any network call fails), `tests/integration` (network or Docker; marked
  `integration`, opt-in via `make test-integration`) and `tests/contract` (JSON Schema round-trips
  and the fixtures shared with `serac`).
- **Fixtures are real slices**, never synthesised. Every fixture directory under `data/fixtures/`
  carries a `provenance.json` and is never edited by hand; regenerate it with the adapter and
  re-record provenance instead.
- **Provenance fields** on every ingested record: `source`, `source_url`, `retrieved_at`, `sha256`,
  `licence`, `adapter_version`. Unknown values are `null`, never guessed.
- **Timestamps** are UTC and timezone-aware everywhere (ruff rule `DTZ` is on). Cutoffs and
  windows are half-open `[from, to)`.
- **Decisions are ADRs** in `docs/adr/` (index in `docs/adr/README.md`). A settled ADR is not
  relitigated in a PR; write a new ADR that supersedes it.
- **Honesty in `RELEASE_STATUS.md`.** Under-claim. If it did not run, say so, and say why.
- No `TODO` without an issue reference.

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
| `schema-export` | regenerate contracts/*.json from the domain models |
| `schema-check` | fail if contracts/*.json drift from the domain models |
| `validate-rupture` | everything, offline (`lint typecheck test` + `$(VALIDATE_GATES)`, initially `validate-language schema-check`) |
| `promote` | refuse unless validate-rupture is green; then print the promotion record |
| `underwriting-check` | AvoidedLossRequest round-trip; exits non-zero: not implemented (Prompt 2) |
| `clean` | remove caches |

How the gates are wired:

- Each `validate-<name>` target runs `uv run rupture validate <name>` (equivalently `rupture
  validate gate <name>`). Gate names are the `GATES` tuple in
  `src/rupture/validation/registry.py`: `language`, `schema`, `catalog`, `etas`, `eval`,
  `hazard`. Each gate is a module `src/rupture/validation/<name>.py` exposing
  `run(repo_root: Path) -> GateResult` (`rupture.validation.result.GateResult`, with
  `GateStatus` in `{PASSED, FAILED, SKIPPED, NOT_IMPLEMENTED}`); the registry imports it by
  name, so adding a gate means adding that module and its `mk/<name>.mk` line. `SKIPPED` is
  legal only with a printed `reason`; a silent skip is a bug. Gates whose module does not exist
  yet report `NOT_IMPLEMENTED`, exit 2 and name the phase that delivers them. `make schema-check`
  runs the same drift check as the `schema` gate through `rupture schema export --check`.
- The `validate-rupture` aggregate depends on `$(VALIDATE_GATES)`, initialised to
  `validate-language schema-check`; the Makefile then does `-include mk/*.mk`. Phase-2 gates
  register themselves by dropping a `mk/<name>.mk` file containing
  `VALIDATE_GATES += validate-<name>`; they do not edit the Makefile itself, so three parallel
  worktrees can each add a gate without merge conflicts. Gates must be offline-safe or skip with
  a printed reason.
- `make promote` refuses unless `validate-rupture` is green and prints the reason for any gate
  that was skipped.

## CLI verbs

`rupture` is a typer application (`src/rupture/cli.py`); each noun is a sub-application in
`src/rupture/commands/<noun>.py`, which the owning Phase-2 agent fills in. Sub-commands not yet
implemented exit 2 and say which phase delivers them, rather than pretending to run. Option names
below for Phase-2 verbs are the planned ones; the implementing module is authoritative.

| Verb | Purpose | Owner |
|---|---|---|
| `rupture catalog build --region <r> --from <utc> --to <utc> [--sources comcat,isc,gcmt,isc-gem] [--offline-fixtures] [--out DIR] [--min-magnitude M] [--time-window-s 16] [--distance-km 100] [--update-region-mc [--force-mc]] [--no-etas-cross-check]` | merge sources, homogenise magnitudes, estimate Mc, write GeoParquet + homogenisation log; `--update-region-mc` writes every estimate to `Region.mc_estimates` and sets `Region.mc` only when maximum-curvature b ≥ 0.7 and Mw coverage at the target ≥ 80 % (else leaves it null and prints why; `--force-mc` overrides) | catalog-engineer |
| `rupture catalog inspect <dir> [--json]` | summarise a built catalogue directory (counts by type, Mw coverage, bounds, Mc estimates, log size) | catalog-engineer |
| `rupture catalog refresh-fixtures` | re-cut the committed ComCat/ISC/GCMT fixtures from the live services and rewrite each `provenance.json` (network) | catalog-engineer |
| `rupture region list` / `rupture region show <r>` / `rupture region init [--force]` | list the test regions; print one `Region` record (polygon, thresholds, fitted Mc); write the three default region files (refuses to overwrite a fitted `mc` without `--force`) | catalog-engineer |
| `rupture forecast fit --model etas --region <r> --cutoff <utc>` | fit the baseline on events with `origin_time < cutoff`; persist the `FitResult` + diagnostics to `baselines/etas/<region>/` | forecast-engineer |
| `rupture forecast issue --model etas --region <r> --horizon 30d --issue <utc>` | issue a `ForecastGrid` at `issue_time` from the persisted fit | forecast-engineer |
| `rupture evaluate run --forecast <id>` | N/M/S/L(CL) tests + plot bundle → `reports/eval/<forecast_id>/` | forecast-engineer |
| `rupture evaluate schedule --region <r> --model etas --from <utc> --to <utc> --step 30d` | rolling pseudo-prospective issue-and-evaluate; aggregates to `reports/eval/schedule-<region>-<model>.json` | forecast-engineer |
| `rupture hazard demo` / `rupture hazard classical` | run the OpenQuake bundled demo / a classical PSHA job in the pinned image; skip with reason if Docker is absent | hazard-engineer |
| `rupture schema export [--out DIR] [--check]` | write (or drift-check) JSON Schema for every domain contract into `contracts/` | architect |
| `rupture validate <gate>` | run one gate (`language`, `schema`, `catalog`, `etas`, `eval`, `hazard`); `rupture validate gate <name>` is the same by argument | gate owner |
| `rupture promote` | print the promotion record (reached via `make promote` only when green) | architect |
| `rupture underwriting-check` | round-trip the example `AvoidedLossRequest` through `contracts/avoided-loss.v0.json`; exit 2 "not implemented: Prompt 2" | architect |

## Subagent roles and the worktree rule

| Agent | Owns | Notes |
|---|---|---|
| `architect` | D1 governance docs, D2 domain + ports + contracts, layout, merges, ledger | runs serially on `main` |
| `catalog-engineer` | D3 catalogue adapters, homogenisation, Mc, regions, fixtures; D4 faults and source models | worktree `../rupture-wt-catalog` |
| `forecast-engineer` | D5 ETAS baseline, D6 CSEP harness and pseudo-prospective runner, `docs/SCHEDULER.md` | worktree `../rupture-wt-forecast` |
| `hazard-engineer` | D7 OpenQuake Docker adapter, `infra/docker`, `infra/jobs` | worktree `../rupture-wt-hazard` |
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
- the deterministic phrasings `will occur`, `will strike`, `will hit`, `will happen`, `imminent`,
  `next big one`.

Use *forecast*, *rate*, *expected count*, *probability of exceedance*. The only permitted
exceptions are the exact fragments in `src/rupture/validation/banned_language_allowlist.txt`:
the sentence "rupture does not predict earthquakes", the definitional sentence quoted in
"What rupture is and is not" above, the gate's own vocabulary, the lines of this banned list
itself, the two glossary headings that define what rupture is not, and the traditional expansion
of the acronym GMPE as a term of art (rupture itself says GSIM). An allowlisted fragment must sit
on a single line to take effect. Do not extend the allowlist without an ADR. The inline marker
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

`serac` is a separate standalone repository. The two share **file contracts only**:
`contracts/avoided-loss.v0.json` and `contracts/source-type-assessment.v0.json`. Coordination is by
copying schema files, never by importing code; `serac` is not, and must never become, a Python
dependency of rupture. As of 2026-09-03 the `serac` repository is empty, so rupture publishes
first (ADR-0014).
