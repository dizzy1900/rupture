# Rupture

**Rupture is an open research project aimed at earthquake prediction.** It exists to measure how
far the predictability of earthquakes can be pushed: how much probability gain over the best
available baseline is achievable, at what lead time, for what magnitude range, and from what
observations. Any computational, statistical or machine-learning method is admissible. The only
requirement is that the result can be scored by someone who did not produce it.

Whether earthquakes can be predicted is an open empirical question. The mainstream position — that
deterministic short-term prediction has never been demonstrated — is a statement about the
historical record, and that record was made with far less data, far less compute and far worse
methods than exist now. "Nobody has done it" was never the same claim as "it cannot be done".
Rupture treats predictability as a quantity to be measured rather than a question to be argued
about, because a project asking "can earthquakes be predicted?" has no way to make progress and a
project asking "does adding continuous GNSS strain to the feature set move information gain at
7-day lead in California, and by how much?" has a research programme, a null result worth
publishing, and a positive result nobody can wave away.

## How you will know whether it is working

The difference between an ambitious research project and a crank project is that the ambitious one
publishes its scoring function before its results and lets other people run it. Rupture's is below.
It has four mandatory layers, none optional, and the last column says honestly which of them exist
in this repository today.

| Layer | What it measures | What it is measured against | State here |
|---|---|---|---|
| **1. Paired information gain** | mean per-event log-likelihood difference from a reference model, in nats per event, with a bootstrap interval | fitted ETAS; **ETAS-I** whenever any event below the completeness limit enters the score; Reasenberg–Jones for aftershock claims; a two-parameter logistic regression for any spatial aftershock model | **built against ETAS** — `lmizrahi/etas` pinned at commit `097f08b6` (MIT), scored through `pycsep==0.8.0`. ETAS-I is **not built**, and it is the baseline most ML claims should have been measured against |
| **2. Consistency tests** | whether a forecast is consistent with what happened, in number, magnitude, space and likelihood | the forecast's own simulated catalogues | **built** — N/M/S/L/CL over 116 scored pseudo-prospective windows. Catalogue-based (non-Poissonian) tests and per-test **statistical power** are **not built**. Power matters: Khawaja et al. (2023, `single-study`) show the S-test cannot reject a uniform global forecast on a 0.1° grid without roughly 32,000 events |
| **3. Alarm scoring** | for any claim that is not a rate grid — Molchan trajectory, area skill score, probability gain *G* at a declared alarm fraction | a **clustering-aware** reference, never a uniform Poisson one. Zhang et al. (2024, `single-study`) found an LSTM's apparent skill vanished when the reference moved from uniform to spatially varying Poisson; Luen & Stark showed a trivial post-M5.5 rule reaches p < 0.001 on clustering alone | **not built.** pyCSEP has no alarm-forecast class. Writing one and upstreaming it is a named, paper-sized contribution — see [CONTRIBUTING.md](CONTRIBUTING.md) |
| **4. Predictability budget** | the gain as a fraction of the estimated remaining headroom, rather than as a bare likelihood | the entropy gap between a Poisson process and the generating process | **not built**, and the framework it rests on (Zhuang & Sornette, 2026) is a `preprint` weeks old at the time of writing. Adoptable as a method; its specific numbers are untested |

Four rules travel with the scoring function and bind every result published here.

**Pre-registration.** An experiment declares its hypothesis, region, magnitude range, lead time,
alarm rate and scoring rule in a committed file *before* it touches the test data. Git is the
timestamp, so anyone can verify from public history that the hypothesis preceded the result. This
is the one thing an open repository can do that a closed lab cannot easily do. Today it is enforced
by convention and by hyperparameter freezing in the challenger pipeline; the mechanical
`git merge-base --is-ancestor` check specified in ADR-0056 is **not implemented**.

