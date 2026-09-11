# RELEASE_STATUS

This ledger says what actually ran, and under-claims by
design. Last updated 2026-09-10.

**Phase:** Prompt 1 (foundations) and Prompt 2 (challengers, loss, cascades) both complete. The
project was re-aimed at earthquake prediction on 2026-09-04; **that re-aim changed documents and
one gate, and changed no scientific result.** See § The re-aim.

Maturity: `not started` · `scaffold` (structure, no behaviour) · `stub` (runs, exits
"not implemented") · `working` (offline tests pass) · `validated` (ran on real data; the result is
recorded, whatever it was).

## The re-aim (2026-09-04)

Rupture was built over two phases as a probabilistic seismic forecasting and cascade-loss system,
under a rule set whose first non-negotiable was "no prediction claims" and which enforced a
banned-word gate on `predict`. The owner removed that positioning on 2026-09-04. Rupture is now an
open research project on earthquake prediction. This section records what that did and — more
importantly for a ledger — what it did not.

### What actually changed in the tree

| Change | Commit | State |
|---|---|---|
| The `language` gate and its creed removed | `b641034` | done. `src/rupture/validation/language.py`, its allowlist, its tests, the `validate-language` target, its CI step and its entry in `registry.GATES` and the CI gate-drift check are gone. The creed sentence was stripped from 38 source files; where it was a data value in artefact metadata it was replaced by a scope statement about the artefact. `make validate-rupture` green with **nine** gates; 945 offline tests pass |
| CLAUDE.md rewritten: seven non-negotiables → nine principles | `c2fdd49` | done. Pre-registration, adversarial baselines generalised beyond ETAS, and negative-results-as-deliverables are new; the banned-word list is replaced by the substance rule "quantify or qualify" |
| `docs/RESEARCH_LANDSCAPE.md` written | working tree | new, 1,393 lines. The evidence base: fourteen research lines, the closed doors, an evidence-status vocabulary that adds the `negative-result` category, and the citation rules |
| `docs/ARCHITECTURE.md` rewritten as Part I (design) / Part II (what exists) | working tree | done. **Part I is not built.** Every module in it is labelled "not built" in prose, in the container table and in the C4 diagrams |
| ADRs 0053–0062 added; 0009, 0010, 0015, 0019, 0022, 0034 and 0040 amended | working tree | done. Numbering starts at 0053 because 0051 and 0052 already existed |
| `CONTRIBUTING.md` and `README.md` rewritten | working tree | done |

### What did not change

**Every maturity row in the two tables below is unchanged, and no result was re-run.** The
catalogues, the ETAS fits, the 116 scored windows, the challenger schedules, the leaky ablations,
the GSIM verification, the Gorkha reproduction and the aftershock fits are the same artefacts, at
the same commits, with the same numbers. The re-aim was a change of target and of vocabulary. It
was not a change of evidence, and nothing in this ledger got better because the project became more
ambitious.

Deliberately kept and re-argued rather than relaxed: the leakage controls, the fitted-baseline
requirement, no fabricated data, and provenance on every record. Those are the machinery by which a
prediction claim earns belief. The repository's own leaky ablation — +0.31 to +2.16 nats/event of
manufactured skill — is the argument for keeping them, and it is stronger for a prediction project
than for a forecasting one.

### What the new architecture means for what is built

`docs/ARCHITECTURE.md` Part I proposes a spine built on latency-aware observation sources, a
hypothesis sum type and a scorer registry. **None of it exists.** Checked against `src/` on
2026-09-04:

