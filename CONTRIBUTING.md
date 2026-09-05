# Contributing to Rupture

Rupture is an open research project on earthquake prediction. It exists to measure how far the
predictability of earthquakes can be pushed, and the only way that ambition is reachable is if
people who did not write this repository can add to it. This file is how you do that.

Read [CLAUDE.md](CLAUDE.md) first: it carries the nine principles, and every one of them binds a
pull request from a stranger exactly as it binds the owner. This file does not restate them. It
tells you what to *do*.

**Two readers at once.** Rupture needs machine-learning researchers who have never estimated a
magnitude of completeness, and seismologists and geodesists who have never written a training
loop. Neither should have to fake understanding to contribute. Everything below is written so that
one of you can act on it without the other's background, and where a term belongs to one field the
other gets a sentence of orientation rather than a citation. `docs/GLOSSARY.md` is the longer
version.

If you are an ML researcher, the four things you need before anything else makes sense:

- **ETAS** is the epidemic-type aftershock sequence model: a Hawkes process in which every event
  raises the rate of later events by an Omori-decaying, magnitude-scaled kernel. It is the
  baseline. Nobody has beaten a properly fitted one in a registered prospective test.
- **Mc**, the magnitude of completeness, is the magnitude above which a catalogue is believed to
  contain everything that happened. Below it the catalogue is censored, not sparse, and treating
  censored data as sparse data is the commonest silent error in ML seismology.
- **CSEP** (the Collaboratory for the Study of Earthquake Predictability) is the field's
  adjudication apparatus: N-, M-, S-, L- and CL-tests on gridded rate forecasts, plus paired T-
  and W-tests between two forecasts. `pycsep` implements it and Rupture depends on it.
- **Information gain** is the mean per-event log-likelihood difference between your model and a
  reference. Rupture reports it in **nats per event** (natural log, the pycsep convention);
  divide by ln 2 for bits.

If you are a seismologist or geodesist, the two things that will look like paranoia and are not:

- **Leakage** is any path by which information from after the forecast cut reaches a fit, a
  feature, a hyperparameter choice or a preprocessing step. It is not usually a bug you can see.
  This repository holds its own evidence: the deliberately leaky ablation in
  `reports/CHALLENGER_EVALUATION.md` manufactures **+0.31 to +2.16 nats/event** of apparent skill
  and turns a −0.346 information-gain *loss* on Nepal into a +0.429 apparent *win*.
- **Pre-registration** here means what it means in a clinical trial: hypothesis, region, magnitude
  range, lead time, alarm rate and scoring rule committed to git *before* the test data is
  touched, so that anyone can verify from the public history that the hypothesis preceded the
  result.

## Fifteen minutes to a green tree

Rupture is not on PyPI. There is no `pip install rupture`; the review that shaped this document
recommended one, and it does not exist yet.

```bash
git clone https://github.com/dizzy1900/rupture && cd rupture
make setup                # uv sync — the locked environment, dev group included
make validate-rupture     # everything, offline: lint, mypy --strict, tests, and every gate
```

`make validate-rupture` runs `lint typecheck test` plus `$(VALIDATE_GATES)`. On an arm64 laptop
`RELEASE_STATUS.md` records it completing in 1 min 38 s to 2 min 51 s, with `validate-hazard`
**skipped for a printed reason** — the pinned OpenQuake image is amd64-only — and the rest passing.
A skip without a printed reason is a bug, not a pass.

Everything under `make validate-*` runs offline from a fresh clone on committed fixtures cut from
real catalogues. If any of it reaches the network, that is a defect worth a pull request on its
own; `make test` passes `--disable-socket --allow-unix-socket` precisely so that it fails loudly
rather than quietly succeeding on a machine with a connection.

Python is pinned to 3.12 (`.python-version`, and `requires-python = ">=3.12,<3.13"`). The ETAS
baseline is the `etas` package by Mizrahi et al., pinned to commit `097f08b6` because it is not on
PyPI; evaluation is `pycsep==0.8.0`.

## Three ways in

The review that informed this document identified four contributor populations — ML researchers,
statistical seismologists, geodesists and data engineers — and observed that the core design
problem is that they cannot evaluate each other's work. Rupture collapses the middle two into one
path, because in this repository they share a deliverable (a null model somebody else has to
beat) even though they do not share a method. The consequence is that the third path, data and
infrastructure, is not the junior one. On the review's reading it is the project's actual
comparative advantage over any funded laboratory: the expensive, unglamorous half is the part an
open project can win.

The governing design principle, which the review states more sharply than we would have: **encode
the domain knowledge in the tooling, not in the documentation.** A contributor who has never heard
of short-term aftershock incompleteness should not be able to produce an invalid result by
accident, because the harness refuses it. Where the harness does not yet refuse it, this file says
so rather than pretending.

---

### Path A — you do machine learning and you have never opened a catalogue

**A weekend.** Get the tree green, then go and look at the leakage evidence, because it is the
thing that will decide whether your model is real.

1. `make setup && make validate-rupture`.
2. Read `reports/CHALLENGER_EVALUATION.md`, then redraw its figures from the committed evidence
   with `uv run python -m rupture.reporting.challenger_plots`. That command loads no model and
   issues no forecast; it reads the schedule JSON under `reports/protocol/` and draws. If a figure
   changes, the evidence changed.