**No leakage, and latency is a leakage class.** All evaluation is time-forward with a hard cut, and
this is asserted in tests against real catalogue timestamps rather than in prose. Rupture holds its
own evidence for why: the deliberately leaky ablation in
[reports/CHALLENGER_EVALUATION.md](reports/CHALLENGER_EVALUATION.md) manufactures **+0.31 to +2.16
nats/event** of apparent skill and turns a −0.346 information-gain *loss* on Nepal into a +0.429
apparent *win*. Leakage does not produce small errors; it produces exactly the result you were
hoping for. Timestamp honesty is necessary and not sufficient, because the *value* at time *t* may
not have existed at time *t* — catalogues are revised, GNSS orbits lag, and the first hours after a
mainshock are incomplete in real time in a way the archive never is. Making data vintage a
first-class property of every source is the largest structural change on the roadmap and it is
**not built**; see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) Part I.

**Baselines are adversaries, not straw men,** and a null publishes an upper bound. The commonest way
a published result turns out to be nothing is that it beat the weakest available baseline: DeVries
et al.'s (2018) deep network reached AUC 0.849 on aftershock location and was matched at AUC 0.85 by
a two-parameter logistic regression (Mignan & Broccardo, 2019, `contested` — Meade et al. replied and
the dispute is on the record), with target leakage between collocated ruptures reported
independently. A negative result here states what it could have detected, not just that it saw
nothing: Hirose, Kato & Kimura (2024, `negative-result`) is the template, reporting not "no
precursory slip before Tohoku" but "any preslip was below 5 × 10¹⁸ Nm, about Mw 6.4".

**Evidence carries a status tag, including `negative-result`.** The literature survey this
repository was rebuilt from tagged a *failed* replication of ultra-low-frequency magnetic
precursors (Warden et al., 2020) as a positive replication, because its vocabulary had no category
for "we looked and found nothing". That single inverted tag would have justified funding
magnetometer work on the strength of a null. The category now exists, one work carries one status,
and a `contested` or `rebutted` work is never cited as support without its rebuttal in the same
sentence. The rules are in [docs/RESEARCH_LANDSCAPE.md](docs/RESEARCH_LANDSCAPE.md) § 1 and
ADR-0058.

## What Rupture does not claim

**No method for short-term deterministic prediction of the time, place and magnitude of an
individual earthquake has been demonstrated, and Rupture has not demonstrated one.** That is the
position of the International Commission on Earthquake Forecasting (Jordan et al., 2011) and of
every national agency since; probabilistic forecasting is operational in Italy, New Zealand and the
United States, and prediction is not endorsed anywhere. Nothing in this repository is an alert
system, and its artefacts say so in their own metadata.

This is the reason the project exists rather than a disclaimer bolted to the end of it. The gap
between "no accepted method" and "no possible method" is exactly the space a research programme
occupies, and it is not empty:

- No machine-learning model has beaten a properly fitted ETAS in a registered prospective test.
  EarthquakeNPP (Stockman, Lawson & Werner, TMLR 2026, `negative-result`) tested five neural point
  processes on seven California catalogues; none beat ETAS on temporal or spatial log-likelihood.
- Denser catalogues are not automatically more information. Mancini et al. (2022,
  `negative-result`) fed four catalogues from Mc 2.3 down to Mc 0.2 into ETAS and rate-state models
  and found no significant M3+ information gain, and information *loss* at M1–M2.
- Evaluation protocol dominates architecture. Jover-Alfaro et al. (2026, `negative-result`)
  replicated a 97.97 %-accurate random forest and watched it fall to 21–24 % under walk-forward
  validation, against a 27.69 % baseline.

Read those three as the shape of the problem. They are also the field's most trustworthy results:
the citation audit behind [docs/RESEARCH_LANDSCAPE.md](docs/RESEARCH_LANDSCAPE.md) found that the
null results are the entries whose status tags survived checking, and the positive claims are where
inflation concentrated. A programme built on the field's nulls stands on firmer ground than one
built on its headlines.

## What is built, and what it scored