| Proposed | Present in `src/`? |
|---|---|
| `ObservationSource[T].available_as_of(t)` | **the port exists, nothing implements it** (ADR-0064 decision 5). `src/rupture/ports/observation_source.py` declares it; the catalogue adapters fetch the present and stamp the reported vintage, which measures exposure and cannot reconstruct a past state. Declared without an adapter on purpose, so the next person does not encode a vintage query as a `retrieved_at` filter |
| `available_time` distinct from `valid_time` on every observation | **yes, 2026-09-10** (ADR-0064). `Event.available_time`, populated from ComCat's `updated`; `Catalog.as_of(t, policy)`; `assert_available_before` as rule 4. The sentence to the left was true and is now measured: **69 of the 217 events a 2019-07-01 fit trains on carry a record last modified after that cutoff, and 130 of 130 scored targets were last modified after the window they were scored in.** The new assertion is **not wired into the pipelines** — see below |
| `Vintage` / a vintaged data store / `catalog.as_of(t)` | **partly.** `catalog.as_of(t, policy)` and `VintageSummary` exist; **there is no vintaged store.** One vintage is held, so the exposure is measurable and past values are not reconstructible |
| `CompletenessField`, Mc(x, t) as a field | no. Mc is a scalar per region, estimated from the catalogue itself |
| `Hypothesis` sum type (`RateForecast` \| `SimulatedCatalogues` \| `AlarmSet` \| `HazardFunction` \| `StateEstimate`) | **partly, 2026-09-10.** `HypothesisArm` names all five (`src/rupture/domain/hypothesis.py`) and `AlarmSet` is a real domain type with a real scorer. The other four arms have no type of their own; `ForecastGrid` is still the only other output shape |
| `Scorer` registry with mandatory baselines, power and minimum detectable effect | **partly, 2026-09-10.** `rupture.scoring.registry` exists, keyed by arm, and refuses an unregistered arm by name. One arm of five is registered. Exact power and minimum detectable gain are computed for every alarm score; **the pyCSEP N/M/S/L/CL path is not in the registry and still reports no power**, so the 116 scored windows are unchanged |
| Alarm scoring (Molchan, area skill score, probability gain against a clustering-aware reference) | **yes, 2026-09-10** (ADR-0063). `rupture.scoring.molchan` / `.alarm` / `.schedule` / `.power`, gated by `validate-alarm`, 83 unit tests. Not upstreamed to pyCSEP |
| ETAS-I as a fitted baseline | no. The pinned `lmizrahi/etas@097f08b6` ships the incompleteness machinery and the adapter calls one of its factors, but `baselines/` holds plain ETAS only and nothing in the tree fits ETAS-I |
| Pre-registration enforced by `git merge-base --is-ancestor` (ADR-0056) | no. Pre-registration today is convention plus the challenger pipeline's `select`-before-`fit` hyperparameter freeze. Note also that the CI checkout runs at default depth, and `git merge-base --is-ancestor` exits 128 rather than 1 on a shallow clone, so the gate could not run in CI today even if it existed |
| floatCSEP containerisation / registration in a live CSEP experiment | no |
| The `asof`, `prereg` and evidence/licence gates named in ADRs 0054, 0056, 0058 and 0062 | no. No `src/rupture/validation/<name>.py`, no `mk/<name>.mk`, no CI step, no entry in the workflow's `covered` set |

### What the roadmap has not started

`docs/ROADMAP.md` landed in the working tree on 2026-09-04 and is 1,284 lines: nine research tracks
(T1–T9), each with a failure criterion, plus the tracks Rupture is explicitly not running and a
programme scorecard at 12, 24 and 60 months. **Nothing in it has an owner, a schedule or a costing**
— § 13 item 1 of that document says so in those words — and the scorecard has no mechanism that
causes its questions to be asked.

Of the ten ranked openings the review produced — the as-of layer, the geodetic adjudication and its
detectability harness, Mc as a field, the predictability budget, beating ETAS-I, prospective slow-slip
timing, the non-cascading foreshock census, the global pick reanalysis, fault-state assimilation and
a below-catalogue multimodal model — **none has been started.** No line of code, no fixture, no
pre-registration file. The re-aim produced a target, a map and a design. It has not yet produced an
experiment.

Two claims that underwrite the whole programme are hypotheses and are recorded as such rather than
as findings. First, that latency leakage is material: nobody has measured (final-data skill − as-of
skill) for a set of published models, and if that difference sits inside bootstrap noise everywhere
then the as-of layer should be demoted from an evaluation requirement to a data-engineering
convenience. Second, that an external contributor exists at all: ADR-0053 records the review's
objection that "predict earthquakes" as a public framing may repel the community whose adjudication
confers legitimacy, and makes it falsifiable — if after twelve months no external group has
submitted a hypothesis and no testing centre has adopted the as-of API, the objection was right.

## The alarm arm (2026-09-10)

ADR-0055 declared five hypothesis arms and registered a scorer for none of them; the README's
scoring table listed **Layer 3, alarm scoring, as not built**. It is built now (ADR-0063) and this
section says what that did and did not buy.