3. Look at what leakage buys. `uv run python -m rupture.commands.challenger ntpp ablate` runs the
   deliberately leaky variants — it comes after `select` and `fit`, so if you would rather not
   spend the compute on a first weekend, the committed output is in
   `reports/protocol/<region>/eval/ablations-<region>-ntpp.json`. The fit leak is worth +0.31 to
   +2.16 nats/event. As a fraction of apparent skill, the leakage controls removed 9 %, 63 %,
   97 % and 181 % in the four cases where a leaked model had any advantage over ETAS to lose. The
   181 % is a sign flip. This is the single most useful hour you can spend in this repository.
4. Read `src/rupture/adapters/forecasting/leakage.py`. It is fifty lines and three assertions:
   `assert_all_before`, `assert_within_window`, `assert_issue_after_fit`. Everything Rupture
   claims about leakage rests on them being called in the right places.

**First tasks, each a weekend and each genuinely wanted.**

- **Ship the one-neuron comparator.** Mignan & Broccardo (2019, Nature 574 E1–E3, doi
  `10.1038/s41586-019-1582-8`) reproduced the DeVries et al. (2018) deep-learning aftershock result
  (doi `10.1038/s41586-018-0438-y`, AUC 0.849) with a two-parameter logistic regression at AUC
  0.85. *Evidence status: DeVries et al. is `rebutted`; Mignan & Broccardo is `contested`,
  independently corroborated by the Shah & Innig reanalysis, and Meade's Reply (Nature 574 E4–E5)
  is on the record beside it. The audit behind this document found the critique tagged `replicated`,
  which overstates how closed the exchange is; `docs/RESEARCH_LANDSCAPE.md` § 5 is the register and
  this line cites it rather than restating it.* Rupture has no such comparator in the tree. Adding one, as
  a `ForecastModel` implementation that any spatial claim must be scored against, is a small,
  self-contained, high-value first contribution.
- **Replace the Student-t interval with a block bootstrap.** `RELEASE_STATUS.md` records that the
  one metric a Rupture challenger ever beat — the Türkiye log-linear ensemble, +0.335 nats/event
  information gain over ETAS — "rests on an interval that assumes independent events". Aftershocks
  are the opposite of independent. A bootstrap over contiguous blocks of windows, reported
  alongside the existing paired T-test rather than replacing it, would either firm that number up
  or dissolve it. Either outcome is a result.
- **Make the harness refuse a bad metric.** Jover-Alfaro et al. (2026) replicated a 97.97 %-accuracy
  random forest and watched it fall to 21–24 % under walk-forward validation against a 27.69 %
  baseline, and to 16 % across regions. *Evidence status: negative result.* A unit test that fails
  if any scoring path in `src/rupture/` reports accuracy or AUC over grid cells costs an afternoon
  and closes that failure mode permanently.
- **Report statistical power with every test outcome.** Khawaja et al. (2023) show the CSEP S-test
  cannot reject a uniform global forecast on a 0.1° grid without roughly 32,000 events, where a
  data-driven quadtree grid needs about 8. Rupture's protocol horizon runs on 0.1° grids and its
  regions have far fewer than 32,000 target events, so some of its published "passes" may be
  statements about power rather than about the forecast. Quantifying that is a paper-sized
  contribution that begins as a weekend one.