Rupture did not start as a prediction project. Two earlier phases built a probabilistic seismic
forecasting and cascade-loss system, and that work is the foundation the prediction programme
stands on rather than something to be discarded. All four layers are built and their gates are
green offline; what each of them has *not* done is in the last column, and the longer list is in
[RELEASE_STATUS.md](RELEASE_STATUS.md).

| Layer | Question it answers | Method | State |
|---|---|---|---|
| **F0** Long-term hazard | exceedance probability of ground motion at a site over 50 years | PSHA via OpenQuake; native GSIMs verified against OpenQuake's own committed vectors | built; **no PSHA has been run for any region** |
| **F1** Time-dependent rate forecast | rate of M ≥ m events per cell over the next day, week, month or year | ETAS baseline, three challenger models and a log-linear ensemble, all CSEP-scored | built; **no challenger beat ETAS** |
| **F2** Ground motion → loss | expected loss to a portfolio, and what an intervention avoids | OpenQuake scenario and event-based risk; published `avoided-loss.v1` contract | built; **the loss numbers are not underwriting-grade** |
| **F3** Triggered cascades | what a large event triggers, and where | USGS ground-failure models; discriminator shared with `serac` | built; **runs on shaking alone**, and the Gorkha correlations show what that costs |

The evidence, in numbers:

- **Three catalogues built 1976 → 2026** from ComCat, ISC and GCMT, homogenised with a logged
  magnitude policy: California 110,766 events, Türkiye 7,038, Nepal 2,728.
- **116 scored pseudo-prospective windows** through the CSEP harness, with every leakage assertion
  holding and four deliberately injected violations correctly refused.
- **ETAS baseline of record**: Nepal N 0.93 / M 0.95 / S 0.73 / L 0.77 / CL 0.86 over 55 windows;
  Türkiye 0.91 / 0.93 / 0.69 / 0.90 / 0.86 over 55; California 6 of 55 windows, stopped for a stated
  cost reason. A pass means a test did not reject at α = 0.05. It is not a skill claim.
- **The negative result.** No challenger was promoted. The neural temporal point process scored
  +0.394 nats/event on Türkiye but with **1 paired-T win in 10 windows and 0 Wilcoxon wins in 29**,
  and −0.346 nats/event on Nepal; a positive mean carried by one window in ten is a heavy tail, not
  a win. The log-linear ensemble beat ETAS on information gain in Türkiye alone (+0.335 nats/event)
  and the promotion rule requires two regions of three. This is a published deliverable, not an
  omission — [reports/CHALLENGER_EVALUATION.md](reports/CHALLENGER_EVALUATION.md) has the figures,
  drawn from the committed schedule JSON by a module that loads no model and issues no forecast.
- **What the leakage controls were worth.** Across the four cases where a leaked variant had any
  advantage over ETAS to lose, the controls removed **9 %, 63 %, 97 % and 181 %** of the apparent
  skill. On Türkiye the same leak barely moved pass rates while nearly tripling information gain, so
  neither diagnostic catches it alone.
- **Nine validation gates**, listed in `src/rupture/validation/registry.py`; eight run in the CI
  offline job on every push, `validate-hazard` in the Docker job on `main`, and a CI step fails the
  build if a registered gate has no step.
  `make validate-rupture` completes offline in 1 min 38 s to 2 min 51 s on an arm64 laptop with
  `validate-hazard` skipped for a printed reason (the pinned OpenQuake image is amd64-only). A skip
  without a printed reason is a bug, not a pass.

[RELEASE_STATUS.md](RELEASE_STATUS.md) is the ledger and it under-claims by design; its "Known
gaps" section is the honest list of what this repository cannot do, and its re-aim section says
what the new architecture means for what is and is not built.

## Quick start

```bash
git clone https://github.com/dizzy1900/rupture && cd rupture
make setup                # uv sync — the locked environment, dev group included
make validate-rupture     # everything, offline: lint, mypy --strict, tests, nine gates
uv run rupture --help
```