| Component | Maturity | What actually ran |
|---|---|---|
| `rupture.scoring` (molchan, alarm, schedule, power, reference, registry, refusals) | validated | 83 unit tests; `mypy --strict` clean; an import-linter contract holds it to `rupture.domain` only, so it can be offered to pyCSEP |
| `validate-alarm` gate | validated | tenth gate, ~40 s, green, wired into CI and into the CI gate-drift ratchet |
| Alarm models (`recent-large-alarm`, any forecast read as an alarm) | validated | six 30-day windows on the committed California fixture, from 2019-07-01 |
| `rupture alarm arms / score / power` | working | exercised by hand and by the gate; `score` has never been run on a stored alarm outside a test, because no alarm set is committed to `data/` |

**The one measured result.** The reference effect that ADR-0055 cites from Zhang et al. (2024) is
now measured in this repository, on its own committed data, with the same alarm and the same
targets in both columns:

| | area skill | p | probability gain *G* | p(G) | minimum detectable *G* |
|---|---|---|---|---|---|
| trivial rule vs **uniform** reference, aftershock window | 0.996 | 0.0004 | 4.91 | 0.042 | 4.39 |
| trivial rule vs **fitted ETAS** reference, same window | 0.354 | 0.75 | 1.09 | 0.85 | none detectable |
| trivial rule vs uniform, **pooled over six windows** | 0.341 | 1 | 0.22 | 0.999 | 1.99 |
| trivial rule vs fitted ETAS, **pooled over six windows** | 0.338 | 1 | 0.049 | 1 | 1.34 |
| ETAS read as its own alarm, pooled | 0.029 | 1 | — | — | — |

Three things in that table are worth more than the headline.

**The single window flatters the rule and the schedule does not.** Pooled over all six windows the
trivial rule scores *worse than the reference it is being compared to* — G = 0.049 — because the
first window is issued on 2019-07-01, three days before the Ridgecrest M6.4, and holds 123 of the
schedule's 130 targets. A rule that can only react to what has already broken has nothing to say
there. Reporting only the aftershock window would have been the exact failure this arm exists to
catch, so both are in the gate's output and both are here.

**The pooled null is a powered null, not a blind one.** At 130 targets and a pooled alarm fraction
of 0.31 the smallest gain the schedule could have rejected the reference for at 80 % power is
G = 1.34. On the single aftershock window, with two targets, the answer is that **no gain whatever
was detectable** — not even a perfect alarm — and the score says so rather than reporting a pass.
That distinction is ADR-0055 decision 5, and it is the first place in this repository where a null
comes with the effect it could have seen.

**ETAS scored against itself pools to 0.029, not 0.5.** The one-half identity holds when the
targets are drawn *from* the reference, which is what the unit tests assert. On real targets the
number measures whether the model put its expected events in the right month as well as the right
place, and ETAS put its mass in the month *after* the mainshock. That is a property of ETAS and it
is not new information about ETAS; what is new is that the alarm arm can express it as one number.

### What the alarm arm did not do

- **It is not upstreamed.** ADR-0061 says the point of writing it is to offer it to pyCSEP, which
  has no alarm-forecast class. Nothing has been offered. The import-linter contract that keeps
  `rupture.scoring` free of everything but `rupture.domain` is the preparation, not the delivery.
- **It scores no external claim.** The whole argument for this arm is that it is where somebody
  else's precursor claim can be adjudicated. No external claim has been submitted or scored, and
  ADR-0053's falsification condition — that no external group submits a hypothesis within twelve
  months — is untouched by this work.
- **It did not give the consistency tests their power figures.** `power.minimum_detectable_information_gain`
  exists and is tested, and nothing calls it from the pyCSEP path. Every one of the 116 scored
  windows and every challenger information gain still ships without power, exactly as before.
- **It did not build ETAS-I**, the reference ADR-0059 requires whenever sub-completeness events
  enter a score. The alarm arm inherits plain ETAS.
- **It does not enforce vintage.** ADR-0054 is unbuilt, so every alarm score carries a note saying
  a revised magnitude is indistinguishable from a timely one. The scorer refuses a reference fitted
  *after* the issue time — the leakage class detectable without a vintage store — and states the
  one it cannot detect rather than implying it checked.
- **The result rests on a 1,433-event test fixture**, not on the three built regions. It is a
  demonstration that the machinery works and that the reference choice is worth a factor of about
  4.5 in *G* here. It is not a regional result and nothing has been promoted.