**What you can own over months.** The line the review ranks highest for an ML researcher is
**beat ETAS-I, not ETAS**. Every claimed ML forecasting gain in the surveyed literature comes from
including events below the completeness threshold, where plain ETAS degrades — and no ML paper has
used ETAS-I, the incompleteness-aware ETAS of Mizrahi et al. (2021), as the comparator. Stockman
et al. (2023, Earth's Future 11(9) e2023EF003777) beat ETAS at input Mcut 1.2 and *tie* at M3+;
QuakeGen (2026) beats the weak USGS Reasenberg-Jones baseline and only *matches* tuned ETAS, and
its code repository returned 404 on 2026-09-04. EarthquakeNPP (TMLR 2026) found none of five
neural point processes beat ETAS on seven California catalogues. *Evidence statuses, from the
register (`docs/RESEARCH_LANDSCAPE.md`, which this line cites rather than restating): Stockman et
al. (2023) and QuakeGen are `single-study`, QuakeGen also `preprint`; EarthquakeNPP is
`negative-result` — the source survey carried it as `replicated` in one section and `single-study`
in two others, and its own headline is that nothing beat ETAS, which is what the tag is for.*

This is tractable here because the pinned `etas` dependency already ships the incompleteness
machinery — `responsibility_factor` and `observation_factor` in `etas/inversion.py` — and
`src/rupture/adapters/forecasting/etas_mizrahi.py` already calls `responsibility_factor` inside
its log-likelihood. What does not exist is ETAS-I fitted and published as a *second baseline*
alongside plain ETAS: `baselines/` holds `etas/` and `ntpp/` and nothing else. Building that, and
then re-scoring the existing challengers against it, is the highest-value multi-month ML task in
the repository, and its failure criterion is stated in advance: if the challenger gains over plain
ETAS are fully absorbed by ETAS-I on every region, the small-event ML result is an artefact of
baseline choice, and that is the publication.

---

### Path B — you do seismology or geodesy and you have never trained a model

Your deliverable is not code, and you should not be persuaded that it is. It is **the null that
somebody else's model has to beat**, and the judgement about whether a claim was scored against
the right thing at all.

The division of labour the review recommends and this project adopts: **seismologists and
geodesists own the nulls; ML researchers own the models; neither grades their own homework.** A
model whose null was written by the same person who wrote the model has not been tested.

**A weekend.**

1. Read `docs/EVALUATION_PROTOCOL.md` end to end. It fixes regions, thresholds, grid, horizons,
   tests, significance levels, schedule, leakage rules and the promotion rule in advance, and it
   was committed before any model in this repository was fitted (protocol 02:43, first ETAS
   adapter 03:26, both on 2026-09-03). If a rule in it is wrong, say so — see *How disagreement is
   resolved* below. Changing one requires an ADR that states what was known at the time.
2. `uv run rupture region show california` (also `nepal-himalaya`, `turkiye-eaf`) and check the
   fitted Mc against your own judgement. Rupture sets `Region.mc` only when maximum-curvature
   b ≥ 0.7 and Mw coverage at the target is ≥ 80 %, and otherwise leaves it null and prints why.
   Nepal's and Türkiye's target thresholds rose from provisional 4.5 and 4.0 to published 4.7 and
   4.6 under ADR-0019 as a result. If that rule is wrong for a region you know, that is a finding.
3. `uv run rupture catalog inspect <dir>` on a built catalogue, and read the homogenisation log.
   ADR-0017 fixes the source precedence, association windows and magnitude conversions. Magnitude
   inconsistency between catalogues is one of the three causes Mancini et al. (2022) diagnose for
   why denser ML catalogues produced *no* significant M3+ information gain and information *loss*
   at M1–M2. *Evidence status: negative result, and one of the most load-bearing in the field.*

**First tasks.**

- **Write a null, not an opinion.** Pick any published prediction or precursor claim and write
  down the null model it should have been scored against, in enough detail that someone else could
  implement it: the reference process, its parameters, how it is fitted, what alarm rate and
  spatial footprint it is matched on. Luen & Stark showed a trivial "declare an alarm after every
  M5.5" rule reaches p < 0.001 purely from clustering; Zhang et al. (2024) showed an LSTM's
  apparent skill vanished when the reference moved from uniform Poisson to spatially varying
  Poisson. Nakatani's (2020) review puts every non-triggering phenomenon at probability gain
  G < 20 and mostly around 2, which is the effect size any such experiment must be powered to
  detect. A null written this way is a merged contribution whether or not code follows it.
- **Seed the rebuttal ledger.** The closed cases should be recorded once, with their evidence
  status, so that nobody re-litigates them without new data: Corralitos ULF (a sensor
  malfunction), acceleration of moment release (a fitting artefact reproducible in synthetic
  catalogues), VAN (failed the 1996 tests), Heki-type TEC enhancement (comparable enhancements
  occur at random comparably often), the 72 % foreshock prevalence (18–33 % under ETAS nulls; 3 of
  53 mainshock-specific), and the Norcia animal-behaviour study (whose own authors conceded no
  predictions are possible). `docs/RESEARCH_LANDSCAPE.md` is where CLAUDE.md says this lives.
- **Review an Mc estimate or add a region.** `uv run rupture region init` writes the three default
  region files and refuses to overwrite a fitted `mc` without `--force`. A fourth region needs a
  polygon, a threshold, a magnitude policy and provenance for each — and a defensible answer to
  whether the b ≥ 0.7 rule holds there.

**What you can own over months.** Two lines, both ranked in the review's top three.

**Completeness as a field.** No Rupture catalogue currently ships Mc as a spatially and temporally
resolved field with uncertainty; it ships point estimates per region. Four independent research
lines each stalled on the absence of Mc(x,t), and shipping it converts dense ML catalogues from a
liability into an asset. The success criterion is stated in advance and is falsifiable: ETAS and
ETAS-I fits on Mc-corrected dense catalogues should recover stable b-values and productivity
parameters across catalogue versions of the same sequence. If parameter stability does not improve
after correction, the Mancini failure is spatial discretisation rather than completeness, and the
line closes.

**Geodetic adjudication.** The strongest unresolved precursor claim is Bletery & Nocquet's stacked
two-hour precursory slip signal, and the honest state of it is: leaning negative, unsettled. The
authors concede common-mode filtering removes the signal but argue the filter removes tectonic
signal too; injection tests by Bradley & Hubbard indicate the filter preserves 80–95 % of
earthquake-like synthetic signal and that three events dominate the stack — *but those critiques
carry DOIs and are Substack posts, not peer review, and must be cited as such.* The peer-reviewed
piece of the record is Hirose, Kato & Kimura (GRL 2024), which stacks independent tiltmeters,
finds no acceleration, and bounds any Tohoku preslip below 5 × 10¹⁸ Nm (~Mw 6.4). *Evidence
status: negative result, and by the audit's assessment one of the most trustworthy entries in the
whole bibliography.*

Note the shape of that last result, because it is the template for every negative result Rupture
publishes: not "we saw nothing" but "anything there was smaller than this number".

---

### Path C — you build data and infrastructure

The review's assessment, which we accept: this is where an open project beats a funded laboratory,
and where the work is most legible to volunteers. It is also where the highest-ranked opening in
the entire review sits.

**A weekend.**

1. Clone fresh, disconnect the network, and run `make validate-rupture`. It is supposed to pass
   offline. The first thing that reaches out is a bug and a pull request.
2. Read `dvc.yaml` and `.dvc/`; `data/` and `baselines/` are DVC-versioned.
3. Read `mk/README.md` and `mk/cascade.mk`. A gate registers itself by dropping a one-line
   fragment; nobody edits the `Makefile`. This is the mechanism that lets several worktrees add
   gates without merge conflicts, and it is the pattern any new gate follows.
4. Build the Docker image. `RELEASE_STATUS.md` says of it: "**the image has never been built or
   run anywhere**". Building it and running `make validate-rupture` inside it closes a known gap
   in a single afternoon.

**First tasks.**

- **The as-of layer, prototyped on one source.** This is opening #1 in the review and the argument
  for it is sharp: timestamp honesty (train `t < T`, test `t > T`) is necessary and *insufficient*,
  because the values at time `t` may not have existed at time `t`. Catalogues are revised, events
  are added and deleted, GNSS orbits lag, satellites revisit on a schedule. Girona & Drymoni's
  Anchorage detection depends on USGS events later removed from the catalogue and vanishes on the
  current one — a published result invalidated by a data-vintage effect. Rhoades et al. (2018)
  record that the New Zealand CSEP testing centre did not consistently capture its own real-time
  catalogue, so most of its results were reprocessed. Hainzl et al. (2024) quantify short-term
  aftershock incompleteness as roughly a 162 s blind time, meaning the real-time catalogue in the
  window that matters is a *different object* from the archive.

  The prototype is small: a daily snapshot of one catalogue source with a revision diff, and a
  `catalog.as_of(t)` reader over it. Every leakage assertion in this repository would pass while a
  model read the future through data vintage; none of them can currently express the failure.

- **Type every observation with two times.** Provenance today carries `source`, `source_url`,
  `retrieved_at`, `sha256`, `licence` and `adapter_version`. It does not carry *available_time* —
  when the value first existed in the form the model read. Adding it, and a gate that fails any
  evaluation reading a value whose `available_time` is not strictly before the forecast issue time,
  is the structural change that makes latency leakage detectable rather than arguable.

- **Containerise the ETAS baseline for floatCSEP.** floatCSEP (JOSS, February 2026) runs whole
  prospective experiments from a YAML file with Docker-pinned models and a `reproduce` command.
  Registration in a real CSEP experiment is now a day of engineering rather than a multi-institution
  negotiation, and third-party testing is the credential this project needs most.

**What you can own over months.** The as-of layer end to end, across ComCat, SCEDC, INGV and
GeoNet, with per-source latency models — and then the replay report that is its whole point: for
every model in this repository, skill on final data minus skill on as-of data. Its failure
criterion is stated in advance: if that delta is within bootstrap noise for every model and every
sequence, latency is not a practical leakage class and the layer is demoted to a data-engineering
convenience rather than an evaluation requirement.

**On licences, because this path touches them most.** The audit behind this document found the
licence column of the surveyed asset list unreliable in both directions. Assume nothing; check the
repository, not the paper. Four assets listed with licences have **none**, which means
all-rights-reserved, not "unattributed": seisLM (the arXiv preprint's CC-BY was mistaken for the
code's), FusionEarthquake, slow-slip-forecasting and CREW. RECAST is UC Santa Cruz
**Noncommercial** — re-implement, do not vendor. GEM hazard, exposure and vulnerability products
are CC BY-NC-SA 4.0; ISC-GEM is CC BY-SA 3.0 and ShareAlike propagates to any catalogue derived
from it; OpenQuake is AGPL-3.0, which is network copyleft if served. pyCSEP has moved to
`github.com/cseptesting/pycsep` and the old path fails through the GitHub API even though it
redirects in a browser. Rupture is Apache-2.0 and every dependency must be compatible with that.

---

## What a model submission is

A model submission is not a pull request containing a notebook and a number. It is four artefacts,
in this order, and the order is enforced.

### 1. The interface

Implement `rupture.ports.forecast_model.ForecastModel`, a runtime-checkable `Protocol`:

```python
class ForecastModel(Protocol):
    model_id: str
    model_version: str

    def fit(self, catalog: Catalog, region: Region, cutoff: datetime) -> FitResult: ...

    def forecast(
        self, history: Catalog, issue_time: datetime, horizon: timedelta
    ) -> ForecastGrid: ...

    def parameter_snapshot(self) -> dict[str, Any]:
        """The parameters the next ``forecast`` call would use; hashed into every grid."""
```

The contract in its docstring is the whole leakage rule: `fit` uses only events with
`origin_time < cutoff`; `forecast` uses only events with `origin_time < issue_time` as history.
`parameter_snapshot` exists so that the parameters actually used are hashed into every grid — you
cannot later claim a forecast was issued from different parameters than it was.

Your model lives under `src/rupture/models/challengers/<name>/`, with an adapter that implements
the port. `src/rupture/models/challengers/ntpp/` is the worked example: `model.py`, `kernels.py`,
`train.py`, `adapter.py`, `schedule.py`, `simulate.py`, `ablation.py`.

**Say plainly what this interface cannot express, because it is a great deal.** A `Catalog` in and
a rate grid out cannot represent continuous seismic or acoustic energy, GNSS displacement, DAS
strain, tremor rate, a completeness field, a data vintage, an alarm (region + window +
declare/don't), a hazard function, or a fault-state estimate. The signals with the strongest
surviving evidence in the literature are all below the catalogue, and this port makes them
inexpressible. `docs/ARCHITECTURE.md` carries the re-architecture; until it lands, a submission
that needs any of the above should open an issue rather than contort itself into a rate grid.

### 2. The pre-registration

Before you touch the test data, commit a file declaring the hypothesis, region, magnitude range,
lead time, alarm rate (where applicable), scoring rule, the baseline you are claiming to beat, and
**your failure criterion** — the result that would make you abandon the line. Git is the timestamp
and the history is public, so anyone can verify that the hypothesis preceded the result. This is
the one thing an open project can do that a closed laboratory cannot easily do.

The mechanism already exists in miniature. The challenger pipeline runs in a fixed order and each
verb refuses to skip a step:

```
uv run python -m rupture.commands.challenger ntpp select | fit | issue | schedule | ablate
```

`select` chooses hyperparameters on a validation window ending at or before the cutoff and writes
the frozen record; nothing later runs without it. `fit` trains on `origin_time < cutoff` with the
frozen configuration. `schedule` runs the whole pseudo-prospective sequence. `ablate` runs the
deliberately leaky variants, **which are never results**. (The sub-application *is* mounted on the
`rupture` CLI — `src/rupture/cli.py` does `app.add_typer(challenger.app, name="challenger")` — so
`uv run rupture challenger ntpp select` and the `python -m` form above are the same command. Any
document in this tree still saying the noun is reachable only through `python -m` is stale;
CLAUDE.md § CLI verbs is the one that says it, and `RELEASE_STATUS.md` § Known gaps records it.)

What is *not* yet built, and is proposed rather than delivered: a runner that refuses to score
unless `git merge-base --is-ancestor <pre-registration commit> <commit introducing the test data>`
succeeds. That check is enforceable rather than aspirational, and it is a wanted contribution.

### 3. The evaluation

Your model is scored under `docs/EVALUATION_PROTOCOL.md` on the same grid and magnitude bins as
ETAS, so the two are directly comparable under pycsep: 0.1° cells, 0.1-wide magnitude bins, a
30-day protocol horizon, N/M/S/L/CL consistency tests at α = 0.05 with 1000 simulations, and
paired T- and W-tests against the baseline.

The promotion rule is encoded exactly once, in `src/rupture/models/promotion.py`, and
`make validate-challengers` recomputes every published verdict from that module over the committed
evidence — so no promotion claim in this repository can be editorial. Three conditions:

| Condition | What it requires |
|---|---|
| 1 — consistency | N-, M-, S- and L-test pass rates each at or above ETAS's, over at least `MIN_CONSECUTIVE_WINDOWS` = 12 *consecutive* protocol windows (the longest run at the exact schedule step, not a count) |
| 2 — skill | Beats ETAS in the paired T-test at α = 0.05 with positive information gain per event over those windows: one test over the schedule's pooled target events, not a majority of per-window tests |
| 3 — regions | Conditions 1 and 2 hold in at least `MIN_REGIONS` = 2 of the three protocol regions. A region never evaluated is not a pass; it is reported by name |

Two rules of construction hold throughout that module and are worth internalising. **Undecidable is
not passed** — where the evidence cannot decide a condition, the condition is not met and the
reason is carried into the verdict. And **nothing in it knows which model it is judging**: the
functions take pass rates and test results, never a model object, so the same code judges your
challenger, the baseline against itself, or a fixture.

**Your baseline is an adversary, properly fitted, or your result is nothing.** For catalogue rate
forecasting that is ETAS, and — whenever your model uses events below the completeness threshold —
ETAS-I. For an alarm-based claim it is a random alarm set matched on alarm rate and spatial
footprint. For a spatial aftershock model it is the two-parameter logistic regression. Rupture has
plain ETAS fitted and published for all three regions; it does not yet have the others, which is
why building them is listed above as wanted work rather than assumed as present.

### 4. What you get back

- A **model card** in `reports/MODEL_CARD_<name>.md`, following the existing ones, whose promotion
  row is machine-read by `make validate-challengers` and fails the gate if the card and the
  recomputed rule disagree (ADR-0040).
- **Per-window information gain**, CSEP pass rates and the paired-test outcome, in
  `reports/protocol/<region>/eval/`, redrawable from committed evidence by
  `python -m rupture.reporting.challenger_plots`.
- A **verdict** computed by the rule, not by the author.
- A row in `RELEASE_STATUS.md`, which under-claims by design.

And if it loses, you get a published negative result with your name on it. That is not a
consolation prize here; see principle 7 and the process below. The honest precedent is the whole
of Prompt 2: three challenger models and an ensemble, each run over the full 55-window
pseudo-prospective schedule in two regions, and **no challenger promoted**. The one metric ever
beaten — Türkiye ensemble information gain, +0.335 nats/event — held in one
region of three and rests on an interval that assumes independent events. That is the published
result, and it is in the ledger in exactly those words.

### The other kind of submission: a hypothesis card

Not every contribution is a model. A **hypothesis card** is a declaration a seismologist or
geodesist can write without writing code: a claim, its region, magnitude range, lead time, alarm
fraction, null model and decision thresholds, in a form the harness executes and scores. The
review recommends this as the primary deliverable for Path B, and we agree.

**It does not exist yet.** There is no hypothesis-card schema in `contracts/`, no runner, and no
alarm-based scorer anywhere in the tree — `Evaluator` scores rate grids only, and pycsep has no
alarm-forecast class either. Adjudicating an alarm claim needs a Molchan trajectory, an area skill
score, probability gain against a clustering-aware reference, and the alarm fraction reported with
it. Building that is one of the clearest paper-sized contributions available here, and upstreaming
it to pyCSEP is worth more than keeping it.

## The review bar

This is a welcome mat, not a compliance document. Almost everything below exists because a claim
in this field's history collapsed on it, and none of it exists because of a preference.

**What gets a contribution merged.**

A claim with its number, its baseline and its protocol in the same breath. A negative result
reported with the same care as a positive one, and with the minimum effect it could have detected.
Code that passes `make validate-rupture` offline from a fresh clone. Tests that assert leakage
control against real catalogue timestamps rather than describing it in prose. Fixtures that are
real slices with `provenance.json`. Documentation that agrees with the code, and a
`RELEASE_STATUS.md` entry that under-claims. A small commit that explains *why*.

**What gets it rejected.**

- **Leakage.** Any path where post-cutoff data reaches a fit, a feature, a hyperparameter choice or
  a preprocessing step. This is the `qa-reviewer` veto and it is not negotiable, because leakage
  does not produce small errors — it produces exactly the result you were hoping for, which is why
  it is invisible from the inside.
- **An unfitted or straw-man baseline.** Beating the weakest available reference is the commonest
  way a published result turns out to be nothing. If your baseline's diagnostics are not published
  alongside your model's, it was not fitted.
- **An unquantified claim.** "Model X improves on ETAS" is not publishable here. "Model X gains
  0.11 ± 0.04 nats/event over ETAS across 22 pseudo-prospective 30-day windows in California,
  paired T-test p = 0.03" is. If the number does not exist yet, the sentence says **untested**.
- **Fabricated or synthesised data presented as real.** Adapters fetch or fail loudly; no adapter
  returns synthesised rows; no test passes on data it invented; unknowns are `null`, never
  guessed. Synthetic data from a physics simulator is welcome as *training* input and is labelled
  synthetic everywhere it appears.
- **Random splits, and accuracy or AUC on grid cells.** Walk-forward or nothing. See Jover-Alfaro
  et al. (2026) above, and note that AUC hid a 5.4 % precision in the DeVries et al. result.
- **A pre-registration written after the fact**, and any post-hoc parameter choice.
- **Counting sources instead of weighing them.** "Six papers agree" is not an argument, and in the
  bibliography behind this document it would often have been an artefact: the audit found roughly
  13 works duplicated across sections, several carrying contradictory statuses in different
  copies. Cite the work, its status and its scope condition.
- **Citing a rebutted or contested work as support without its rebuttal in the same sentence.**
- **Network access in `tests/unit`**, silent skips, docs that disagree with code, and an
  over-claiming ledger.
- **A `TODO` without an issue reference.** One `TODO` exists in the tree and it is not Rupture's:
  it is inside the USGS ground-failure reference implementation vendored verbatim at
  `tests/fixtures/cascade/usgs_groundfailure/jessee_2018.py.txt:113`, which the fixture rule
  forbids editing.

**Evidence-status vocabulary.** When you tag a cited work — in `docs/RESEARCH_LANDSCAPE.md`, a
model card, an ADR or a pull request — use this vocabulary, and use one canonical record per DOI.
It is fixed by ADR-0058; `docs/RESEARCH_LANDSCAPE.md` § 1.1 is the register, this table is a copy,
and if the two ever differ the register is right:

| Tag | Means |
|---|---|
| `established` | reproduced by independent groups and/or in operational use for years |
| `replicated` | reproduced at least once by a named group with no authors in common with the original |
| `widely-used` | third parties depend on it in published work or shipped software, and the dependants are nameable |
| `single-study` | one group, one result, not yet independently reproduced — the default for anything new |
| `contested` | a substantive published disagreement exists and the question is open |
| `rebutted` | a published rebuttal stands and must be cited with it |
| `negative-result` | the paper's own finding is that the effect is absent, or bounded below a stated level |
| `preprint` | not peer-reviewed — a modifier, combined with one of the above |
| `unverified` | Rupture has not checked the venue, metadata or content; temporary, and never on a load-bearing citation |

The `negative-result` category is here because its absence caused a specific, documented error:
Warden et al. (2020) was tagged `replicated` when the paper is a **failed replication** of ULF
precursor findings that reports no significant precursory activity for 2013–2018 and explicitly
urges caution about electromagnetic earthquake-precursor research. As tagged it was the strongest
apparent positive in an entire section, and it inverts the paper's finding. Two further rules
follow: **a work weeks or months old cannot be `replicated` or `widely-used`**, whatever it
achieved; and **the same work must not carry different statuses in different documents**.

## How disagreement is resolved

Four kinds of disagreement, four different answers, and the first three are short.

**1. Disagreement about what the repository does.** The tree wins. `src/rupture/validation/registry.py`
is the authority on gates, `src/rupture/cli.py` on CLI nouns, `ls contracts/` on the published
contract surface, `Makefile` plus `mk/*.mk` on targets, and `RELEASE_STATUS.md` on what has
actually run. Run the gate; whoever is right, the documentation gets fixed in the same pull
request.

**2. Disagreement about a convention or a design decision.** ADRs, in `docs/adr/`. A settled ADR is
not re-litigated in a pull request; you write a new ADR that supersedes it and update the status of
the old one. Format: Status / Date / Context / Decision / Consequences / Alternatives considered.
The point is not bureaucracy — it is that the reasoning survives the person, and that "we already
discussed this" is a link rather than a memory.

**3. Disagreement about whether a change is safe.** The `qa-reviewer` role holds a veto, and its
grounds are enumerated in CLAUDE.md: leakage, a result published without its protocol and
baseline, an experiment scored against a pre-registration written after the fact, fabricated or
synthetic data presented as real, network access in `tests/unit`, silent skips, docs that disagree
with code, an over-claiming `RELEASE_STATUS.md`. A finding must be fixed before the next merge. A
veto is not an opinion about quality; it is a statement that one of those eight things is present.

**4. Disagreement about whether a result is real.** This is the one that matters and the one that
cannot be settled by authority, seniority or eloquence.

The rule is: **a challenge is an experiment, not an argument.** If you believe a result in this
repository is an artefact, the response Rupture owes you is not a rebuttal in a comment thread. It
is a merged pull request in which you pre-register the null, the ablation or the alternative
baseline that would expose the artefact, and then run it. Rupture supplies the harness so that
this is cheap: the schedule runner, the leakage assertions, the ablation machinery and the
promotion rule are all already in the tree, and the ablation pipeline exists precisely so that
"what if this is leakage?" is a command rather than a debate.

Three constraints on how that plays out.

*Nobody grades their own homework.* The null a model is scored against is signed off by someone
who did not write the model. In practice that means a seismologist or geodesist reviews the null
for an ML contributor's model, and an ML contributor reviews the fitting and evaluation code
behind a seismologist's hypothesis card. This is the division of labour that makes the project
work; it is not a formality and a pull request that skips it is incomplete.

*A red-team contribution is a first-class contribution.* If your deliverable is a failed
replication — of a Rupture result or of anybody else's — it is credited exactly as a positive
result is. The field's de facto red team currently operates unpaid and outside peer review, and
institutionalising that function is one of the more valuable things an open project can do.

*Where the experiment cannot settle it, the ledger records the disagreement rather than picking a
winner.* If two readings of the same evidence both survive the tests either party can afford to
run, `RELEASE_STATUS.md` states both, names the evidence each rests on, and states the minimum
effect the available data could have detected. An unresolved disagreement recorded honestly is
worth more than a resolved one recorded by fiat, and it tells the next contributor exactly what
experiment would break the tie. Merge authority still rests with the maintainer, but merge
authority is not authority over the wording of a result.

### Negative results are deliverables — the process, not the slogan

Principle 7 says a line pursued properly and failed, published with the evidence, is a
contribution to this repository and to the field. That needs mechanism, so:

1. **The failure criterion is declared before the results exist.** Every pre-registration states
   the outcome that would make you abandon the line. A line abandoned against a criterion written
   in advance is a result; a line abandoned against one written afterwards is a rationalisation.
2. **A null states an upper bound, not an absence.** "We saw nothing" is not a finding. "Any
   preslip was below 5 × 10¹⁸ Nm, roughly Mw 6.4" is — that is Hirose et al. (2024) and it is the
   template. Every Rupture negative result reports the minimum detectable effect at the achieved
   sensitivity, with the protocol that establishes it.
3. **It ships with the same care as a positive.** A model card, the committed evidence, the
   figures redrawable from that evidence, and a row in `RELEASE_STATUS.md`. `reports/CHALLENGER_EVALUATION.md`
   is the existing worked example: four models, none promoted, six figures, and a table of what
   fraction of each model's apparent skill was leakage.
4. **It is not quietly downgraded later.** A negative result is superseded by a new experiment
   with its own pre-registration, not by a subsequent positive result that did not run the same
   protocol.

## Practical matters

**Setup and gates.** `make setup` (`uv sync`), then `make validate-rupture`. That aggregate is
`lint typecheck test` plus `$(VALIDATE_GATES)`.

| Target | What it does |
|---|---|
| `make help` | list targets |
| `make lint` | ruff check + ruff format --check + `lint-imports` |
| `make typecheck` | `mypy --strict` |
| `make test` | offline unit + contract suite, sockets disabled |
| `make test-integration` | opt-in: network / Docker tests, marked `integration` |
| `make schema-export` / `schema-check` | regenerate, or drift-check, `contracts/*.json` from the domain models |
| `make validate-<gate>` | one gate; each runs `uv run rupture validate <gate>` |
| `make validate-rupture` | everything, offline |
| `make promote` | refuses unless every gate is green **and** `PROMOTE_APPROVED_BY` names a human |
| `make underwriting-check` | prices the serac Nepal corridor against the MHT scenario end to end |
| `make clean` | caches, plus `git clean -fdX reports` — the *ignored* files only; committed evidence and model cards are left alone |

The gate names are the `GATES` tuple in `src/rupture/validation/registry.py`, which as of this
commit holds **nine**: `schema`, `catalog`, `etas`, `eval`, `hazard`, `cascade`, `risk`,
`aftershock`, `challengers`. That tuple is the single source of truth; if this file and the tuple
disagree, the tuple is right and this file is stale.

**Adding a gate.** Write `src/rupture/validation/<name>.py` exposing `run(repo_root: Path) ->
GateResult`; add the name to `GATES`; drop `mk/<name>.mk` containing `VALIDATE_GATES +=
validate-<name>` (and, if the name is new to the `Makefile`, its own `.PHONY` target, as
`mk/cascade.mk` does); add a step to the CI offline job and list the name in that job's `covered`
set. The last step of the offline job compares `covered` against `GATES` and fails if they
disagree, so a gate cannot be registered and then quietly never run. A gate must be offline-safe or
skip with a **printed** reason; a silent skip is a bug. `GateStatus` is one of `PASSED`, `FAILED`,
`SKIPPED`, `NOT_IMPLEMENTED`.

**What CI runs, and when.** The **offline job** runs on every push, on any branch, and on every
pull request: ruff, `mypy --strict`, import-linter, the offline suite, the eight offline gates and
`make underwriting-check`. A feature branch pushed before its pull request exists gets the same
signal as one pushed after; the concurrency group cancels superseded runs. The
**`hazard-integration` job** pulls the pinned `openquake/engine:3.26.2` image and runs
`make validate-hazard` plus the Docker integration tests, on pushes to `main` and on manual
dispatch. It sets `RUPTURE_HAZARD_REQUIRE=1`, so a skip there is a failure. Locally,
`make validate-hazard` skips with a printed reason where Docker is absent or the host is arm64.

**Architecture.** Hexagonal, and enforced. `src/rupture/domain/` holds pure pydantic v2 models and
imports nothing from any outer layer; `src/rupture/ports/` holds `Protocol` classes and imports
only `domain`; `adapters/` implement ports. All three are import-linter contracts in
`pyproject.toml` and fail CI. Two things the contracts do **not** cover, stated rather than
implied: the adapter-independence contract lists five families (`catalogs`, `sources`,
`forecasting`, `evaluation`, `hazard`) and not the newer ones (`groundmotion`, `exposure`,
`vulnerability`, `cascade`, `storage`); and nothing forbids `cascade` importing `models`, or
`models` importing `pipelines`, which it already does in four places. Both are in
`RELEASE_STATUS.md` § Known gaps. Do not read a green `lint-imports` as a statement about those
edges.

**Tests.** `tests/unit` is offline (sockets disabled), `tests/integration` is opt-in and marked
`integration`, `tests/contract` covers JSON Schema round-trips and the fixtures shared with
`serac`. Fixtures are real slices, never synthesised, each with a `provenance.json`, never edited
by hand — regenerate with the adapter and re-record provenance instead. Some are third-party files
vendored verbatim (renamed `.py` → `.py.txt` so ruff and mypy skip them); Rupture's rules about the
contents of Rupture's own files do not apply to those.

**Timestamps** are UTC and timezone-aware everywhere (ruff's `DTZ` rules are on). Windows and
cutoffs are half-open `[from, to)`.

**Parallel work and the worktree rule.** Contributors working in parallel use separate `git
worktree`s branched from the same commit, each with its own `uv` venv, and touch only their own
subtrees plus their own tests, docs and `mk/<name>.mk` gate file. Shared files (`Makefile`,
`pyproject.toml`, `cli.py`, `dvc.yaml`) are pre-sectioned so additions are append-only —
`src/rupture/commands/challenger.py` is the clearest example: each challenger registers its own
typer sub-app and touches nothing else in the file. Merges are real merges, never `format-patch`,
performed serially by the maintainer, and `make validate-rupture` runs after **each** merge before
the next one starts. A `qa-reviewer` finding is fixed before the next merge.

**Data, credentials and money.** Ask before downloads greater than 5 GB or any paid API call.
Credentials go in `.env`, never committed, loaded with python-dotenv; nothing is required for the
offline suite. See `docs/CREDENTIALS.md` and `docs/DATA_SOURCES.md`.

**Interoperate; do not compete.** pyCSEP, floatCSEP, EarthquakeNPP, SeisBench and the CSEP
archives exist and are permissively licensed. Extending them buys credibility with exactly the
people whose adjudication Rupture needs; forking them buys isolation. If a scorer you write here is
useful outside Rupture, upstream it.

**Licence.** By contributing you agree your work is licensed under Apache-2.0 (see [LICENSE](LICENSE)).

## Known gaps in this document

Under-claiming applies to this file too. These are the things it describes that are not yet true,
or that it could not verify:

- **The hypothesis card, the alarm scorer and the null-model review board are proposed, not
  built.** There is no card schema in `contracts/`, no runner, no Molchan or area-skill
  implementation, and no standing review board — the sign-off described above is a norm this
  document is establishing, not a mechanism the tooling enforces. Until a scorer exists, an
  alarm-based claim cannot be adjudicated in this repository at all.
- **The pre-registration ancestry check is not implemented.** The `git merge-base --is-ancestor`
  gate described under *the pre-registration* is a proposal. What exists today is the ordered
  challenger pipeline whose `select` step freezes hyperparameters before `fit`.
- **ETAS-I is not a fitted baseline here.** The pinned `etas` dependency carries the incompleteness
  terms and Rupture's adapter calls `responsibility_factor`, but `baselines/` contains plain ETAS
  and the NTPP challenger only. Any claim in this file that a submission "must beat ETAS-I" is a
  standard being set, not a comparator you can currently run.
- **No `as_of` reader, no `available_time` field, no latency gate.** The entire Path C weekend
  programme above is greenfield.
- **CLAUDE.md § Make targets says the `GATES` tuple holds ten and names a `language` gate.** The
  tuple holds nine and there is no `src/rupture/validation/language.py`; the banned-word gate was
  removed with the positioning it enforced. CLAUDE.md's own rule is that the tuple wins, so the
  count in that section is stale. Flagged rather than silently corrected, because CLAUDE.md is not
  this document's to edit.
- **Parts of the tree still carry the old positioning.** `README.md`, `CLAUDE.md` and the documents
  under `docs/` were rewritten in the re-aim, but the creed sentence survives where it is a *data
  value* rather than prose: `pyproject.toml`'s `description` field still reads "rupture does not
  predict earthquakes", and it is repeated in `reports/PROMPT2_SUMMARY.md`,
  `reports/MODEL_CARD_ntpp.md`, `reports/MODEL_CARD_aftershock.md` and `reports/MODEL_CARD_risk.md`,
  plus the `note` field of the committed evaluation summaries under `reports/smoke/`. The model
  cards and summaries are committed evidence and changing them changes an artefact, so this is not
  a find-and-replace; the `pyproject.toml` description is, and it is a legitimate first pull
  request on its own.
- **The contributor pathways are untested.** No external contributor has yet walked any of these
  three paths. The weekend tasks are sized by inspection of the code, not by measurement, and the
  first person to try one should record how long it actually took — including where it went wrong,
  which is the more useful half.