Two things worth running next, because they are the project's argument in executable form:

```bash
uv run rupture validate eval     # the CSEP harness on fixtures, plus the leakage assertions —
                                 # including four injected violations that must each be refused
make underwriting-check          # the serac Nepal corridor priced against the MHT scenario
```

Everything under `make validate-*` runs offline from a fresh clone on committed fixtures cut from
real catalogues; no fixture is synthesised. Online data pulls and the OpenQuake Docker image are
opt-in (`make test-integration`, `make validate-hazard`). Rupture is not on PyPI; there is no
`pip install rupture`.

## Where to read next

| Document | What it is for |
|---|---|
| [CLAUDE.md](CLAUDE.md) | the nine principles, the repository conventions and the gate wiring. Read first; every one of them binds a pull request from a stranger exactly as it binds the owner |
| [docs/ROADMAP.md](docs/ROADMAP.md) | the research programme: what is being attempted, in what order, with each line's success and abandon criteria |
| [docs/RESEARCH_LANDSCAPE.md](docs/RESEARCH_LANDSCAPE.md) | the evidence the roadmap was built from — fourteen research lines, the closed doors, and the citation rules. Read the closed doors before proposing a direction; a large fraction of the obvious ideas were tried between 1975 and 2000 and the reasons they failed are usually still true |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Part I is the unbuilt re-architecture — latency-aware observation sources, a hypothesis sum type, a scorer registry. Part II documents the system that actually exists. The two are kept strictly apart |
| [CONTRIBUTING.md](CONTRIBUTING.md) | how to contribute, by path, with weekend-sized first tasks |
| [RELEASE_STATUS.md](RELEASE_STATUS.md) | what actually ran, under-claimed on purpose |
| [docs/EVALUATION_PROTOCOL.md](docs/EVALUATION_PROTOCOL.md) · [docs/GLOSSARY.md](docs/GLOSSARY.md) · [docs/adr/](docs/adr/) | the protocol, the two-way glossary, and 59 architecture decision records (numbered to 0062; 0036–0038 were consumed by an earlier renumbering and left as a gap) |

Where those documents overlap, the precedence is fixed and worth knowing before you find a
disagreement: `RELEASE_STATUS.md` is authoritative on anything this repository has actually run,
`docs/RESEARCH_LANDSCAPE.md` § 1.1 on every external number and every evidence-status tag, and the
tree itself — `src/rupture/validation/registry.py` for gates, `src/rupture/cli.py` for CLI nouns —
on what the code does. A document disagreeing with one of those is a defect, and fixing it in the
same pull request is expected rather than optional.

## Three ways in

Rupture needs machine-learning researchers who have never estimated a magnitude of completeness,
and seismologists and geodesists who have never written a training loop. Neither should have to
fake understanding to contribute, and the harness is meant to encode the domain knowledge so that
no single contributor needs all of it. [CONTRIBUTING.md](CONTRIBUTING.md) has the first tasks in
full; this is the shape.

**A — ML and computational research, no seismology required.** Get a green tree, redraw the
committed figures, read the 50 lines of `src/rupture/adapters/forecasting/leakage.py`, then look at
what the leaky ablation bought. The open work is the missing one-neuron comparator, a block
bootstrap to replace the independence-assuming interval behind the one metric ever beaten here, CI
refusal of accuracy and AUC on grid cells, and statistical power reported with every test. The
multi-month version is: **beat ETAS-I, not ETAS.** The pinned `etas` package already ships the
incompleteness machinery and `baselines/` holds plain ETAS only.

**B — Seismology and geodesy.** Your deliverable is not code, it is the null. A hypothesis card
declares a claim, region, magnitude range, lead time, alarm fraction, null model and decision
threshold, and the harness executes and scores it. Seismologists and geodesists own the nulls, ML
contributors own the models, and neither grades their own homework. The adjudication work is real
work: the stalled disputes in this field are stalled because nobody ran the injection-recovery
tests as a pre-registered protocol.