## Data vintage (2026-09-10)

ADR-0054 proposed an as-of layer; ADR-0064 built enough of it to **measure the thing the layer
would exist for**, and deliberately enforces nothing yet. The § above records this ledger's own
statement that the claim underwriting the layer had never been tested. Here is the first test.

### The exposure, measured on the committed California fixture

| | |
|---|---|
| records carrying a vintage | 1,433 of 1,433 (ComCat `updated`) |
| median `updated − origin` | **191.6 days** (p90 1,069 d, max 2,759 d) |
| events a 2019-07-01 fit would train on | 217 |
| …last modified **after** that cutoff | **69 (32 %)** |
| targets scored across six 30-day windows | 130 |
| …last modified **after** the window they were scored in | **130 (100 %)** |

**Every one of those events passes `assert_all_before`.** The existing leakage assertions are not
weak; they answer a different question. This one had no way to be asked before.

### What moved, and what did not

Restricting the 2019-07-01 ETAS fit to provably-available records:

| | all records | provable vintage only |
|---|---|---|
| training events | 214 | 145 |
| `gamma` | 1.544 | 1.069 |
| total expected in the window | 1.089 | 0.653 |
| N / M / S / L / CL verdicts | fail / pass / fail / fail / fail | fail / pass / fail / fail / fail |

A 40 % change in the headline rate and **no consistency-test verdict flipped.** On this window,
revision cannot reach the result through the training path.

That is **one window, one region, one fixture**, and it is evidence for demoting the as-of layer
from an evaluation requirement to a data-engineering convenience *only if it holds across many*.
It is a first data point, recorded as one.

### What this did not do, and cannot

- **The skill difference is not computed and cannot be from a single vintage.** ComCat's
  `updated` proves a record is *not* the one that existed at *t*; it does not say what that record
  said. The events were in the catalogue at the time with values nobody kept.
- **The ablation bounds one direction.** Dropping unproven records fits a smaller, different
  catalogue. No movement is conclusive; movement is not.
- **100 % target exposure is partly an artefact of fetch date** — a 2026 fetch of 2019 events,
  and ComCat re-touches records for reasons unrelated to magnitude. It bounds what is *provable*,
  not what *changed*.
- **`assert_available_before` is not wired into any pipeline.** Turning it on would move every
  number in the ledger in a single commit with cause and effect entangled. Measure, decide,
  enforce — in that order, and only the first is done.
- **There is no vintaged store and `ObservationSource` has no adapter.** Archived vintages
  (periodic snapshots forward from now, or a provider serving as-of queries) are the next step,
  with a lead time in months.
- **ISC and GCMT carry no vintage**, so their events are `None` and any strict-policy filter
  empties them. That is reported as 0 % coverage, not hidden.

## Prompt 1 — foundations

