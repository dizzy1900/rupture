# RELEASE_STATUS

rupture does not predict earthquakes. This ledger says what actually ran, and under-claims by
design. Last updated 2026-09-03.

**Phase:** Prompt 1 (foundations) and Prompt 2 (challengers, loss, cascades) both complete.

Maturity: `not started` · `scaffold` (structure, no behaviour) · `stub` (runs, exits
"not implemented") · `working` (offline tests pass) · `validated` (ran on real data; the result is
recorded, whatever it was).

## Prompt 1 — foundations

| Component | Maturity | What actually ran |
|---|---|---|
| Repository, CI, tooling | validated | `uv`, ruff, `mypy --strict`, import-linter; CI green on every push, running lint, typecheck, the offline suite and the catalogue, ETAS, evaluation, language and contract gates |
| Governance docs, 35 ADRs | validated | the evaluation protocol was committed **before** any model in this repository was fitted (protocol 02:43, first ETAS adapter 03:26) |
| Language gate | validated | passes tree-wide; a seeded violation fails it; ADR-0034 admits published paper titles so sources can be cited by name |
| Domain + 19 contracts | validated | drift-checked in CI; `avoided-loss.v1` reconciles with the sibling `serac` and is proven by tests that parse serac-shaped payloads |
| Catalogues (ComCat, ISC, GCMT) | validated | three built 1976→2026: California 110,766 events, Türkiye 7,038, Nepal 2,728 |
| ISC-GEM adapter | working | parser only; the download is form-gated and was never fetched, so no ISC-GEM data is in any build |
| ETAS baseline | validated | converged fits for all three regions at cutoff 2022-01-01; parameters published in `docs/ETAS_BASELINE.md` |
| CSEP harness + pseudo-prospective schedule | validated | 116 scored windows; every leakage assertion held; four injected violations correctly refused |
| OpenQuake adapter | validated (CI only) | the bundled demo runs in the pinned container in CI with `RUPTURE_HAZARD_REQUIRE=1` so a skip fails the job. **Never completed on this machine** — see gaps |
| Docker image, job manifests | scaffold | manifests schema-validated; **the image has never been built or run anywhere** |

Baseline scores (`docs/BASELINE_RESULTS.md`): Nepal N 0.93 / M 0.95 / S 0.73 / L 0.77 / CL 0.86 over
55 windows; Türkiye 0.91 / 0.93 / 0.69 / 0.90 / 0.86 over 55; California 6 windows, all passed.
A pass means a test did not reject at α = 0.05. It is not a skill claim.

## Prompt 2 — challengers, loss, cascades

| Component | Maturity | What actually ran |
|---|---|---|
| C1a neural temporal point process | validated | full 55-window schedule, both regions. **Not promotable** |
| C1b gridded ConvLSTM | validated | same schedule, same targets. **Not promotable** |
| Log-linear ensemble | validated | beats ETAS on information gain in Türkiye only (+0.335/event); the rule needs 2 of 3 regions. **Not promoted** |
| Leaky ablation | validated | +0.31 to +2.16 nats/event across the three models; on Nepal the NTPP leak (+0.77) flips the sign of the result |
| C2 ground motion (native GSIMs) | validated | BC Hydro reproduces OpenQuake's 22,400 reference values to 5e-7 %, stddev exact; BSSA14 to 0.00067 % at tabulated periods. **These are measured, not ratcheted**: the tests assert the looser registry tolerances (0.01 % / 2 %), so a regression to 0.009 % would pass silently |
| C2 exposure, vulnerability, loss, avoided loss | validated | the serac Trishuli corridor priced end to end; `make underwriting-check` prints USD 675.2M [361.6–996.5M] expected, retrofit avoiding USD 45.0M [32.2–54.5M] |
| C2 FastAPI service | working | tested with `TestClient`; **never served outside tests** |
| C3 ground failure (Nowicki Jessee 2018, Zhu 2017) | validated | against the real USGS product for Gorkha: liquefaction r = 0.45, landslide r = 0.16, both biased low |
| C3 cascade exposure + discriminator client | working | serac has published no slope-unit export yet, so terrain screens report **not applied** |
| C4 aftershock service | validated | Gorkha and Kahramanmaraş at +1 h, +1 d, +7 d. **Under-forecasts the first day 3–12×** |
| Gates | validated | 10 gates; `promote` refuses without a named approver |

## Known gaps

- **No challenger was promoted.** The one metric beaten (Türkiye ensemble information gain) rests
  on an interval that assumes independent events, and corrects a baseline over-forecast rather than
  adding information. `reports/CHALLENGER_EVALUATION.md` has the evidence.
- **The loss numbers are not underwriting-grade.** 27 % of the loss rests on fragility functions
  with no published source; all component value shares are assumed; the replacement-value interval
  is judgement. The central cost figure is sourced (IRENA 2024).
- **The aftershock service under-forecasts the first day by 3–12×** because it has no generic
  multi-sequence parameters.
- **Ground failure runs on shaking alone.** Slope, lithology, land cover and topographic index were
  not sourced. The Gorkha correlations above are what that costs.
- **No PSHA has been run for any region.** Türkiye's ESHM20 is fetched and unused; California and
  Nepal have no openly licensed model in OpenQuake's format that could be verified (ADR-0008).
- **OpenQuake has never completed a run on this machine.** The image is amd64-only and this host is
  arm64; the gate skips with the reason printed and CI proves the path (ADR-0011 addendum).
- **California's schedule is 6 of 55 windows.** Stopped deliberately: issuance cost scales with a
  55,828-event history, leaving an estimated 35–60 core-hours. Resumable and idempotent.
- **The `models/data` seam did not dissolve on merge** (ADR-0035). Two implementations of the same
  guarantees exist; every gridded fit records which produced it.
- **Türkiye's fitted branching ratio is 1.04**, at criticality, on 405 training events.
- **California magnitudes are an approximation** (ADR-0019): 102,940 events take Mw from the
  network-preferred local or duration magnitude, following CSEP RELM practice.
- **Nepal is sparse**: 33 of 55 windows held no target event, so M, S, L and CL were undecidable.
- **ISC-GEM absent** from every build; **the DVC remote is a local placeholder**; **`log_likelihood`
  is null** on every ETAS fit because upstream does not expose it.
- **`baselines/ntpp/` is committed while `baselines/etas/` and `baselines/gridded/` are not.** The
  neural weights are the only reproducible evidence for a negative result and are small; the
  asymmetry is deliberate and noted here rather than tidied away. **The gridded and ensemble
  *fits* are therefore not retained** — their *scores* are, in
  `reports/challenger/<region>/schedule-<region>-challengers.json`, which is committed.
- **No import-linter contract governs the four Prompt 2 packages relative to each other.** `domain`
  and `ports` are protected from all of them, but nothing stops `cascade` importing `models`, and
  `models` already imports `pipelines` in four places — an inward-facing model reaching into the
  orchestration layer. Unforbidden, and it should not be.