**C — Data and infrastructure, which is where an open project beats a funded lab.** The as-of layer
and the vintaged catalogue store, `available_time` on every provenance record, floatCSEP
containerisation and registration in a live CSEP experiment, and building the Docker image that the
ledger records has never been run anywhere. Rupture interoperates and does not fork: pyCSEP,
floatCSEP, EarthquakeNPP and the CSEP archives exist and are permissively licensed, and extending
them buys the adjudication that a parallel benchmark would not. Be warned that several third-party
assets in this field carry no licence grant at all, which means all rights reserved; the traps are
catalogued in [docs/RESEARCH_LANDSCAPE.md](docs/RESEARCH_LANDSCAPE.md) § 9 and ADR-0062.

Negative results are first-class contributions here, with the same treatment as positive ones. A
line pursued properly and published with its evidence is the thing the literature is worst at
supplying and the thing that stops the next person burning a year.

## Layout

```
contracts/          versioned JSON Schemas published for downstream consumers
docs/               ROADMAP · RESEARCH_LANDSCAPE · ARCHITECTURE · EVALUATION_PROTOCOL · GLOSSARY · adr/
data/regions/       test-region polygons + metadata (california, nepal-himalaya, turkiye-eaf)
data/fixtures/      small real catalogue slices for offline tests, each with provenance
src/rupture/
  domain/           pure models: Event, Catalog, Region, ForecastGrid, EvaluationResult, contracts
  ports/            thirteen Protocols in ten modules: CatalogSource, ForecastModel, Evaluator,
                    HazardEngine, GridStore, Tracker, GroundMotionEngine and its LogicTree and
                    EventBased refinements, ExposureSource, VulnerabilityModel, CascadeModel,
                    SlopeUnitSource. None of them is an observation source; see ARCHITECTURE Part I
  adapters/         ten families: catalogs · sources · forecasting · evaluation · hazard ·
                    groundmotion · exposure · vulnerability · cascade · storage
  pipelines/        build_catalog · fit_etas · run_forecast · evaluate
  risk/             ground motion → damage → loss → avoided loss (F2)
  cascade/          earthquake-triggered ground failure and slope exposure (F3)
  models/           challenger forecast models and the ensemble
  services/         operational products (the aftershock forecast service)
  validation/       the make validate-* gates (nine, listed in validation/registry.py)
  reporting/        figures for reports/*.md, drawn only from committed evidence
  commands/         one typer sub-application per CLI noun
  cli.py            `rupture ...`
infra/              docker/ (the deployment unit) · jobs/ (portable manifests, AWS-annotated)
baselines/          ETAS and gridded fits per region (DVC-tracked); the NTPP weights (git-tracked)
reports/            the published evidence: model cards, protocol and challenger schedules, figures
```

The architecture is hexagonal: `domain/` imports nothing from `adapters/`, enforced in CI by
import-linter. Two edges the contracts do **not** cover are stated in `RELEASE_STATUS.md` rather
than implied — the adapter-independence contract names five of ten adapter families, and nothing
currently forbids `models` importing `pipelines`, which it already does.

## Sibling project

[`serac`](https://github.com/dizzy1900/serac) is a separate standalone repository. The two share
**file contracts only** — `contracts/avoided-loss.v1.json` (the reconciled shape, ADR-0021),
`contracts/avoided-loss.v0.json` (superseded in practice, still published, because a version is
never withdrawn), `contracts/source-type-assessment.v0.json`, and serac's own `slope-unit.v0.json`
in the other direction — never code. serac has published no slope-unit export yet, so rupture's
cascade layer runs on a fallback that labels itself as one and leaves every terrain attribute null
(ADR-0027).

## Licence

Apache-2.0. Data sources carry their own licences, several of them restrictive in ways that
propagate to derived work; see [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md) and ADR-0062.