| Component | Maturity | What actually ran |
|---|---|---|
| Repository, CI, tooling | validated | `uv`, ruff, `mypy --strict`, import-linter. The **offline job** — lint, typecheck, the offline suite and the language, contract, catalogue, ETAS and evaluation gates — has been green on every push. The **bootstrap commit's overall check was red**: `d67a25d` wired the Docker `hazard-integration` job to run on pushes to `main` before any hazard adapter existed, so `validate-hazard` failed once; `42dcd28` narrowed the trigger and every push from `a6a4dce` onward is green. Two further runs show as cancelled by the concurrency group. The claim is "the offline job green on every push", not "CI green on every push" |
| Governance docs, 37 ADRs at this commit | validated | the evaluation protocol was committed **before** any model in this repository was fitted (protocol 02:43, first ETAS adapter 03:26) |
| Language gate | **removed 2026-09-04** | it did pass tree-wide while it existed, and a seeded violation failed it. It was deleted with the positioning it enforced (`b641034`); ADR-0034 is superseded by ADR-0053. Nine gates remain |
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
| Leaky ablation | validated | Leaked variants were run for two of the three models (NTPP and gridded; **none for the ensemble**). The fit leak is worth +0.31 to +2.16 nats/event. **As a fraction of apparent skill: the leakage controls removed 9 %, 63 %, 97 % and 181 % in the four cases where a leaked model had any advantage over ETAS to lose.** On Nepal the NTPP leak (+0.77 nats/event, 181 %) flips the sign of the result. `reports/CHALLENGER_EVALUATION.md` § "What fraction of the apparent skill was leakage" has the table and its sources |
| C2 ground motion (native GSIMs) | validated | BC Hydro reproduces OpenQuake's 22,400 reference values to 5e-7 %, stddev exact; BSSA14 to 0.00067 % at tabulated periods. **These are measured, not ratcheted**: the tests assert the looser registry tolerances (0.01 % / 2 %), so a regression to 0.009 % would pass silently |
| C2 exposure, vulnerability, loss, avoided loss | validated | the serac Trishuli corridor priced end to end; `make underwriting-check` prints USD 675.2M [361.6–996.5M] expected, retrofit avoiding USD 45.0M [32.2–54.5M] |
| C2 FastAPI service | working | tested with `TestClient`; **never served outside tests** |
| C3 ground failure (Nowicki Jessee 2018, Zhu 2017) | validated | against the real USGS product for Gorkha: liquefaction r = 0.45, landslide r = 0.16, both biased low |
| C3 cascade exposure + discriminator client | working | serac has published no slope-unit export yet, so terrain screens report **not applied** |
| C4 aftershock service | validated | Gorkha and Kahramanmaraş at +1 h, +1 d, +7 d. **Under-forecasts the first day 3–12×** |
| Gates | validated | **11 gates** (`registry.GATES`): nine after the `language` gate was removed on 2026-09-04, plus `alarm` (ADR-0063) and `asof` (ADR-0064) on 2026-09-10, both in the CI offline job; the timings below were measured when there were ten and have not been re-measured. `make validate-rupture` is green in 1 min 38 s to 2 min 51 s on an arm64 laptop, with `validate-hazard` **SKIPPED** for the printed reason (amd64-only image on an arm64 host) and the rest PASSED; `promote` refuses without a named approver. Eight run in the CI offline job on every push and pull request, alongside `make underwriting-check`; `validate-hazard` runs in the Docker job on `main`. A CI step compares the workflow's gate list against `GATES` and fails if a gate is registered without one. **`validate-risk` does not start OpenQuake** — it checks rupture's native GSIMs against OpenQuake's own committed expected values instead (ADR-0020), because the container is amd64-only and gates must run offline from a fresh clone. A reader of the brief expecting "OpenQuake runs" inside the risk gate should read that as satisfied only by `validate-hazard`, in CI |
| Evidence and figures | validated | `reports/CHALLENGER_EVALUATION.md` carries six figures — per-window information gain, cumulative pass rates, and honest-against-leaked — rendered from the committed schedule JSON by `python -m rupture.reporting.challenger_plots`, which loads no model and issues no forecast |

## Known gaps

Documentation drift found while re-aiming the project, recorded rather than silently fixed, because
each of these belongs to a file another owner is editing:

- ~~**CLAUDE.md § Make targets is stale.**~~ **Closed 2026-09-10.** It named `language` in the
  `GATES` list and disagreed with its own CI paragraph on the count. Both now say ten and neither
  names `language`; the tuple is still the single source of truth.
- **CLAUDE.md § CLI verbs is wrong about the challenger pipeline.** It says the noun is "**Not
  mounted on `rupture`**" and must be reached through `python -m`. `src/rupture/cli.py:70` does
  `app.add_typer(challenger.app, name="challenger")`, and `rupture challenger --help` works.
- **ADR-0057 accepts operating a prospective board and `docs/ROADMAP.md` has no track for it.**
  The ADR is `accepted` and carries a twelve-month failure criterion; the roadmap's § 8 explains
  the decision and its § 13 item 11 records that nothing schedules, staffs or costs it. Until a
  track exists, ADR-0053's third falsification condition and ADR-0057's own failure criterion are
  stated against something nobody plans to switch on, so neither can fire in either direction.
- **`mk/risk.mk` invokes `python -m rupture.validation.risk` directly**, with a comment saying the
  gate is not registered. It is: `risk` is in `GATES` and `rupture validate risk` runs it. The
  fragment and its comment are stale, though the gate does run.
- **The citation rules are enforced by prose, not by CI.** ADR-0058 fixes an evidence-status
  vocabulary and forbids citing a `rebutted` or `contested` work without its rebuttal in the same
  sentence; nothing checks it. A machine-readable bibliography with status tags would make that
  mechanical and does not exist.
