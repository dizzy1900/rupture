# RELEASE_STATUS

rupture does not predict earthquakes. This ledger says what actually ran, and under-claims by
design. Last updated 2026-09-03.

**Phase:** Prompt 1 — Foundations, complete. Prompt 2 (challenger models, the loss layer, the
cascade layer) has not started.

Maturity scale: `not started` · `scaffold` (structure, no behaviour) · `stub` (runs, exits
"not implemented") · `working` (offline tests pass) · `validated` (ran on real data; the result is
recorded, whatever it was).

## Components

| Component | Maturity | What was actually run |
|---|---|---|
| Repository, CI, tooling | validated | `uv`, ruff, `mypy --strict`, 234 offline tests, import-linter; CI green on every push to `main`. The CI `offline` job runs lint, typecheck, tests and the catalogue, ETAS, evaluation, language and contract gates on every push; only `validate-hazard` is separate (it needs the container) |
| Governance docs (CLAUDE, ARCHITECTURE, EVALUATION_PROTOCOL, GLOSSARY, DATA_SOURCES, CREDENTIALS, HAZARD, DEPLOYMENT, CATALOG_BUILD, ETAS_BASELINE, SCHEDULER, BASELINE_RESULTS, 20 ADRs) | validated | the evaluation protocol was written and committed before any model in this repository was fitted |
| Language gate | validated | `make validate-language` passes over the whole tree; a seeded violation fails it (test) |
| Domain models and `contracts/*.v0.json` (11 schemas) | validated | drift-checked in CI; example payloads round-trip; `rupture underwriting-check` validates an `AvoidedLossRequest` then exits 2 "not implemented: Prompt 2" |
| Catalogue adapters (ComCat, ISC, GCMT) + homogenisation | validated | three catalogues built 1976-01-01 → 2026-08-01: California 110,766 events, Türkiye 7,038, Nepal 2,728. Details and the superseded first builds in `docs/CATALOG_BUILD.md` |
| ISC-GEM adapter | working | parser only; the download is form-gated and was never fetched, so no ISC-GEM data is in any build |
| Test regions, Mc estimation | validated | Mc by maximum curvature and b-value stability published per region in `data/regions/*/region.json` (`mc_estimates`) |
| GEM Global Active Faults; ESHM20 source model | working | GAF fetched (13,696 faults, GeoParquet, DVC pointer committed); ESHM20 fetched for Türkiye (55 files, 40.2 MB, manifest committed). Neither has been used in a hazard calculation |
| ETAS baseline (`etas` at a pinned commit, behind `ForecastModel`) | validated | converged fits for all three regions at cutoff 2022-01-01; parameters and diagnostics published in `docs/ETAS_BASELINE.md` |
| CSEP harness (`pycsep` 0.8.0) | validated | N, M, S, L, CL and paired T/W implemented; 110 scored windows across two regions, plus one California window |
| Pseudo-prospective schedule + leakage assertions | validated | 55 windows per region, 2022-01-01 → 2026-08-01, 4 logged refits each; all three leakage rules held in every window; a seeded post-cutoff event fails the negative test |
| OpenQuake adapter (`openquake/engine:3.26.2`) | validated (CI only) | the bundled demo ran through the adapter in the pinned container in CI (run 33744626791, gate 86 s, integration test 85 s, with `RUPTURE_HAZARD_REQUIRE=1` so a skip would have failed). never completed on this machine — see Known gaps |
| Docker image, `infra/jobs/*.yaml` | scaffold | manifests validate against their schema; **the rupture image has never been built or run anywhere**, and neither has `compose.yml` |
| `make promote` | validated | refused to promote while `validate-hazard` was failing; passes now that the gate reports the arm64 container limitation as a skip rather than a failure. `rupture promote` re-runs every gate itself and prints each skip and its reason |

## Results

The ETAS baseline's scores are in `docs/BASELINE_RESULTS.md`. Summary, for two of three regions:

| Region | Windows issued / scored | N | M | S | L | CL |
|---|---|---|---|---|---|---|
| `nepal-himalaya` | 55 / 55 | 0.93 | 0.95 | 0.73 | 0.77 | 0.86 |
| `turkiye-eaf` | 55 / 55 | 0.91 | 0.93 | 0.69 | 0.90 | 0.86 |

A pass means a consistency test did not reject the forecast at α = 0.05. It is not a skill claim,
and no comparison against a challenger has been made — that is Prompt 2, and the promotion rule
for it is fixed in `docs/EVALUATION_PROTOCOL.md`.

## Known gaps

- **No challenger models, no loss layer (F2), no cascade layer (F3).** Prompt 2. `make
  underwriting-check` deliberately exits non-zero.
- **California has one scored window, not a schedule.** Its fit converged (55,828 events at
  Mc 2.70, 94 minutes of EM) and its first window scored 4 target events against 5.66 expected,
  passing all five tests. The full 55-window schedule costs roughly 11 hours and was still running
  when this was written; `docs/BASELINE_RESULTS.md` covers Nepal and Türkiye only.
- **The OpenQuake container has never completed a run on this machine.** It starts and initialises, then exceeds the timeout: `openquake/engine` publishes a
  single-platform `linux/amd64` image and this host is arm64, so the demo can only run under
  emulation, where it exceeds the adapter's timeout. `validate-hazard` skips with that reason
  printed; CI (amd64) runs it for real on every push to `main`. See ADR-0011 addendum.
- **No PSHA has been run for any test region.** Türkiye has an openly licensed source model
  (ESHM20) fetched and ready, and an example job; it was not executed. California and Nepal have
  no openly licensed NRML model (ADR-0008).
- **Türkiye's fitted branching ratio is 1.04**, at or above criticality, on 405 training events.
  Published rather than tuned away; treat Türkiye rates as weakly constrained.
- **California magnitudes are an approximation.** 102,940 of its events take Mw from the
  network-preferred local or duration magnitude under ADR-0019, following CSEP RELM practice,
  because no ML→Mw relation is cited. Every such event is identifiable by its `mw_conversion`
  prefix `assumed-equivalent`. Before this policy, Mw coverage at M ≥ 3.95 was 49 % and the
  apparent b-value was 0.59; after it, 99 % and 1.01.
- **Nepal is sparse.** 33 of 55 windows contained no target event at M ≥ 4.7, so M, S, L and CL
  were undecidable there and are recorded as N-test only.
- **ISC-GEM is absent** from every build (form-gated download).
- **`run_scenario` and `rupture hazard classical` are untested against a real container.**
- **The DVC remote is a local placeholder.** `.dvc/local-remote`; nothing is pushed anywhere.
- **`log_likelihood` is null** on every fit: the upstream package does not expose it.