- ~~**No consistency-test or challenger result reports its statistical power.**~~ **Closed for
  the challenger comparisons, still open for the consistency tests (2026-09-10).** Every
  comparison in the committed schedules now carries its minimum detectable effect, derived from
  the interval it already published — arithmetic on committed numbers, nothing re-run
  (`rupture alarm evidence-power`, and `validate-challengers` prints it):

  | region / model | IG (nats/event) | verdict | min detectable at 80 % power |
  |---|---|---|---|
  | türkiye / ensemble-loglinear | **+0.3354** | significant | **0.0866** — 3.9x the detectable effect |
  | türkiye / gridded-convlstm | +0.0587 | null | 0.4564 |
  | nepal / ensemble-loglinear | −0.0789 | null | 0.3390 |
  | nepal / gridded-convlstm | −0.6215 | significant, and **worse** than ETAS | 0.6132 |

  Three things follow. **The one metric ever beaten here is comfortably powered** — the Türkiye
  ensemble's gain is nearly four times the smallest effect its own test could have found, which
  it was not previously possible to say. **Two of the four nulls are near-blind**: Türkiye's
  gridded model saw +0.059 where only +0.456 was findable, so "no skill" says very little about
  it. And Nepal's gridded result is significant *in the wrong direction*, which the sign-aware
  rendering now states rather than reporting a magnitude that reads as skill.

  **Still open:** the N/M/S/L/CL consistency tests. The 116 scored windows report no power, the
  pyCSEP path does not call the power module, and simulation-based power for those tests is not
  built. Khawaja et al.'s point stands unanswered for them.

  **The assumption travels with the figures.** They are derived from intervals that assume
  independent events, which a clustered catalogue violates, so the true detectable effects are
  larger than the table says. A block bootstrap would fix the intervals and these together and is
  not built.

The scientific gaps, unchanged by the re-aim:

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
- **Nepal is sparse, and it is sparse because the catalogue runs out.** 33 of 55 windows held no
  target event, so M, S, L and CL were undecidable in them. The completeness limit is the reason:
  Nepal's published Mc is **4.40** by maximum curvature (+0.2) and **4.70** by b-value stability,
  against a 4.7 target — the target sits *at* the completeness limit, not above it, so the
  threshold cannot be lowered to gather more events without scoring an incomplete catalogue. A
  further **596 Nepal events (about a fifth of the 2,728 built) are reported only as ML or Md**,
  carry `mw = None` under the `strict` policy, and enter neither the Mc estimate nor any fit.
  Türkiye's figures for comparison: Mc 4.30 / 4.60 against a 4.6 target, 4,675 ML/Md-only events.
  The gate's own fixture build reports Mc 4.60 / 4.50 — a smaller slice, a different estimate;
  neither is the published value. See `docs/CATALOG_BUILD.md`.
- **ISC-GEM absent** from every build; **the DVC remote is a local placeholder**; **`log_likelihood`
  is null** on every ETAS fit because upstream does not expose it.
- **`baselines/ntpp/` is committed while `baselines/etas/` and `baselines/gridded/` are not.** The
  neural weights are the only reproducible evidence for a negative result and are small; the
  asymmetry is deliberate and noted here rather than tidied away. **The gridded and ensemble
  *fits* are therefore not retained** — their *scores* are, in
  `reports/challenger/<region>/schedule-<region>-challengers.json`, which is committed.
- **No import-linter contract governs the four Prompt 2 packages relative to each other.** `domain`
  and `ports` are protected from all of them, but nothing stops `cascade` importing `models`, and
  `models` already imports `pipelines` — six import statements across three modules
  (`models/ensemble/protocol_runner.py`, `models/challengers/ntpp/schedule.py`,
  `models/challengers/gridded/challenger.py`) — an inward-facing model reaching into the
  orchestration layer. Unforbidden, and it should not be. The adapter-independence contract is
  likewise still written for the five original families and does not mention `groundmotion`,
  `exposure`, `vulnerability`, `cascade` or `storage`.
- **`src/rupture/reporting/` is a new top-level package with no import-linter contract of its own**
  and no CLI mounting: the challenger figures are redrawn with
  `uv run python -m rupture.reporting.challenger_plots`. It reads committed JSON and writes PNGs,
  and nothing else imports it, so the exposure is small — but it is one more package the layering
  rules do not mention.
