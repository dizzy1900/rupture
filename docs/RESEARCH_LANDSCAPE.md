# Research landscape — what has been tried in earthquake prediction, and what survived

**This is the evidence base `docs/ROADMAP.md` was built from.** It maps the computational and
machine-learning attempts on earthquake prediction by research line: what each line claims, the
strongest work supporting it, the strongest work against it, whether it has ever passed a
prospective test, what open code and data exist, and where it stands today. The **closed doors**
section is the most useful part of the document and the part to read first if you are choosing what
to work on, because a large fraction of the obvious ideas have been tried and the reasons they
failed are usually still true.

Two readers are assumed at once: a machine-learning researcher with no seismology, and a
seismologist with no machine learning. Terms from either side are expanded on first use or defined
in `GLOSSARY.md`. Neither reader should have to fake understanding to contribute.

The document is written under the rule that binds every other document in this repository:
**quantify or qualify**. Every claim below carries its number, its baseline and its protocol, or it
says plainly that no number exists. Where a work is contested, the contest is in the same sentence
as the claim.

Compiled 2026-09-04 from a fourteen-dimension literature survey and an adversarial citation audit
of roughly 230 entries. Everything in it is second-hand unless it is a statement about this
repository, which is checked against the tree. See § 8 for what that means for how much you should
trust it.

---

## 1. How to read this document

### 1.1 Evidence status

Every cited work carries a tag. The tag describes the **status of the claim**, not the prestige of
the venue, and it is the first thing to read.

This table is the register: ADR-0058 fixes the vocabulary and names this section as its normative
copy, and `CONTRIBUTING.md` reproduces it for contributors. Where any of the three differ, this one
is right.

| Tag | Meaning |
|---|---|
| `established` | reproduced by independent groups and/or in operational use for years |
| `replicated` | reproduced at least once by a named group with no authors in common with the original |
| `widely-used` | third parties depend on it in published work or shipped software, and the dependants are nameable |
| `single-study` | one group, one result, no independent reproduction found |
| `contested` | a substantive published challenge exists and the dispute is unresolved |
| `rebutted` | the central claim has been shown to be unsupported, and the rebuttal stands |
| `negative-result` | the finding **is** that an effect is absent, or bounded below a stated value |
| `preprint` | not peer-reviewed (a modifier, combined with one of the above) |
| `unverified` | the survey could not confirm the work's venue, metadata or content |

**One ambiguity, resolved rather than left to the reader.** A tag in backticks beside a citation is
that *work's* status. The `**Status.**` paragraph closing each research line in § 3 is the state of
the *line* — "`rebutted` for the automatic downstream benefit" is a verdict on a research
direction, not a tag on Mancini et al., which is a `negative-result`. The words are shared because
inventing a second vocabulary for lines would be worse; the position on the page is what
distinguishes them.

`negative-result` is a category the source survey's vocabulary did not have, and its absence caused
a real error: a failed replication of ultra-low-frequency (ULF) magnetic precursors was filed as a
positive replication and became, as tagged, the strongest apparent evidence in the entire precursor
section. The category exists here so that a paper whose contribution is "we looked and found
nothing" is not silently converted into "we looked and found something".

Five rules apply to every citation in this repository:

1. **A `rebutted` or `contested` work is never cited as support without its rebuttal in the same
   sentence.** Not in a footnote, not in the next paragraph.
2. **Nothing published within the last twelve months carries `replicated`, `widely-used` or
   `established`** unless a named independent replication is cited alongside it. Novelty and
   adoption are different properties and the second one takes time.
3. **One canonical record per DOI, one status.** The same paper arguing for opposite conclusions in
   two sections of the same document is a defect, and it occurred in the source survey in at least
   eight cases.
4. **Never count sources.** The source survey duplicated roughly thirteen works across sections, so
   any statement of the form "N independent sources agree" overstates the evidence base. Argue from
   the strongest single piece of evidence and name it.
5. **A negative result is cited with its bound.** "No precursor was observed" is weak. "Any preslip
   was below 5 × 10^18 N m, equivalent to about Mw 6.4" is a measurement, and it is the form every
   null in this repository takes.

### 1.2 What "passed a prospective test" means here

Throughout this document, a model has passed a prospective test only if the model was frozen and
registered — publicly, with a verifiable timestamp — **before** the data it was scored on existed,
and if it was scored by someone other than its authors against a declared reference model. Nothing
weaker counts. In particular:

- A *retrospective* analysis fits and scores on data that already existed. Almost the whole
  precursor literature is retrospective.
- A *pseudo-prospective* analysis honours a time cut — train before, test after — but the analyst
  knew what happened. This is the standard in the statistical seismology literature and it is what
  this repository's own baseline schedule does. It is much better than a random split and much
  weaker than prospective.
- A *prospective* test issues into the future. The Collaboratory for the Study of Earthquake
  Predictability (CSEP) runs these; almost nothing from the machine-learning side has ever entered
  one.

By that standard, **as of September 2026 no machine-learning model has beaten a properly fitted
ETAS baseline in a registered prospective test**, and no precursor has been validated. Both
statements are about the historical record, not about what is possible.

### 1.3 The three problems, which are in radically different states

Earthquake prediction is not one problem. Reading the literature as if it were is the fastest way to
draw a wrong conclusion.

**Detection is solved, and it did not help — yet.** Deep-learning phase picking and event
association have unambiguously won, delivering roughly one magnitude unit of extra completeness. And
feeding those denser catalogues into the standard forecasting models produced no measurable gain
(§ 3.1). Density without a completeness model is not information.

**Forecasting has not moved.** ETAS — an epidemic-type aftershock sequence model, in which every
earthquake triggers offspring at a rate decaying as a power law in time and distance — remains
unbeaten prospectively. Every apparent machine-learning win concentrates in one regime, small events
below the completeness threshold, and is measured against the wrong baseline (§ 3.2, § 3.3).

**Precursors are mostly rebutted, with two live exceptions.** The rebuttal record is dense and
specific (§ 3.6, § 3.9). The exceptions worth attention are the residual population of foreshock
sequences that survive a clustering null, and months-scale slow slip before *some* megathrust
events.

---

## 2. Notation and units used below

- **Information gain (IG)**, in nats or bits per event: the mean difference in log-likelihood
  between a model and a reference model, per target earthquake. Positive means the model assigned
  more probability to what actually happened. One nat ≈ 1.44 bits. This is the currency; a claim
  without it is not comparable to anything.
- **Probability gain G**: the ratio of the earthquake rate inside an alarm to the rate outside it.
  Used for alarm-based (rather than rate-forecast) claims.
- **Mc**: magnitude of completeness — the magnitude above which a catalogue is believed to contain
  every event. It varies in space and time, and pretending it does not is the source of several
  results below.
- **CSEP consistency tests** (N, M, S, L, CL): whether a forecast's event *number*, *magnitude*
  distribution, *spatial* distribution and *likelihood* are consistent with what was observed.
  "Passing" means the forecast was not rejected at α = 0.05; it is not evidence of skill.
- **Molchan diagram / area skill score**: the alarm-based analogue — miss rate plotted against the
  fraction of space-time occupied by alarms.

---

## 3. Research lines

### 3.1 Detection, picking and catalogue enhancement

**The claim.** Deep learning applied to raw waveforms detects far more earthquakes than analysts do,
and a denser catalogue is a better substrate for everything downstream, including forecasting.

**Strongest support.** The first half of the claim is settled. Ross et al. (2019, Science
364(6442):767–771) [`established`] template-matched the entire Southern California archive with
248,000 templates on 200 GPUs and turned ~180,000 analyst events (2008–2017) into 1.81 million,
dropping completeness from about M 1.7 to M 0.3. Deep pickers — PhaseNet (Zhu & Beroza 2019, GJI
216(1):261–273) [`established`], EQTransformer (Mousavi et al. 2020) [`established`] — plus modern
associators deliver a factor of 5–10 more events routinely: Central Italy 2016–17 went from 73,009
events at Mc 2.3 to 900,058 at Mc 0.2. At the extreme, Ni et al. (2025, Seismica 4(2),
doi 10.26443/seismica.v4i2.1738) [`single-study`] ran PhaseNet over 1.3 PB from 47,354 stations
(2002–2025) on cloud infrastructure in under three days and released 4.3 billion P and S picks
(2.8 billion P, 1.5 billion S) as an open database.

**Strongest rebuttal — of the second half.** Mancini et al. (2022, JGR Solid Earth,
doi 10.1029/2022jb025202) [`negative-result`] fitted ETAS and Coulomb rate-and-state models to four
Central Italy catalogues spanning Mc 2.3 down to Mc 0.2 and found **no significant information gain
at M 3+ and information loss at M 1–2**. The diagnosed causes are specific: 2 km spatial
discretisation cannot use sub-kilometre relocation precision; magnitudes are inconsistent between
catalogue versions for the same events; and validation metrics are themselves catalogue-dependent.
This is the field's central under-appreciated fact.

Two further constraints on the detection layer itself. Aguilar Suarez & Beroza (2025,
arXiv:2511.09805) [`single-study`] audited 8.6 million examples across eight standard labelled
datasets with a model ensemble and found a **3.9% average label error rate** (0–8% per dataset):
unlabelled events, events sitting inside "noise" windows, wrong onsets. And Ma et al. (2026,
arXiv:2605.22837) [`single-study`, `preprint`] showed that scaling model size is the wrong lever: a
roughly 120× larger teleseismic PhaseNet gained 15.6% precision and 23.2% recall while losing 87% of
GPU throughput, whereas *retraining* from scratch on teleseismic data gained 741.5% P recall.
Distribution, not capacity, is the binding constraint.

**Prospective record.** Not applicable in the forecasting sense; pickers are evaluated on held-out
labelled data, and the SeisBench cross-benchmark (Münchmeyer et al. 2022, JGR Solid Earth,
doi 10.1029/2021JB023499) [`established`] is the reference comparison — six models across eight
datasets, PhaseNet best overall, mild degradation across regions and failure across distance
regimes.

**Open code and data.** SeisBench (GPL-3.0), PhaseNet / GaMMA / QuakeFlow / ADLoc (MIT), PyOcto
(MIT), PhaseNO (MIT), EQcorrscan (LGPL), the QuakeScope pick database (data CC0, code MIT). All
listed in § 9.

**Status.** `established` for detection, `rebutted` for the automatic downstream benefit. **Do not
build another picker or associator.** The layer is won and openly licensed; the open problem is
*what to do with density*, which is a completeness-modelling problem (§ 3.14), not a detection one.

---

### 3.2 The incumbent: ETAS and its incompleteness-aware variant

**The claim.** Most short-term earthquake predictability is clustering: earthquakes trigger
earthquakes, with rates given by well-established empirical laws (Omori decay in time, a power law
in distance, Gutenberg–Richter in magnitude). A statistical model of that triggering is the best
available short-term forecast, and any new method must beat it.

**Strongest support.** Thirty years of prospective CSEP results and operational deployment.
Reasenberg–Jones and ETAS underlie the USGS operational aftershock forecasts (public since August
2018), GNS Science's New Zealand forecasts (since 2010), and OEF-Italy. The CSEP California
benchmark archive (Serafini et al. 2025, Scientific Data 12:1501,
doi 10.1038/s41597-025-05766-3) [`established`] holds more than 50,000 daily gridded forecasts from
25 models over 2007–2018, scored against 571 M ≥ 3.95 targets — the closest thing in the field to a
real prospective track record.

The important refinement is **ETAS-I** (Mizrahi, Nandan & Wiemer 2021, JGR Solid Earth,
arXiv:2105.00888) [`single-study`], which jointly estimates ETAS parameters and short-term
aftershock incompleteness — the systematic loss of small events in the minutes to hours after a
large one, when the record is saturated. ETAS-I **significantly outperforms plain ETAS
pseudo-prospectively in California**, precisely by modelling the small events that plain ETAS
mishandles. This matters enormously for § 3.3: it is the correct baseline for every
machine-learning claim that draws its gain from small events, and **no machine-learning paper has
used it as a comparator.**

**Strongest rebuttal.** ETAS is not a theory of earthquakes and does not pretend to be. It carries
no information about the next magnitude beyond Gutenberg–Richter, it assumes a spatially fixed
background rate that fails during sequences, and in the ten-year CSEP Italy experiment no model —
ETAS included — adequately described spatial clustering (Iturrieta et al. 2024,
doi 10.1785/0220230247) [`single-study`]. Physics-based Coulomb rate-and-state forecasts match but
do not beat it (Hardebeck 2021, doi 10.1029/2020JB020824; Cattania et al. 2018,
doi 10.1785/0220180033) [`replicated`].

**Prospective record.** Yes — the only model class with one.

**Open code and data.** `lmizrahi/etas` (MIT) implements calibration, simulation, forecasting,
space-time-varying completeness and event-based log-likelihood; it is the ETAS used inside the
EarthquakeNPP benchmark and by QuakeGen. `opensha-oaf` (CC0) is the USGS operational
Reasenberg–Jones and ETAS code. pyCSEP (BSD-3-Clause) is the scoring engine.

**Status.** `established`, and the baseline every claim in this repository is measured against.
**Rupture already depends on it**: `pyproject.toml` pins `etas` to commit `097f08b6` from
`lmizrahi/etas` and `pycsep==0.8.0`, and `src/rupture/adapters/forecasting/etas_mizrahi.py` is the
adapter. **ETAS-I is not wired in**, which is a named gap (§ 7).

---

### 3.3 Neural point processes and deep catalogue forecasting

**The claim.** A neural model of the catalogue as a point process — a marked sequence of events in
space, time and magnitude — can learn triggering structure that ETAS's fixed functional forms
cannot, and so forecast better.

**Strongest support, and its exact scope.** Three results, each with a scope condition that is
routinely dropped when they are cited:

- Stockman, Lawson & Werner (2023, Earth's Future 11(9):e2023EF003777,
  doi 10.1029/2023EF003777) [`single-study`]: a magnitude-marked neural point process on the
  enhanced Central Apennines catalogue reaches **parity with ETAS at input threshold M ≥ 3 and beats
  it when the input threshold is lowered to M 1.2**, because ETAS degrades on incomplete data. The
  gains concentrate in the first hours after the Norcia mainshock. ETAS with Gutenberg–Richter still
  beats the neural magnitude model.
- Zlydenko et al. (2023, Scientific Reports 13:12350) [`single-study`]: Google's FERN encoder–
  decoder on the JMA catalogue with strict temporal splits (train to 1995, validate to 2003, test
  2004–2011, ending before Tohoku) gains **4–12% information gain per event (~0.1 bits) over ETAS
  only in the FERN+ configuration that uses smaller-magnitude events**, at 1000× faster inference.
- Dascher-Cousineau et al. (2023, GRL 50:e2023GL103909) [`single-study`]: RECAST, a GRU-based
  temporal point process, beats a temporal ETAS on Southern California **only when the training set
  exceeds about 10^4 events**.

Every one of these gains comes from small events, and every one is measured against **plain ETAS
rather than ETAS-I**. The honest reading is that what has been demonstrated so far is
robustness-to-incompleteness, measured against a baseline that was never designed for incomplete
data.

**Strongest rebuttal.** EarthquakeNPP (Stockman, Lawson & Werner, arXiv:2410.08226, TMLR
2026) [`negative-result`] built seven California datasets (1971–2021, Mc 0.6–3.0, 12,000–128,000
training events) with chronological splits, an open ETAS baseline and CSEP tests, and found that
**none of five off-the-shelf spatio-temporal neural point processes (NSTPP, DeepSTPP, AutoSTPP,
DSTPP, SMASH) beat ETAS** on temporal or spatial log-likelihood. ETAS passed 77.8–97.6% of daily
CSEP N/S/PL tests; SMASH passed 51–88%, DSTPP 0–89%, including 0% on two datasets' N-test. The
diagnosed failure is architectural: the models lack magnitude marks and truncate history to roughly
twenty events, so they collapse exactly during the large sequences that matter. The same paper found
that the machine-learning community's prior Japan benchmark (Chen et al. 2021) had alternating-split
leakage and had removed the 2011 Tohoku sequence as an outlier.

Corroborated by Tian, Stockman, Zhang & Werner (Earth's Future 2026,
doi 10.1029/2025ef007318) [`single-study`]: domain-informed DeepSTPP variants remain inferior on
overall spatiotemporal log-likelihood.

**The 2026 hybrids, and what they have not done.** Fusion (Xiong et al., arXiv:2608.18791)
[`single-study`, `preprint`] combines an LSTM history encoder with an ETAS Omori kernel and
Gutenberg–Richter magnitudes, and reports the highest mean temporal log-likelihood on all five
EarthquakeNPP catalogues — but the margin is "higher likelihood than ETAS on 54.9–58.4% of target
events", there is no magnitude gain over Gutenberg–Richter, and the study is retrospective and
non-spatial. NMRP (Zhan, Zhuang & Wu 2026, Earth's Future, doi 10.1029/2025EF007342)
[`single-study`] reports matching and sometimes surpassing ETAS log-likelihood with substantially
less history. **Neither ran CSEP generative consistency tests**, which is the test EarthquakeNPP
showed the earlier generation failed. That gap is a well-scoped opening, not a criticism of intent.

**Prospective record.** None. Werner et al. (SCEC 2025 abstract) [`unverified`] report marginal
temporal information gains over USGS forecasts for the Ridgecrest and Puerto Rico sequences and that
generative neural point processes underperform in catalogue-based evaluation.

**Open code and data.** EarthquakeNPP (MIT) — datasets, splits, ETAS baseline and five model
wrappers. RECAST is under a **UC Santa Cruz Noncommercial licence**: reimplement, do not vendor.
FusionEarthquake has **no licence at all** (§ 9.7).

**Status.** `rebutted` for off-the-shelf neural point processes; `contested`, leaning promising, for
magnitude-marked long-memory hybrids. The decisive experiment is cheap and nobody has run it: score
a hybrid against **ETAS-I** with paired information gain and bootstrap confidence intervals, plus
10,000-catalogue CSEP consistency tests.

---

### 3.4 Generative spatial-field forecasting

**The claim.** Rather than modelling a stream of events, generate the whole spatial rate field
directly with an image-generative model conditioned on recent seismicity.

**Strongest support.** QuakeGen (Zhu 2026, arXiv:2607.24109) [`single-study`, `preprint`], a
conditional diffusion U-Net producing 64 × 64 log-rate and maximum-magnitude fields, trained on
about 2,050 global M 4.5+ sequences (2.2 million events, 1990–2023) plus the QTM Southern California
catalogue. On 80 held-out 2024–25 mainshocks it reports spatial information gain **3.65 versus 2.23
nats at 3 hours** against the USGS Reasenberg–Jones baseline, and on the EarthquakeNPP 2016–17
windows **1.66 versus 1.49 nats** against a locally tuned ETAS, with a productivity ratio of 1.01
against ETAS's 0.80. It captures fault-aligned anisotropy, which grid-smoothed models do not.

**The scope condition that must travel with it:** Reasenberg–Jones is a *weak* baseline, and against
tuned ETAS the result is a match, not a win. It reports no CSEP consistency tests, it is
non-autoregressive, it degrades on the largest sequence in its test set (the 2025 M 8.8 Kamchatka
event), and as of 2026-09-04 the code repository returned 404 — the archived forecasts are on OSF
but the model is not reproducible.

Lesser results in the same family: Zhang, Zhan, Huang & Sornette (2025, GJI 240(1):81–95,
doi 10.1093/gji/ggae373) [`single-study`] report a fully-connected network whose Molchan area skill
is **within 0.01 of a spatially variable ETAS** for M 3 and M 4 and ahead only for M 5+ (few events),
at 2000–4000× lower calibration cost — a speed result, not an accuracy result. CL-ETAS (Zhang, Ke,
Liu & Zhang 2024, GJI 239(3):1545–1556) [`single-study`] passes pyCSEP N and PL tests where its ETAS
comparator fails, but that comparator used a fixed α and therefore fails N-tests — this is the
weak-baseline problem in reverse, and it is why "our model passed where ETAS failed" is not by
itself a claim.

**Strongest rebuttal.** None specific to the class; it is too new. The general constraint is that
Poisson grid tests are inadequate for over-dispersed seismicity, and that the S-test cannot reject
even a uniform global forecast on a 0.1° grid without roughly 32,000 events, against roughly 8 on a
data-driven quadtree grid (Khawaja et al. 2023, GJI 233(3):2053) [`single-study`]. **Every test
result must therefore ship with its statistical power**, or a "pass" means nothing.

**Prospective record.** None.

**Status.** `single-study`, `preprint`, not independently reproducible. It is the most interesting
2026 forecasting result and the highest-value replication target in the field.

---

### 3.5 Deep learning on static stress for aftershock patterns

**The claim.** A deep network trained on computed stress-change fields around a mainshock predicts
where aftershocks will occur, better than the classical Coulomb failure stress criterion.

This line is closed. It is treated in full as the worked example in § 5, because how it closed is
more instructive than the fact that it closed.

**In one paragraph:** DeVries et al. (2018, Nature 560:632–634, doi 10.1038/s41586-018-0438-y)
[`rebutted`] reported AUC 0.849 against 0.583 for Coulomb failure stress. Mignan & Broccardo (2019,
Nature 574:E1–E3, doi 10.1038/s41586-019-1582-8) [`contested`, independently corroborated] matched it
with a two-parameter logistic regression (AUC 0.85) and beat it with logistic regression on
distance-to-rupture and mean slip (AUC 0.86), at unchanged precision of 5.4%; Meade's reply (Nature
574:E4–E5, doi 10.1038/s41586-019-1583-7) [`single-study`] did not dispute the numbers and reframed
the paper as physical inference. Independently, Shah & Innig documented target leakage between
collocated training and test ruptures. Separately, Sharma et al. (2020, JGR Solid Earth,
doi 10.1029/2020JB019553) [`single-study`] showed across 289 SRCMOD slip models that classical
Coulomb failure stress is itself outperformed by maximum shear and von Mises metrics — so the
original baseline was weak on both sides.

**Reopens if:** the inputs are measured rather than modelled, splits are grouped by sequence and
chronological, and precision/recall and information gain are reported against both the logistic and
the ETAS/Omori-distance baselines on held-out sequences.

---

### 3.6 Foreshocks, nucleation and real-time discriminators

**The claim.** Large earthquakes are preceded by identifiable small-earthquake activity that differs
from ordinary aftershock clustering, and that difference can be detected in real time.

**Strongest support, after correction.** The headline number collapsed under scrutiny and what
remains is small but real. Trugman & Ross (2019, GRL, doi 10.1029/2019GL083725) [`contested`]
reported foreshocks before 72% of M ≥ 4 Southern California mainshocks in the dense QTM catalogue.
Against an ETAS-consistent null — that is, asking whether the pre-mainshock activity exceeds what
ordinary triggering already predicts — van den Ende & Ampuero (2020, GRL,
doi 10.1029/2019GL086224) [`replicated`] obtained 33%, or 18% once temporal fluctuations are
accounted for, and Moutote et al. (2021, GRL, doi 10.1029/2020GL091757) [`replicated`] found 10 of
53 mainshocks (19%) above ETAS expectation with only about 3 looking mainshock-specific. The
observation that foreshocks are common stands; the precursory *interpretation* is what was
rebutted.

Globally the number is smaller still: Nishikawa & Koyama (2025) [`single-study`] find significant
foreshock acceleration before only 3–4% of large earthquakes — but report that where it does occur
it is **not** explained by aftershock cascades, which implies a driver they could not observe. That
residual is the live target.

Mignan (2014, Scientific Reports 4:4099) [`established`] is the gating result across 37 studies:
anomalous foreshock behaviour appears **only when the catalogue is complete to about three magnitude
units below the mainshock**. Completeness, not sensors, is the lever.

**The real-time discriminator.** Gulia & Wiemer (2019, Nature 574) [`contested`] proposed that a
drop in b-value — the slope of the magnitude-frequency distribution — after an M ≥ 6 event flags it
as a foreshock, reporting 95% classification on 58 sequences ("foreshock traffic light system").
Dascher-Cousineau, Lay & Brodsky (2020, SRL, doi 10.1785/0220200082) [`single-study`] found the
system flagged Ridgecrest M 6.4 but was ambiguous at the M 7.1 onset and highly sensitive to expert
parameter choices; the 2021 comment/reply exchange did not settle it; Li & Luo (2024, GJI
237:1554) [`single-study`] then showed that maximum-likelihood, b-positive and KMS b-value
estimators **all fail under realistic real-time incompleteness and magnitude error**. The authors
released an automated b-positive version in 2024 (SRL 95(6), doi 10.1785/0220240163); its prospective
2016–2024 record exists only as a conference abstract [`unverified`].

The consequence is sharp and worth stating on its own: **this dispute cannot be settled on archival
catalogues at all**, because the quantity in question behaves differently in the real-time catalogue
than in the reprocessed one. It is a latency problem (§ 3.14) wearing a seismology costume.

**A newer, falsifiable proposal.** Lippiello et al. (2025, GRL, doi 10.1029/2025GL115466)
[`single-study`] define a "Q index" from the first 45 minutes of ground-velocity envelope after an
M 6+ event, flagging 10 of 11 foreshocks against 4 of 57 non-foreshocks — in selected regions. It is
a concrete real-time rule awaiting global pseudo-prospective testing, which is a well-scoped project.

**Prospective record.** None for any foreshock discriminator.

**Open code and data.** QTM catalogue (public, SCEDC terms); the ETAS-null methodology is published
but there is no maintained package implementing it — building one and running it across every
ML-enhanced catalogue is a concrete contribution.

**Status.** `contested`. Prevalence claims are `rebutted`; the residual non-cascading population is
open and is the strongest remaining seismicity-based line.

---

### 3.7 Geodetic precursors: the stacked-GNSS episode and what is actually there

**The claim.** Fault slip accelerates measurably before rupture, and geodesy — GNSS, tilt, strain,
InSAR — can see it.

**Strongest support, and why it is unresolved.** Bletery & Nocquet (2023, Science 381:297–301,
doi 10.1126/science.adg2565) [`contested`] stacked 3,026 five-minute GNSS displacement series over
the 48 hours before 90 Mw ≥ 7 earthquakes (2000–2020), projected onto the direction expected from
slip at each hypocentre, and found a **~2-hour exponential acceleration**. The authors state that
current instrumentation cannot detect this for individual events.

**Strongest rebuttal.** Bradley & Hubbard (2023, 2024; Earthquake Insights, with DOIs, but **not
peer-reviewed** — the 2024 post is doi 10.62481/0ff960fa) [`contested`] showed that subtracting
far-field (>200 km) common-mode noise removes the signal — the Tohoku amplitude falls by about 90% —
that far-field noise **alone**, fed through the original code, regenerates the same hockey stick,
that **three events** (El Mayor-Cucapah 2010 plus two Tohoku-related) drive the final spike of the
110-event stack, and that the common-mode filter **preserves 80–95% of injected earthquake-like
signal** (93–97% in one framing), so the removal is not deleting real slip.

The peer-reviewed piece of the record is Hirose, Kato & Kimura (2024, GRL,
doi 10.1029/2024GL109384) [`negative-result`]: an independent stack of tiltmeter records before
Tohoku shows no acceleration-like deformation in the two hours before the mainshock, bounding any
preslip below **5 × 10^18 N m (~Mw 6.4)**, smaller than the ~Mw 6.9 implied by the GNSS stack. This
is the model for how a null should be published — with a number, not with an absence.

Bletery & Nocquet (2025, Seismica 3(2), doi 10.26443/seismica.v3i2.1383) [`contested`] concede that
common-mode filtering removes the signal, argue the filter also removes tectonic signal, report
spatial and rake consistency, put the probability that common-mode noise produced it "well below
1%", and conclude their tests "do not irrefutably demonstrate" a precursory phase. No independent
group has replicated the positive result.

**Net position:** unresolved, leaning negative. It is also the single most tractable open dispute in
precursor science, because **both sides released full code and data** and four new M 7.5+ events
(Kahramanmaraş 2023, Noto 2024, Hyuga-nada 2024, Kamchatka 2025 M 8.8, Myanmar 2025 M 7.7) are
out-of-sample with respect to the original stack. What is missing is not data but an
injection-recovery curve: the minimum detectable precursory moment as a function of lead time and
station density. Nobody has published one.

**What geodesy does show.** Weeks-to-months-scale slow slip before *some* subduction earthquakes is
not disputed: Tohoku 2011 (Kato et al. 2012, Science; Ito et al. 2013) [`replicated`], Iquique 2014
(Boudin et al. 2021, GJI 228(3):2092) [`replicated`] — four aseismic events Mw 5.8–6.2, 100–180 km
from the hypocentre, resolvable only by fusing tilt with GPS — and foreshock migration at about
7 km/day before the 2025 Mw 8.8 Kamchatka earthquake (Zhang et al. 2026, GRL,
doi 10.1029/2025GL120956) [`single-study`]. The signal is weeks-long, near-field, off-hypocentre and
multi-sensor. It is not a universal two-hour signal.

**Where machine learning genuinely works in geodesy today** is transient *detection*, not
prediction: Costantino et al. (2023, Communications Earth & Environment, arXiv:2305.19720)
[`single-study`] detect 78 Cascadia slow-slip events over 2007–2022 at 87.5% recall of the catalogue;
Tanaka, Kano & Yano (2025, JGR Solid Earth, doi 10.1029/2024JB029499) [`single-study`] reach about
75% accuracy on real GEONET data for 1.5–2.0 mm signals and identify **temporally correlated noise
as the dominant false-positive source**; Mastella et al. (2025, GJI 242(3)) [`single-study`] show a
learned single-station denoiser outperforming common-mode filtering. GNSS-FM (Teutschmann et al.
2026, arXiv:2606.07725) [`single-study`, `preprint`] is the first geodetic foundation model — 359
million parameters, 17,652 NGL stations, 73.4 million station-days — reporting 90-day forecast RMSE
**6.78 mm against 58.77 mm** for a supervised PatchTST baseline. *Caveat*: the survey reports its
seismic-step localisation F1 inconsistently in two places (0.515 vs 0.175 in one, 0.429 vs 0.035 in
another); treat that specific figure as unverified until the paper is read directly. No weights have
been released.

**Prospective record.** None for any geodetic precursor.

**Open code and data.** Bletery & Nocquet reproduction package (Zenodo 8064086, CC-BY-4.0 — but
DataCite also lists an "Embargoed Access" flag, so confirm the files download before scheduling
work); `kyleedwardbradley/BN24` (CC0-1.0) and `precursordenoise` (MIT); NGL GNSS series (open, daily,
5-minute rapid); EarthScope GNSS as an independent second processing.

**Status.** `contested`, leaning `rebutted` for the two-hour stack; `replicated` for weeks-scale
slow slip before some events; `single-study` for every machine-learning transient detector.

---

### 3.8 Slow slip as a target in its own right

**The claim.** Slow slip events — aseismic ruptures lasting days to weeks, releasing moment
equivalent to a Mw 6–7 earthquake without radiating destructive waves — recur often enough to be
forecast, and forecasting them is a genuine test of fault-state estimation on a real fault.

**Strongest support.** Hulbert et al. (2020, Nature Communications 11:4139) [`single-study`]:
gradient boosting on daily interquantile-range features of 8–13 Hz continuous borehole seismic
energy (Cascadia, 2005–2018) estimates time-to-next-slow-slip-event at Pearson correlation about
0.56 on the held-out second half, with seismic power rising exponentially roughly 100 days before
events. Two things about it matter more than the correlation. First, the authors report that the
2018 event was **not** predicted before onset and that the test is retrospective on a 50/50 split.
Second — and this is the architectural point — **a model trained on catalogued tremor alone cannot
do this**: the predictive energy build-up lies below the tremor-catalogue detection threshold and
appears only in continuous-signal features.

Earlier in the same line, Rouet-Leduc et al. (2019, Nature Geoscience 12:75–79) [`single-study`]
showed a random forest on 40 Hz continuous data estimating GPS-derived plate displacement rate on
Vancouver Island at correlation above 0.6 for 60-day windows — a *nowcast* of the present state, not
a forecast.

**Strongest constraint.** Gualandi et al. (2020, Science Advances 6:eaaz5548,
doi 10.1126/sciadv.aaz5548) [`established`] show Cascadia slow slip is a low-dimensional (fewer than
5 degrees of freedom) chaotic system with a **predictability horizon of days to weeks**, by segment
2–65 days; beyond it "deterministic prediction seems intrinsically impossible". Any lead-time claim
should be published alongside an embedding-estimated horizon bound, and a claim exceeding it should
be rejected. Keane, Veveakis & Poulet (2026, arXiv:2608.30861) [`single-study`, `preprint`,
`unverified`] claim physics-based filtering extends the Hikurangi horizon to 37.9 ± 4.3 days against
14.0; it was four days old at survey, is unreviewed, its repository carries no licence, and it must
not be load-bearing for anything.

**And the base-rate problem.** Dascher-Cousineau & Bürgmann (2024, Science Advances,
doi 10.1126/sciadv.ado2191) [`single-study`] examined three decades of circum-Pacific slow slip and
found earthquake rates rise **only up to about 3×** during slow-slip events and relax quickly. Most
slow-slip events are followed by nothing, so "a slow-slip event occurred" is an alarm with a
crippling false-alarm rate. The tractable question is not whether an event occurred but whether it
loaded a locked asperity.

**Prospective record.** None — but this is the one line where a prospective test is now
*possible*, because independent ground truth arrived after the original result. Gualandi (2025, GJI
242(2)) [`single-study`] publishes a daily-updated Cascadia slip inversion from about 232 stations
with roughly two-day latency, explicitly positioned as a base for prospective forecasting, and
Costantino's detectors supply independent event catalogues. A forecaster can now be scored against
labels it did not construct.

**Open code and data.** EarthScope borehole seismic and GNSS archives; PNSN tremor logs; the
near-real-time Cascadia slip stream (open web directory, licence not stated);
`Geolandi/labquakesde` for predictability-horizon estimation (no licence, dormant since 2023).

**Status.** `single-study` throughout, with a clear and cheap prospective test available. This is the
strongest surviving transfer path from the laboratory literature to a real fault.

---

### 3.9 Laboratory earthquakes and the fault-state signal

**The claim.** In a controlled shear experiment, machine learning on the continuous acoustic
emission signal predicts the timing of the next slip event, and reads the fault's frictional state
throughout the cycle.

**Strongest support.** This is the one machine-learning result in the field that replicated.
Rouet-Leduc et al. (2017, GRL 44, arXiv:1702.05774) [`replicated`] trained a random forest on about
100 windowed statistics of the continuous acoustic signal from a double-direct-shear gouge fault and
predicted time-to-failure at **R² = 0.89** against a periodicity baseline of 0.3, using only the
instantaneous window and throughout the whole cycle — independently reproduced by van Klaveren et
al. (2020, arXiv:2011.06669) on glass beads and salt gouge. The follow-up (Rouet-Leduc et al. 2018,
GRL 45:1321–1329) [`established`] established what the model is reading: signal power maps to
friction, giving an "equation of state". The signal is not a precursor; it is a continuous
observation of state.

Scaling up: Norisugi, Kaneko & Rouet-Leduc (2025, Nature Communications,
doi 10.1038/s41467-025-64542-4) [`single-study`] ran the same idea on a 1.5 m × 0.1 m metagabbro
fault with 64 acoustic sensors at 10 MHz, 34 events split 19 train / 4 validation / 11 test, and
obtained time-to-failure **R²(log) = 0.84** and shear-stress R² = 0.81 against an inter-event
baseline of **R² = −0.28** — from *catalogue-network* features, which is what makes it
field-compatible. A paired rate-and-state simulation identifies the predicted latent as **shear
stress on velocity-strengthening creeping patches**, not nominal fault stress. That is a target
variable that exists in nature.

**Strongest rebuttal — of the transfer, not the result.** Two hard limits.

Borate et al. (2023, Nature Communications 14:3693) [`single-study`] state it plainly: the model
"cannot be directly applied to field data", because the lab's labels — shear stress and slip rate on
the fault — do not exist at seismogenic depth, continuous active-source monitoring over geological
time is unavailable, and lab shear rates (about 5–9 µm/s) are orders of magnitude above tectonic
loading.

Johnson, Wang & Johnson (2025, Nature Communications, doi 10.1038/s41467-025-55994-9)
[`negative-result`] is the decisive field test and it is negative in the most informative way: a
wav2vec-2.0 model pretrained on continuous waveforms from the 2018 Kīlauea caldera collapse
sequence nowcasts contemporaneous surface displacement at **R² = 0.63** (beating gradient-boosted
trees at 0.59), but reconfigured to predict 30 seconds or more ahead it identified slip onset for
only **3 of 20** test events. The authors' own conclusion is that the model "fails to extract
information that describes the short term future behavior". Continuous waveforms carry present
state; on that fault they did not carry future state.

And Goebel et al. (2024, doi 10.1038/s41467-024-49959-7) [`single-study`] with Laurenti et al.
(2022, EPSL 598:117825) [`single-study`] bound where transfer could work at all: high fluid pressure
and low roughness homogenise stress and compress the precursory period, so extended foreshock
activity is expected mainly on immature, shallow faults, and continuous-signal predictability drops
when preseismic creep is small.

**Prospective record.** Not applicable in the lab. The Kaggle LANL competition (Johnson et al. 2021,
PNAS 118(5):e2011362118) [`replicated`] is the closest thing to a blind test and it is a cautionary
one: 4,521 teams, 59,890 entries, and the winner's mean absolute error went from **1.080 s on the
public leaderboard to 2.265 s on the private set**, with 31st place going from 1.509 to 2.425. The
experiment drifted; feature distributions shifted between train and test; gradient-boosted trees
overfitted less than deep networks; predicting *cycle fraction* rather than seconds-to-failure was
what survived.

**Open code and data.** The Marone lab public bucket (tens to hundreds of GB per experiment, no
licence statement found); the Kaggle LANL dataset; `lauralaurenti/DNN-earthquake-prediction-
forecasting` (no licence, dormant since 2022); the Norisugi Zenodo record (CC-BY-4.0 — note the
*paper* is CC BY-NC-ND 4.0, which is more restrictive than open-access readers usually assume).

**Status.** `replicated` in the laboratory; `rebutted` for direct transfer to a locked natural
fault; `single-study` for the creeping-fault transfer path, which is the one worth pursuing (§ 3.8).

---

### 3.10 Non-seismic precursors: electromagnetic, ionospheric, chemical, biological

**The claim.** Physical processes in the fault zone before rupture produce measurable signals in
other channels — magnetic fields, ionospheric electron content, radon, groundwater chemistry, thermal
infrared, animal behaviour.

**The state of the record.** This is the most thoroughly closed area in the document, and the
closure is specific rather than dismissive.

The unifying measurement is Nakatani (2020, Journal of Disaster Research 15(2):112,
doi 10.20965/jdr.2020.p0112) [`established`], who put every candidate phenomenon on the same scale:
**every phenomenon not attributable to earthquake triggering has probability gain G < 20, mostly
about 2, with p near 0.05**, while foreshock/aftershock clustering alone gives G > 100 and up to
10^4. That is the effect size any experiment in this area must be powered to detect, and it is small.

Line by line:

- **ULF magnetic.** The Corralitos anomaly before Loma Prieta 1989 was traced to sensor-system
  malfunction (Thomas, Love & Johnston 2009, PEPI) [`established`], reaffirmed after comments in
  2012. Later polarisation-ratio claims track the geomagnetic Kp index inversely (Masci & Thomas
  2015, JGR Space Physics) [`established`]. **Warden et al. (2020, JGR Space Physics,
  doi 10.1029/2020JA027955) is a `negative-result` and must be cited as one**: it reimplemented the
  superposed-epoch method, approximately reproduced 6–15-day anomalies at Kakioka for 2001–2010,
  then found the result inconsistent under alternative outlier rejection and catalogue choices, found
  **no significant precursory activity when extended to 2013–2018**, and explicitly urged caution
  for future electromagnetic precursor research. It was tagged as a positive replication in the
  source survey; as tagged it would have justified funding magnetometer work on the strength of a
  null. Wang et al. (2022, GJI 229(3):2081) [`negative-result`] similarly found the Alum Rock
  magnetic-pulse claim absent at a 42 km reference station and peaking during human activity hours.
- **Ionospheric TEC.** Heki (2011, GRL) [`contested`] reported a ~40-minute pre-Tohoku enhancement;
  Kamogawa & Kakinami (2013) attribute it to a reference curve fitted through the post-seismic
  ionospheric hole, and Ikuta et al. (2020, JGR Space Physics, doi 10.1029/2020JA027899)
  [`negative-result`] show comparable enhancements occur far more often at random than reported.
  Globally, Cullen et al. (2024, arXiv:2401.01773) [`negative-result`] find **no significant,
  consistent worldwide pre-earthquake ionospheric anomaly**; only weak regional signals survive.
  (This paper was also tagged `replicated` in the source survey, inverting its finding.)
- **VAN / seismic electric signals.** The 1996 GRL special section [`rebutted`] found the
  predictions too ambiguous to score, no better than a Poisson null once aftershocks are removed,
  with about half of large events missed and recognition criteria not independently reproducible.
  The ICEF (Jordan et al. 2011, Annals of Geophysics 54(4)) [`established`] concluded the claimed
  capability could not be validated.
- **Accelerating moment release.** Hardebeck, Felzer & Michael (2008, JGR 113:B08310,
  doi 10.1029/2007JB005410) [`established`] showed the apparent power-law acceleration is a fitting
  artefact: with the freedom to choose time window, area and magnitude range after the fact, it is
  statistically insignificant, and it is reproducible in synthetic catalogues with no such effect.
- **Thermal infrared.** Blackett, Wooster & Malamud (2011, GRL 38:L15303) [`established`] show the
  reported Gujarat 2001 anomalies lie within normal variation and that detected anomalies are
  positive biases from cloud cover and orbit-mosaic data gaps.
- **Radon.** Woith (2015, Eur. Phys. J. ST 224:611) [`established`]: anomaly counts scale inversely
  with record length, only 19% of published series exceed five years, and about half report exactly
  one anomaly.
- **Animal behaviour.** Woith et al. (2018, BSSA 108(3A)) [`established`]: 729 reports across 160
  earthquakes yield only 14 time series, the longest one year, and anomaly timing matches foreshock
  timing. The authors of the single-farm Norcia study conceded in reply (Wikelski et al. 2021) that
  no predictions are possible from the dataset.
- **Groundwater chemistry** is the one line with a stated forward test: Skelton et al. (2024,
  Communications Earth & Environment) [`single-study`] report that on 2014–2023 data, **one of three
  M > 5 events could have been forecast** — with no stated false-alarm rate. That is honest and it is
  also not yet evidence.
- **Methodology worth copying.** Chaniadakis et al. (2025, Applied Sciences 15(24):13218)
  [`single-study`] is the template regardless of one's view of ionospheric precursors: 38 years of
  ionosonde data from more than 100 stations, strict temporal partitioning with a held-out 2022–2025
  period, no overlapping windows, spatial and temporal identifiers removed, and the resulting best
  weighted F1 of 0.71 presented explicitly **as an upper bound** with sensitivity to validation
  configuration reported.

**Prospective record.** None, anywhere in this section.

**Status.** `rebutted` for every specific mechanism with a published test. The correct posture for
an open project is not to generate claims here but to **score submitted alarm functions** from these
communities against a clustering-aware reference — which is a service the field has no home for, and
which pyCSEP cannot currently provide because it has no alarm-forecast class (§ 3.14).

---

### 3.11 Physics-based simulation and fault-state estimation

**The claim.** Simulating earthquake cycles from rate-and-state friction — either to generate
training data, or to estimate the current state of a real fault by data assimilation — puts physics
where statistics currently is.

**Strongest support.** The assimilation branch is the interesting one. Kaveh, Avouac & Stuart
(2025, GJI 240(2):870–885, ggaf518) [`single-study`] built a 40-mode reduced-order model (proper
orthogonal decomposition plus a neural network) that is **338× faster than the QDYN simulator** and
coupled it to an ensemble Kalman filter, forecasting large synthetic slow-slip events at 75% true
positive rate with a reliable horizon of about 0.4 years. Kano et al. (2024) [`single-study`] showed
Markov-chain Monte Carlo assimilation on **86 real GEONET stations** is feasible for the 2010 Bungo
Channel slow-slip event, though the posteriors were implausibly tight, indicating an over-constrained
model. Earlier perfect-model tests (van Dinther et al. 2019; Diab-Montero et al. 2023)
[`single-study`] caught about 90% of events at 10% alarm time.

The missing link is a proper geodetic observation operator — the map from fault slip to what a GNSS
station actually measures — instead of smoothed synthetic slip rate. Differentiable Okada
implementations now exist (`OkadaTorch`), though that repository carries **no licence**, and the
Okada formulation itself is public and reimplementable.

**Strongest rebuttal.** Three constraints, all specific.

- **Physics does not currently beat statistics for short-term forecasting.** Coulomb rate-and-state
  models match but do not outperform ETAS (Hardebeck 2021; Cattania et al. 2018) [`replicated`],
  because unmodelled spatial clustering of direct aftershocks from background heterogeneity gives
  ETAS the edge.
- **Simulator output is not ground truth.** Vazquez & Jordan (2025, GJI, doi 10.1093/gji/ggaf101)
  [`single-study`] found RSQSim rates disagree with the UCERF3 consensus at about 25% of fault
  subsections and give 60% higher M ≥ 6.7 rates; the simulator encodes strong uncalibrated modelling
  choices. Training a forecaster on a single canonical run trains it on those choices.
- **Physics-informed neural networks are not drop-in solvers.** They recover friction parameters
  well but displacement accuracy lags without extensive extra training, and 3-D crustal-deformation
  variants struggle with rigid-body motions and semi-infinite boundaries (Rucker & Erickson 2024,
  CMAME, arXiv:2312.09403; Okazaki et al. 2025, arXiv:2507.02272) [`single-study`].

**Prospective record.** None. UCERF3-ETAS has a decade of archived next-day forecasts in the CSEP
California benchmark, which is the nearest thing.

**Open code and data.** SeisSol (BSD-3-Clause), Tandem (BSD-3-Clause), SPECFEM3D (GPL-3.0), QDYN
(GPLv3 asserted in a README badge only — no LICENSE file, so the grant is asserted rather than
conveyed), RSQSim catalogues on Zenodo (CC-BY-4.0, 715 GB), SEAS community benchmarks BP1–BP6 for
verification.

**Status.** `single-study` for fault-state assimilation on real data, and it is the line whose target
variable — slip rate and stress on creeping patches — matches what the laboratory work identified
(§ 3.9). `rebutted` for physics beating statistics at short-term forecasting today.

---

### 3.12 Below-catalogue and multimodal learning: foundation models

**The claim.** Self-supervised pretraining on large volumes of continuous waveform, geodetic and
catalogue data produces representations that carry fault state, and those representations forecast.

**Strongest support.** The component backbones arrived in 2024–2026 and each does what it claims on
*perception* tasks: SeisLM (Liu et al. 2024, arXiv:2410.15765; **NeurIPS 2024 FM4Science workshop
poster**, not main track) [`single-study`], SeisMoLLM (Wang et al. 2025, arXiv:2502.19960 —
`preprint` only; the "GRL" attribution in circulation is unsupported by the arXiv record)
[`single-study`, `unverified`], PhaseNO for multi-station picking [`single-study`], and GNSS-FM for
geodesy (§ 3.7).

**Strongest rebuttal.** Four negative results bound the claim tightly.

- SeisLM's advantage over a supervised PhaseNet exists **only in the 5%-label regime**; at 100% of
  STEAD all models are near-perfect. The pretraining benefit is label efficiency, not a ceiling
  raise [`single-study`].
- Jafari et al. (2024, GeoHazards 5(4):59, arXiv:2408.11990) [`negative-result`]: generic time-series
  foundation models (TimeGPT, Chronos, PatchTST, iTransformer, TSMixer) pretrained on weather,
  traffic and M4 data **do not transfer** to earthquake catalogues; models trained directly on the
  catalogue score better (TimeGPT NNSE 0.5484 against 0.6175 for the best direct model), and the
  gains that exist come from graph structure rather than pretraining.
- Johnson, Wang & Johnson (2025) [`negative-result`] — the Kīlauea result in § 3.9: present state,
  not future state.
- Esmail et al. (2026, arXiv:2606.02912, arXiv:2606.10868) [`single-study`, `preprint`]: purely
  autoregressive next-sample waveform models work as continuation only *after* P and S arrivals, and
  generalisation collapses when the context ratio falls below the P–S interval. Nothing in that setup
  predicts an event before it starts.

Every existing seismic foundation model is **single-station and single-modality**, and every one is
evaluated on perception. No model has fused continuous waveform, geodetic and catalogue state and
been scored on forecast information gain. That is simultaneously the largest remaining hope and an
untested one.

**Prospective record.** None.

**Open code and data.** SeisBench (GPL-3.0) as the data and model plumbing; SeisMoLLM (MIT), SeisT
(MIT), SeisCLIP (MIT); **seisLM has no licence** — the CC-BY-4.0 in circulation is the arXiv
preprint's posting licence, which covers the paper and not the code or weights. Continuous archives
are on S3 (SCEDC ~105–150 TB, NCEDC ~184–190 TB, EarthScope >1 PB) but are not analysis-ready.

**Status.** `single-study` on perception, **untested** on forecasting. The decisive experiment is a
frozen-embedding linear probe across many mainshock sequences, trained only on earlier sequences and
scored against ETAS and Markov nulls, with an ablation removing the waveform and geodetic inputs.

---

### 3.13 New observational substrates

**The claim.** Distributed acoustic sensing (DAS — using a telecom fibre as thousands of strain
sensors), dense nodal arrays, smartphone accelerometers and L-band radar interferometry change what
can be observed, and therefore what can be predicted.

**Strongest support.** DAS is now operational, not experimental: a 100 km Ridgecrest array streams
into the SCSN/AQMS pipeline with machine-learning picking (Biondi et al. 2025, arXiv:2505.24077)
[`single-study`], and a Monterey Bay seafloor array produced more than 620,000 detections over
nearly four years (Zhang et al. 2026, arXiv:2603.14844) [`single-study`]. NISAR — the NASA-ISRO
L-band radar mission — began releasing calibrated provisional products on 20 July 2026, giving
12-day repeat coverage over vegetated faults where C-band interferometry fails. Android-phone
earthquake detection reaches roughly 312 detections per month in Türkiye and about 18 million alerts
per month across 98 countries (Allen et al. 2025, Science, doi 10.1126/science.ads4779)
[`single-study`].

**Strongest rebuttal.** Each substrate has a hard, quantified limit. DAS strain-rate saturates by
optical cycle-skipping during strong shaking (van den Ende et al. 2025, Seismica,
doi 10.26443/seismica.v4i1.1371) [`single-study`], so the events early warning most needs are the
ones DAS records worst — though Zhai et al. (2025) [`single-study`] show tunable pulse rate and
gauge length keep M 6+ P-waves unsaturated at 10 km. Cycle-skipped channels are **censored data, not
missing data**, and any model reading DAS must represent that distinction. Smartphone magnitude
estimation sized the 2023 M 7.8 Türkiye event at M 4.5–4.9, and Raspberry Shake self-noise means
events must be about 0.3 magnitude units larger than for a broadband station to be characterised
reliably (Anthony, Ringler & Wilson 2018, SRL) [`established`].

**Prospective record.** Not applicable; these are observation layers.

**Open code and data.** PubDAS (~90 TB, open per the paper), SCEDC Ridgecrest DAS, DASCore (LGPL),
xdas (GPL-3.0), DAS-N2N (GPL-3.0), NISAR products via ASF DAAC (open), Sentinel-1 (Copernicus free
and open), MintPy (GPLv3+), LiCSBAS (GPL-3.0). Raw smartphone waveforms from both Android and
Earthquake Network are **proprietary**.

**Status.** `established` as infrastructure, **untested** as a prediction substrate. **Do not fund
instrumentation**: borehole observatories, fibre-geodesy campaigns and cabled seafloor deployments
are capital projects requiring observatory partnerships. Ingesting other people's instrumentation and
making it more useful is what an open project can do.

---

### 3.14 The measurement layer: scoring, predictability budgets and data vintage

This is a research line, not plumbing, and it is the one with the largest gap between what exists
and what is needed.

**Adjudication as it stands.** CSEP is the working machine: forecasts registered in advance as rates
on a space-magnitude grid (or as simulated catalogues), evaluated only against future data, with
consistency tests (N, M, S, L, CL) and comparative paired-T and Wilcoxon tests on information gain
per earthquake. pyCSEP implements it; floatCSEP (JOSS 2026) runs entire containerised prospective
experiments from a YAML file and has a `reproduce` command; the CSEP Italy 2024 experiment is live
and accepting models. A Delphi elicitation of 20 experts found only one near-consensus requirement:
**79% consider comparison to a benchmark model important, and 74% agree a model is ready when tested
by a third party such as CSEP** [`single-study`].

**Three things the machine does not do.**

1. **It cannot score alarms.** pyCSEP has no alarm-forecast class, so a claim of the form "this
   region, this window, declare or do not" — which is the shape of most precursor claims — cannot be
   adjudicated by the standard toolchain at all. Molchan diagrams, area skill score and probability
   gain against a **clustering-aware** reference are the right instruments. The reference matters
   enormously: Zhang et al. (2024, doi 10.1029/2023JB028037) [`single-study`] showed an LSTM's
   apparent Molchan skill vanishes when the reference moves from uniform Poisson to spatially varying
   Poisson, and Luen & Stark showed a trivial "declare an alarm after every M 5.5" rule reaches
   p < 0.001 purely from clustering. Building an alarm-forecast class and upstreaming it to pyCSEP is
   a concrete, paper-sized contribution.
2. **It does not report test power.** Khawaja et al. (2023, GJI 233(3):2053) [`single-study`]: the
   S-test cannot reject a uniform global forecast on a 0.1° grid without roughly 32,000 events,
   against roughly 8 on a data-driven quadtree grid. A "pass" without its power is not information.
3. **It does not know what data existed when.** This is the deepest gap and it is discussed next.

**Latency is a distinct leakage class.** Timestamp honesty — train on `t < T`, test on `t > T` — is
necessary and *insufficient*, because the **values** at time `t` may not have existed at time `t`.
Three sub-classes, each with evidence:

- **Revision leakage.** Catalogue magnitudes and locations are revised; events are added and
  deleted. The Girona & Drymoni (2024, Nature Communications, doi 10.1038/s41467-024-51596-z)
  [`rebutted`] detection of abnormal low-magnitude seismicity before the 2018 Anchorage earthquake
  depends on USGS events **later deleted** and vanishes on the current catalogue; the Ridgecrest hit
  is driven by Coso volcanic-swarm events; the published model was the best of twenty configurations
  and fails on 15+ further M 6.2+ events. (The rebuttal is Bradley & Hubbard,
  doi 10.62481/e64960d4, which is a non-peer-reviewed blog analysis carrying a DOI — the status rests
  on criticism that has not been through review.)
- **Availability lag.** NGL final daily GNSS solutions lag about two weeks, against 24-hour rapid and
  5-minute rapid products; the Gualandi Cascadia slip stream lags about two days; Sentinel-1 repeats
  every 6 days; NISAR every 12. A model reading the final product at issue time is reading the
  future.
- **Completeness-regime mismatch.** The real-time catalogue in the first hours after a mainshock is a
  different object from the archive — Hainzl et al. (2024) [`single-study`] quantify short-term
  aftershock incompleteness as roughly a 162-second blind time. Models validated on archival
  catalogues are validated in a data regime that will never exist operationally.

The field acknowledges this obliquely and then proceeds anyway: Rhoades et al. (2018)
[`single-study`] state that the New Zealand CSEP testing centre did not consistently capture the
real-time catalogue, so most results are reprocessed; Mizrahi et al. (2024, Reviews of Geophysics,
doi 10.1029/2023RG000823) [`established`] note that catalogue-based tests have not yet been used in
truly prospective experiments. **No vintaged data store exists.** Nobody can currently answer the
question "what would this model have scored on the data that was actually available?" — which means
nobody knows how much published short-term skill is latency leakage.

**The predictability budget.** Zhuang & Sornette (2026, arXiv:2607.26918) [`single-study`,
`preprint`] define predictability as the entropy gap between a Poisson process and the true
generating process, decomposable into time, space and magnitude components, with auxiliary
observations contributing exactly their mutual information — plus an over-performance diagnostic: a
model scoring better on real data than on its own synthetics has not reached the data's ceiling. It
was about five weeks old and unreviewed at the time of survey; the *framework* is adoptable, the
specific claims are untested, and nobody has computed the numbers for any region. Kagan & Knopoff
(1987) [`established`] made the first quantitative version of the same statement — clustering reduces
rate uncertainty by more than a factor of 1000.

**Status.** This layer is where the largest genuinely open gaps are, and it is the part of the
programme an open repository is best placed to build.

---

## 4. Closed doors

**Read this section before proposing a direction.** Each entry names what was tried, why it failed
with numbers, and what would have to change to reopen it. "Reopens if" is not a courtesy; several
of these doors are genuinely ajar and the conditions are what distinguish a contribution from a
repetition.

### 4.1 Protocol failures — these invalidate a result regardless of the model

| Closed door | Why it failed | Reopens if |
|---|---|---|
| **Random (non-chronological) train/test splits on catalogues** | Aftershock clustering leaks future information into training. A published 97.97%-accuracy random forest fell to 21–24% under walk-forward validation against a 27.69% majority-class baseline, and to 16% transferred to another city (Jover-Alfaro et al. 2026, Earth Science Informatics, doi 10.1007/s12145-026-02078-x) [`negative-result`]. The prior neural-point-process benchmark had alternating-split leakage and had deleted Tohoku. | Never for evaluation. Time-forward, region-held-out or fully prospective protocols only. |
| **Accuracy, F1 or AUC on grid cells** | Targets are heavy-tailed and grossly imbalanced; AUC 0.85 concealed precision of 5.4% in the DeVries case (§ 5). | Never as a headline metric. Use information gain per event, CSEP consistency tests, Molchan and area skill. |
| **RMSE / MAE on next-event time or magnitude** | Inter-event times and magnitudes are power-law distributed; squared and absolute errors assume Gaussian or Laplacian noise (EarthquakeNPP § 4.1) [`negative-result`]. | Never. Use log-likelihood. |
| **Validating on final, revised data and calling it out-of-sample** | Revision leakage, availability lag, completeness-regime mismatch (§ 3.14). The Anchorage detection vanished on the current catalogue. | Only with as-of reads: every observation typed with both `valid_time` and `available_time`, and evaluation refusing any value whose availability postdates issue time. |
| **Post-hoc optimisation of window, region and magnitude range** | This is exactly what produced accelerating moment release as an apparent signal; with those degrees of freedom accounted for it is statistically insignificant and reproducible in synthetics (Hardebeck et al. 2008) [`established`]. | Only with the windows fully pre-registered before the test data is touched. |
| **Best-of-N model selection reported as one model** | The Girona & Drymoni model was the best of twenty configurations and failed on 15+ subsequent qualifying events [`rebutted`]. | Report the selection procedure and score the selection, not the survivor. |
| **Kaggle-style one-off competitions with a static hidden test set** | LANL 2019: the test-set statistics had already been published and were exploited; the public-to-private collapse was severe (1.080 → 2.265 s MAE); lab data did not transfer to field seismicity and no lasting benchmark asset survived [`replicated`]. | Only as truly prospective challenges where forecasts are registered before the evaluation window exists. |
| **Treating labelled waveform benchmarks as clean ground truth** | 3.9% average label error across 8.6 million examples, up to 8% per dataset (Aguilar Suarez & Beroza 2025) [`single-study`]. | Versioned corpora shipping error lists, re-audited each release. |

### 4.2 Model-class failures

| Closed door | Why it failed | Reopens if |
|---|---|---|
| **Deep networks on engineered static-stress features** (the DeVries 2018 paradigm) | Matched by a two-parameter logistic regression (AUC 0.85 vs 0.849) and beaten by distance-plus-slip (0.86); leakage between collocated ruptures; precision 5.4%. Separately, the Coulomb baseline it beat is itself outperformed by maximum shear and von Mises across 289 slip models. | Measured rather than modelled inputs, sequence-grouped chronological splits, and gain over both the logistic and ETAS/Omori-distance baselines on held-out sequences. Ship the one-neuron baseline as a mandatory comparator. |
| **Off-the-shelf spatio-temporal neural point processes** (NSTPP, DeepSTPP, AutoSTPP, DSTPP, SMASH) | None beat ETAS on any of seven California datasets; generative variants failed CSEP badly (DSTPP 0% N-test on two datasets); they collapse during large sequences for want of magnitude marks and long memory [`negative-result`]. | Partially reopening via magnitude-marked, ETAS-prior hybrids — but only parity claims so far, retrospective, and no CSEP generative tests. |
| **Neural magnitude prediction beyond Gutenberg–Richter** | ETAS with Gutenberg–Richter beat the neural magnitude model (Stockman 2023); Fusion (2026) finds no consistent gain across five catalogues. MAGNET's ~0.07 bits/event (Berman et al., arXiv:2408.02129) is unreplicated and operationally negligible even if real. | An independent replication of the 0.07 bits on EarthquakeNPP catalogues against a time-varying-b Gutenberg–Richter null. Cheap to settle either way. |
| **Reading final magnitude from rupture onsets** | Large and small earthquakes have identical onsets (Meier, Ampuero & Heaton 2017, Science 357:1277; Ide 2019, Nature 573:112, ~100,000 co-located events) [`established`]. Final size is set by what the rupture encounters. | Only in specific regimes and for early warning, not prediction. The existence of a nucleation phase remains `contested`; the magnitude-predictive interpretation does not. |
| **Purely neural next-large-event forecasting on small-N regional data** | With about 440 M ≥ 6.5 Japanese events, models beat a Markov baseline on validation (best Brier skill +0.024 after 307,200 trials) and scored **−0.053 on the final held-out quintile** (Koehler et al., arXiv:2509.14661) [`negative-result`]. | Orders of magnitude more large events via global pooling, or physics priors — and a mandatory final-period holdout. |
| **Generic time-series foundation models on catalogues** | No transfer from weather/traffic/M4 pretraining; direct-trained models win; gains came from graph structure (Jafari et al. 2024) [`negative-result`]. | Only with a model pretrained on seismicity-like point-process data at scale. |
| **Autoregressive next-sample waveform models as a route to prediction** | Rollout works only as continuation after P and S have arrived; generalisation collapses below a context ratio of one P–S interval [`single-study`]. | Reframe from waveform continuation to state-variable forecasting; no evidence yet of precursory skill. |
| **Building another picker, associator or benchmark** | The detection layer is won and permissively licensed; scaling model size is explicitly inefficient (+15.6% precision for −87% throughput). EarthquakeNPP, pyCSEP, floatCSEP, SeisBench and the CSEP California archive already exist. | Extending them is a contribution; forking them buys isolation. The frozen `seisbench/pick-benchmark` (last pushed 2023, three years behind SeisBench) is worth reviving. |

### 4.3 Precursor failures

| Closed door | Why it failed | Reopens if |
|---|---|---|
| **Corralitos ULF and single-sensor ULF generally** | Sensor-system malfunction; later polarisation-ratio claims track Kp inversely; the one line with an original G ≈ 2 result failed out-of-sample for 2013–2018 (Warden et al. 2020, a `negative-result`). | Multi-station arrays with reference stations, geomagnetic-index regression, superposed-epoch design validated out of sample. |
| **VAN / seismic electric signals** | Predictions too ambiguous to score; no better than Poisson after declustering; about half of large events missed; recognition criteria not independently reproducible [`rebutted`]. | Only via pre-registered prospective alarms with published alarm maps and Molchan scoring. |
| **Accelerating moment release / time-to-failure fits** | A fitting artefact; reproducible in synthetic catalogues with no acceleration [`established`]. | Physically constrained, pre-specified region and window, tested prospectively against ETAS synthetics. |
| **Satellite thermal-infrared anomalies** | Reported anomalies lie within normal variation; detections are biases from cloud and orbit-mosaic gaps [`established`]. | Gap-aware whole-record false-alarm accounting with shuffled-catalogue nulls. |
| **Immediate pre-earthquake TEC enhancement by reference-curve fitting** | The reference curve is biased by the post-seismic ionospheric hole; comparable enhancements occur frequently at random; no consistent global anomaly exists [`negative-result`]. | A prospective whole-series detector with a pre-specified reference model, reporting occurrence rate against earthquake-conditioned rate. |
| **Single-site radon; animal behaviour** | Anomaly counts scale inversely with record length; ~50% of radon series contain exactly one anomaly; 729 animal reports yield 14 time series and the authors of the best-known study conceded no predictions are possible [`established`]. | Multi-year, multi-site, pre-registered monitoring only. Low expected value. |
| **"72% of mainshocks have foreshocks" as a predictor** | Falls to 18–33% under an ETAS null, and to about 3 of 53 mainshock-specific; globally 3–4% show significant acceleration [`rebutted`]. | Not closed entirely: the residual non-cascading population is the target, and it needs catalogues complete to M−3 (Mignan 2014) with ETAS-conditioned nulls. |
| **The universal ~2-hour stacked GNSS precursor** | Vanishes under common-mode noise removal; far-field noise alone regenerates it; three events dominate; the filter preserves 80–95% of injected signal; an independent tiltmeter stack bounds Tohoku preslip below ~Mw 6.4 [`contested`, leaning `rebutted`]. | Independent GNSS processing, injection-recovery curves proving the denoiser preserves near-field slip, survival after excluding the three dominant events, and reproduction on the post-2023 events at pre-registered significance. |
| **Slow-slip events as earthquake precursors** | Rates rise only up to ~3× during slow slip and relax quickly; most slow-slip events are followed by nothing, so the false-alarm rate is crippling [`single-study`]. | Only if detectors can distinguish slip that loads a locked asperity from ordinary periodic slip, tested prospectively against a live stream. |
| **Retrospective "prediction" of the 2025 M 8.8 Kamchatka earthquake** | Every published analysis was submitted 4–11 months after the event; the quiescence result rests on few M 5+ events by its authors' own caveat; the cross-correlation work reports no significance test and no alarm. One paper's title begins "Prediction of" and is retrodiction [`single-study`]. | Only via prospective, registered alarms on other subduction segments using the same recipes. |

### 4.4 Programme-level closed doors

| Closed door | Why it failed | Reopens if |
|---|---|---|
| **The Parkfield paradigm** — dense multi-parameter monitoring on a "characteristic" segment | The 1985 prediction (95% by 1993) missed by 11 years; when the M 6.0 arrived on 28 September 2004 the densest network in the world recorded no obvious precursors (Bakun et al. 2005, Nature 437:969–974, doi 10.1038/nature04067) [`established`]. Savage (1993) showed the recurrence statistics were over-fitted. | Only with a qualitatively new observable demonstrated prospectively at multiple sites, not one. |
| **Statutory pre-slip-triggered warning (Japan's Tokai regime)** | Cabinet Office panels found no confirmed observation of pre-slip before any large earthquake and that high-confidence prediction from pre-slip is not feasible; the regime was replaced on 1 November 2017 by probabilistic Extraordinary Information [`established`]. | Would require prospective demonstration of quantified probability gain over multiple earthquake cycles — the panel's own bar. |
| **Haicheng 1975 as a reproducible template** | There was no official short-term prediction; success rode on an unusual felt foreshock sequence. Tangshan 1976, the same programme one year later, had no such signals and killed more than 240,000 [`established`]. | Foreshock-based probability gain is the salvageable core and is already the frontier of operational forecasting; the administrative framing is closed. |
| **Public broadcasting of untested predictions** | NEPEC states that broadcasting predictions before expert evaluation is strongly discouraged and that USGS will not consider methods not first tested and vetted; the L'Aquila convictions were about communication, not about failing to predict [`established`]. | Never as practice. The only accepted channel is closed-loop prospective testing with results published afterwards. |
| **Validating a large-event model on one region within a career** | NEPEC (2015): testing UCERF3-ETAS-class models on California's rare large events would likely take several hundred years; RELM's five-year rankings later proved unstable [`established`]. | Reopened in principle by global testing — which is precisely the opening an open project can occupy. |
| **Planning on non-redistributable data** | NIED prohibits redistribution of Hi-net/K-NET/KiK-net, so no openly licensed Japanese waveform corpus can legally exist; access terms for the Chinese national datasets are unverified for non-Chinese users; raw smartphone waveforms are proprietary [`established`]. | Treat Japan and China as code-only regions: ship code users run against their own downloads, or aggregate derived products. |
| **Funding instrumentation** | Borehole observatories, drilling, dense fibre-geodesy campaigns and cabled deployments are capital projects. SAFOD's durable output was fault-rock mechanics, not precursors [`established`]. | Ingest other people's products; do not try to acquire them. |

---

## 5. Worked example: how a strong result fails

**Why this episode and not another.** DeVries et al. (2018) is the most instructive story in the
field for exactly this project's audience, because nothing about it was fraudulent, sloppy in the
ordinary sense, or obviously wrong. It was a competent deep-learning paper on a real problem, in the
best venue, by capable people, and it was undone by a baseline nobody had bothered to fit. Every
failure mode in it is a failure mode a well-intentioned contributor to this repository could
reproduce next month.

**The result.** DeVries, Viégas, Wattenberg & Meade, *Deep learning of aftershock patterns following
large earthquakes*, Nature 560:632–634 (2018), doi 10.1038/s41586-018-0438-y. A six-hidden-layer
neural network with 13,451 parameters was trained on 12 engineered static-stress-change features
computed around mainshock ruptures from the SRCMOD database, over more than 131,000
mainshock–aftershock grid-cell pairs, and tested on more than 30,000. It forecast whether a cell
would contain an aftershock with **AUC 0.849, against 0.583 for the classical Coulomb failure stress
criterion**. The authors further reported that maximum shear stress change, the von Mises criterion
and the sum of absolute stress components explained more than 98% of the network's output — an
interpretability result offered as physical insight.

The reception was what you would expect: a deep network beating a textbook physical criterion on
aftershock location, in Nature.

**The rebuttal.** Mignan & Broccardo, *One neuron versus deep learning in aftershock prediction*,
Nature 574:E1–E3 (2019), doi 10.1038/s41586-019-1582-8 (preprint arXiv:1904.01983). They reproduced
the network (AUC 0.85, precision 5.4%), then fitted a **two-parameter logistic regression** on a
single scalar stress metric:

    Pr(y) = 1 / (1 + exp[−(b0 + b1 · log10 x)])

and obtained **AUC 0.85** — the same number, with 13,449 fewer parameters. They then fitted a
three-parameter logistic regression on log distance-to-rupture and log mean slip and obtained
**AUC 0.86** (b0 = 10.18, b1 = −2.32, b2 = 1.16), beating the network with two features that contain
no stress physics at all. They also noted that the same AUC had already appeared, with ROC curves, in
the same group's 2017 GRL paper.

The conclusion was not that deep learning is useless. It was that on this problem the network had
rediscovered a distance power law, and that no predictive or inferential content had been added over
what was already known.

**The independent corroboration.** Separately, Rajiv Shah and Lukas Innig
(`github.com/rajshah4/aftershocks_issues`) [`single-study`] documented **target leakage**: training
and test ruptures were nearly collocated in space and time and therefore shared aftershocks, with the
diagnostic symptom that **test AUC exceeded training AUC**. They further showed that 1,500 rows and
2 epochs reproduce the 4.7-million-row result — that is, the model was not learning from most of its
data. A Nature referee agreed leakage existed but judged it "somewhat rare" and declined to publish
the correspondence; Nature did not act.

**The reply.** Meade, Nature 574:E4–E5 (2019), doi 10.1038/s41586-019-1583-7 [`single-study`], did
not dispute the numbers. It argued the network had been a tool for removing human bias toward
Coulomb stress and for discovering interpretable metrics, and questioned whether slip and distance
are as useful as elastic stress calculations. This is the "interpretability, not prediction" retreat,
and it is worth naming because it is available to anyone: **a project must state before the
experiment whether a model is for prediction or for inference, and evaluate accordingly.**

**And the baseline it beat was itself weak.** Sharma, Hainzl, Zöller & Holschneider (2020, JGR Solid
Earth, doi 10.1029/2020JB019553) [`single-study`] showed across 289 SRCMOD slip models that classical
Coulomb failure stress on predefined receiver faults is outperformed by maximum shear and von Mises
metrics, with slip-inversion non-uniqueness and receiver-orientation uncertainty dominating. So the
0.583 the deep network beat was not the best physics available; it was the most familiar physics
available.

**The five independent failures.** Any one of them would have been enough.

1. **No fitted simple baseline.** The comparator was a physical criterion with no free parameters, not
   a fitted statistical model of comparable capacity. Two parameters were sufficient to erase the
   result.
2. **Leakage through the split.** Collocated ruptures share aftershocks; a random or
   spatially-naive split leaks the target. Test AUC above training AUC is the visible signature and
   it was visible.
3. **A metric that hides the failure.** AUC is insensitive to class imbalance. Precision was 5.4% at
   a 0.5 threshold — that is, roughly nineteen of every twenty positive calls were wrong — and AUC
   0.849 said nothing about it.
4. **Modelled inputs treated as measurements.** The 12 features are outputs of stress calculations
   from slip inversions with large, structured uncertainties. The network's ceiling was set by its
   inputs, which is why accuracy plateaus around AUC 0.85–0.86 for everything anybody has tried.
5. **No held-out sequence.** Generalisation was never demonstrated on ruptures the model's family had
   not seen.

**The status ledger for this episode**, applying § 1.1 honestly to a work that supports the position
this repository takes:

| Work | Status | Note |
|---|---|---|
| DeVries et al. 2018 | `rebutted` | never cited here without its rebuttal |
| Mignan & Broccardo 2019 | `contested`, independently corroborated | it is a single Matters Arising with a published Reply; the *core* point is corroborated by the Shah & Innig reanalysis, but the exchange is not closed, and calling the critique `replicated` while its target is `rebutted` would overstate how settled it is |
| Meade 2019 (Reply) | `single-study` | kept visible alongside the critique |
| Shah & Innig | `single-study` | independent, unpublished, repository abandoned in 2019 and unlicensed |
| Sharma et al. 2020 | `single-study` | shows the original baseline was weak on its own terms |

**What this repository takes from it.** Six rules, all of which are already in force here or are
named as gaps in § 7:

1. A mandatory trivial baseline per task, fitted on the same data, published with the result. For
   spatial aftershock models that baseline is the two-parameter logistic regression above.
2. Splits grouped by sequence, and chronological. Where a group of targets shares a cause, the group
   moves together.
3. Information gain per event with bootstrap confidence intervals as the headline number; precision
   and recall alongside; never AUC or accuracy alone.
4. A declared distinction between a prediction claim and an inference claim, made before the
   experiment.
5. Held-out sequences the model's family has never seen, not held-out rows.
6. The leakage diagnostic reported, not assumed: if test performance exceeds training performance,
   the split is broken until proven otherwise.

And one more, which is about people rather than method: **the correction did not come from the review
process.** It came from a Matters Arising eighteen months later and from an unpaid GitHub reanalysis
that a referee declined to publish. A project that wants results to be corrected quickly has to make
red-teaming a first-class contribution with equal credit, because the surrounding institutions do not
reliably do it.

---

## 6. Where this map disagrees with the pre-review architecture thesis

The architecture thesis written before this review argued that Rupture's catalogue-shaped spine —
`ForecastModel.fit(Catalog, Region, cutoff) -> ForecastGrid` — is a dead end for prediction, on three
grounds: input poverty, output poverty and time granularity. **The review supports the core argument
and contradicts it in four specific places.** The review wins; the disagreements are recorded here
rather than smoothed over.

**Supported, and more strongly than the thesis argued.** The signals with the strongest surviving
evidence all live below the catalogue: continuous acoustic energy (the only lab result that
replicated), the Cascadia slow-slip build-up (explicitly below tremor-catalogue threshold), GNSS
displacement, tremor rate, DAS strain. A catalogue-shaped port does not merely fail to support them;
it makes them inexpressible. The output-poverty argument is confirmed from an unexpected direction:
pyCSEP has no alarm-forecast class, so the gap the thesis identified in Rupture's architecture is
also a gap in the field's standard toolchain, and closing it is an upstreamable contribution rather
than a private convenience.

**Disagreement 1 — "dead end" is too strong; the harness is the asset.** The review's clearest
practical finding is that the evaluation machinery, not the modelling, is what an open project can
contribute and what buys credibility. The CSEP shape should become one output type among several,
not be discarded, and the existing leakage controls, catalogue infrastructure and provenance
machinery transfer unchanged. The re-architecture generalises the ports around a working scoring
engine; the phrase "dead end" invites throwing away the half that works.

**Disagreement 2 — "CSEP is rate-grid-only" is out of date.** CSEP accepts simulated-catalogue
forecasts and pyCSEP implements catalogue-based, non-Poissonian consistency tests; floatCSEP (JOSS,
February 2026) runs whole containerised prospective experiments from a YAML file with a `reproduce`
command, and the CSEP Italy 2024 experiment is live and open to submissions. The thesis's premise
that registration is a multi-institution negotiation is no longer true — it is roughly a day of
engineering. This changes the build-versus-join calculus decisively: **do not build a parallel
benchmark**; package models as floatCSEP containers and submit.

**Disagreement 3 — the evidential framing of two cited signals is too favourable.** The thesis cites
Rouet-Leduc et al. (2017–2019) and Bletery & Nocquet (2023) as "prediction signals with real
evidence behind them". The lab result is real and replicated but its Earth analogue works only where
a fault broadcasts a slip-modulated continuous signal; every attempt on a locked natural fault has
failed, most cleanly at Kīlauea (slip onset identified for 3 of 20 events). The stacked-GNSS result
is `contested` and leaning negative, with the peer-reviewed part of the record being a null with a
bound. **The port argument survives without them** — it rests on where the evidence lives, not on
those two claims being right — but it should not be made by citing them as established.

**Disagreement 4 — lead time has a measurable ceiling, and the thesis does not mention it.** The
thesis proposes continuous re-issuance to trace skill against lead time. Correct, and incomplete:
Cascadia slow slip is low-dimensional chaos with a predictability horizon of 2–65 days by segment.
Any lead-time claim should be published alongside an embedding-estimated horizon bound, and a claim
exceeding that bound should be rejected mechanically rather than argued about.

**One addition the thesis did not have.** Latency is the leakage class the thesis identified as
highest-value, and the review confirms it and supplies the missing evidence: a published Nature
Communications detection that depends on catalogue events later deleted, a testing centre that could
not capture its own real-time catalogue, and a 162-second post-mainshock blind time that makes the
archival catalogue a different object from the operational one. It also supplies the strongest
argument for building it: **nobody has one**, so the first replay table of (final-data skill minus
as-of skill) for published models would be new information about the field, not merely about Rupture.

---

## 7. What this repository has actually done, against this map

Stated so a newcomer can locate the code relative to the literature. `RELEASE_STATUS.md` is the
authority; this is the orientation.

- **The baseline is real and pinned.** `pyproject.toml` depends on `etas` at commit `097f08b6`
  from `lmizrahi/etas` (MIT) and on `pycsep==0.8.0`, with adapters at
  `src/rupture/adapters/forecasting/etas_mizrahi.py` and
  `src/rupture/adapters/evaluation/pycsep.py`. Rupture is scored on the field's own instruments, not
  on instruments of its own design.
- **The pseudo-prospective schedule ran and is published.** 55 windows per region at 30-day horizon
  over 2022-01-01 to 2026-08-01 for `nepal-himalaya` and `turkiye-eaf`; the spatial (S) test is the
  weakest in both, which is where a uniform-background ETAS is expected to lose. California's
  schedule stopped after 6 of 55 windows for a stated cost reason. Numbers in
  `docs/BASELINE_RESULTS.md`.
- **No challenger beat ETAS**, and that is the published result
  (`reports/CHALLENGER_EVALUATION.md`). The neural temporal point process scored **+0.394 nats per
  event on Türkiye but with 1 paired-T win in 10 windows and 0 Wilcoxon wins in 29**, and
  **−0.346 nats per event on Nepal**. A positive mean carried by one window in ten is a heavy tail,
  not a win. This is consistent with — and independently arrived at, on different regions from — the
  EarthquakeNPP finding in § 3.3.
- **The repository holds its own evidence for why leakage control is load-bearing.** The deliberate
  leaky ablations manufacture **+0.31 to +2.16 nats per event** of apparent skill; on Nepal a fit
  that crosses the cutoff turns a **−0.346 loss into a +0.429 apparent win** and lifts the spatial
  pass rate from 12/22 to 18/22. On Türkiye the same leak barely moves pass rates while nearly
  tripling information gain, so neither diagnostic catches it alone.

**Where this repository sits relative to the map.** Its evaluation discipline is ahead of most of the
machine-learning literature surveyed here and behind CSEP in exactly two respects: it is
pseudo-prospective rather than prospective, and it is not containerised for third-party
re-execution. Its ports are catalogue-shaped, which places every line in § 3.7 to § 3.13 outside what
the current architecture can express. And it has **no ETAS-I**, no completeness field, no alarm
scorer, no test-power reporting and no vintaged data store — five named gaps, each corresponding to a
line above.

---

## 8. Known gaps and open questions

Stated rather than smoothed over.

1. **Everything here is second-hand.** No paper cited in this document has been read in full by the
   author of this document; the source is a fourteen-dimension survey plus an adversarial audit that
   checked existence and metadata, not content. Verify before you build on any single number.
2. **The audit checked existence, not meaning.** It found no fabricated papers, no invented authors
   and no dead DOIs across roughly 230 entries — including every 2026-dated item, which is the usual
   failure surface. It found status inflation everywhere, and one sign inversion. Numbers quoted
   here inherit that: the citation is trustworthy, the *interpretation* deserves a second look.
3. **One quantity is internally inconsistent in the source material** and is flagged in place: the
   GNSS-FM seismic-step localisation F1 appears as 0.515 vs 0.175 in one section and 0.429 vs 0.035
   in another (§ 3.7). Do not use either until the paper is checked.
4. **Coverage stops at 2026-09-04**, and one dimension's web-search budget was exhausted before it
   could look for Transformer-Hawkes and LLM-based catalogue forecasters. Their absence from this map
   is not evidence that they do not exist.
5. **No non-English literature was surveyed.** The Chinese and Japanese prediction literatures are
   substantial and largely absent here; the AoyuX 25-year pseudo-prospective experiment at the China
   Seismic Experimental Site appears only through a preprint.
6. **Several load-bearing rebuttals are not peer-reviewed.** The Bletery & Nocquet critique and the
   Girona & Drymoni critique are blog analyses carrying DOIs. They are careful and their central
   computations were reproduced by the original authors in one case, but a reader should know the
   status rests on criticism outside the review process. The peer-reviewed corroboration for the
   geodetic case is Hirose et al. (2024); for the catalogue-vintage case there is none yet — *citation
   needed* for a formal comment on Girona & Drymoni, if one has since been published.
7. **Prevalence numbers for non-cascading foreshocks are unstable across studies** (33%, 19%, 3 of 53,
   3–4% globally) because they measure different things on different catalogues with different nulls.
   Anyone working this line should expect to spend real effort defining the quantity before measuring
   it.
8. **No independent replication of the strongest 2026 results exists**, by construction — they are
   months old. QuakeGen, Fusion, NMRP, GNSS-FM, Zhuang & Sornette and the Keane slow-slip claim are
   all `single-study` and several are unreviewed preprints. This document will be wrong about some of
   them within a year, and the correct response is to re-check rather than to have hedged everything
   into uselessness.
9. **Two access questions are unresolved and block plans if assumed:** whether the Bletery & Nocquet
   Zenodo record (8064086) is actually downloadable today given its "Embargoed Access" flag, and what
   the ISC Bulletin's licence terms are — ISC-GEM is CC BY-SA 3.0 but the Bulletin has no explicit
   licence found. Both should be resolved in writing before work depends on them.
10. **The claim that latency leakage is material is a hypothesis, not a finding.** It is
    well-motivated by the Anchorage case and the New Zealand testing-centre admission, but nobody has
    measured (final-data skill − as-of skill) for a set of published models. If that difference turns
    out to be within bootstrap noise everywhere, the whole as-of programme should be demoted to a
    data-engineering convenience.

---

## 9. Open-source assets

Every asset below is drawn from the audited list. **Licences in circulation are frequently wrong**,
and the corrections found by the audit have been applied here — read § 9.7 before depending on any of
them. Maturity reflects the state at survey (2026-09-04) and should be re-checked.

### 9.1 Evaluation, baselines and benchmarks

| Asset | Kind | Licence | Scale | Maturity |
|---|---|---|---|---|
| [pyCSEP](https://github.com/cseptesting/pycsep) | library | BSD-3-Clause | v0.8.0; 66 stars, ~740 commits | mature, community standard; **repository moved from `SCECcode/pycsep`** |
| [floatCSEP](https://github.com/cseptesting/floatcsep) | experiment runner | BSD-3-Clause | v0.5.1; ~475 commits; JOSS 2026 | young but official for new CSEP experiments |
| [EarthquakeNPP](https://github.com/ss15859/EarthquakeNPP) | benchmark + datasets | MIT | 7 California catalogues 1971–2021, Mc 0.6–3.0, 12k–128k training events | published (TMLR 2026), single group, active; no model-plugin interface |
| [lmizrahi/etas](https://github.com/lmizrahi/etas) | ETAS + ETAS-I implementation | MIT | 102 stars, 33 forks, 351 commits | mature research code; the reference ETAS in EarthquakeNPP and QuakeGen |
| [opensha-oaf](https://github.com/opensha/opensha-oaf) | operational forecast code | CC0-1.0 | 659 commits; operational since Aug 2018 | production at USGS |
| [CSEP California next-day benchmark](https://zenodo.org/records/15076187) | forecast archive | CC BY 4.0 | 56.4 GB; 25 models; >50,000 daily forecasts; 571 M ≥ 3.95 targets, 2007–2018 | published (Scientific Data 12:1501) |
| [CSEP Italy 2024 experiment](https://cseptesting.org/italy2024experiment/) | live experiment | per-model licences | open call since March 2024 | live; accepts simulated-catalogue forecasts |
| [RELM forecast archive](https://doi.org/10.5281/zenodo.5080947) | forecast archive | not checked | 17 forecasts, 2006–2010 | archival |
| [Global quadtree testing data](https://zenodo.org/records/6305669) | experiment data | not checked | global M ≥ 5.95 | published |
| [EPBench](https://github.com/zhiyuxu03/EPBench) | benchmark | MIT (code) | 924,472 catalogue records 1970–2021; 2,959 multimodal; 7 stars | early; **split and label definitions unstated — audit its leakage before trusting numbers**; repository renamed from `CoderZY-X/EPBench` |
| [ctf4science](https://github.com/CTF-for-Science/ctf4science) | benchmark platform | MIT | 47 stars; hidden test sets, independent referee scoring | early; wavefield tasks, not catalogues |
| [WeatherBench 2](https://github.com/google-research/weatherbench2) | benchmark (other field) | Apache-2.0 | 633 stars; ERA5 baselines | mature; architectural template only |

### 9.2 Catalogues, pick databases and event data

| Asset | Kind | Licence | Scale | Maturity |
|---|---|---|---|---|
| [USGS ComCat](https://earthquake.usgs.gov/data/comcat/) | catalogue service | US public domain | global, real-time, millions of events | operational |
| [QuakeScope pick database](https://dasway.ess.washington.edu/quakescope) | dataset + service | **data CC0-1.0, code MIT** (not CC-BY) | 4.3 billion picks (2.8B P, 1.5B S), 47,354 stations, 2002–2025; dumps 12 MiB–601 GiB | new (2025), single release; association step explicitly left open, ~25% association-rate estimate by the authors |
| [QTM catalogue (SCEDC)](https://scedc.caltech.edu/data/qtm-catalog.html) | catalogue | public, citation required | 1.81M events (and ~900k high-confidence), 2008–2017 | static research product |
| [ISC-GEM](https://www.isc.ac.uk/iscgem/) | catalogue | **CC BY-SA 3.0**, form-gated | ~74,100 events, Mw ≥ 5.0/5.5, 1904–2021; v12 Aug 2025 | mature; ShareAlike propagates to derivatives, download is manual |
| ISC Bulletin | catalogue | **no explicit licence found** | global phases since 1900, ~24 months behind | mature; terms unresolved |
| [Global CMT](https://www.globalcmt.org/) | catalogue | no formal licence; citation requested | >25,000 moment tensors, M > 5, 1976– | mature |
| [GeoNet open data](https://registry.opendata.aws/geonet/) | waveforms + GNSS | CC BY 3.0 NZ | full NZ archive, daily sync | production |
| [SCEDC on AWS](https://scedc.caltech.edu/data/cloud.html) | waveform archive | AWS Open Data; SCEDC terms | ~105–150 TB; ~600 stations, 1999– | production; not cloud-optimised |
| [NCEDC on AWS](https://ncedc.org/aws-public-dataset.html) | waveform archive | AWS Open Data; attribution requested | >184 TB; 29 networks, 2,640 stations | production |
| [EarthScope sponsored open data](https://docs.earthscope.org/sponsored-open-data) | waveform archive | CC BY 4.0 by default | archive 1.3 PB; ~2-day latency on the S3 subset | production; cloud migration ongoing |
| NIED Hi-net / K-NET / KiK-net / S-net | waveform archive | **redistribution prohibited** | densest national network | operational; **legally unusable as a redistributable corpus** |
| CSNCD / DiTing (China) | labelled dataset | **access terms unverified** for non-Chinese users | CSNCD 1.3M events, 45M annotations, 1.6 TB; DiTing 2.73M traces | released 2023; treat as unavailable until confirmed |

### 9.3 Machine-learning toolboxes and labelled waveform corpora

| Asset | Kind | Licence | Scale | Maturity |
|---|---|---|---|---|
| [SeisBench](https://github.com/seisbench/seisbench) | toolbox + dataset API | GPL-3.0 (datasets carry their own) | ~24–30 datasets, 20 waveform models; 414 stars, 1,133 commits | mature, institutionally funded |
| [seisbench/pick-benchmark](https://github.com/seisbench/pick-benchmark) | benchmark harness | GPL-3.0 | 6 models × 8 datasets | **frozen since Sept 2023**; three years of SeisBench drift, budget for porting |
| [PhaseNet](https://github.com/AI4EPS/PhaseNet) | picker | MIT | 383 stars | production |
| [EQTransformer](https://github.com/smousavi05/EQTransformer) | picker | MIT | 416 stars | production, lightly maintained |
| [PhaseNO](https://github.com/sun-hongyu/PhaseNO) | multi-station picker | MIT | 43 stars; trained on NCEDC 1984–2019 | research-grade |
| [GaMMA](https://github.com/AI4EPS/GaMMA) / [PyOcto](https://github.com/yetinam/pyocto) | associators | MIT | PyOcto 10–70× faster than alternatives | production |
| [QuakeFlow](https://github.com/AI4EPS/QuakeFlow) | pipeline | MIT | 575 commits, 122 stars | production/research |
| [EQcorrscan](https://github.com/eqcorrscan/EQcorrscan) | template matching | LGPL | 188 stars | production; no LICENSE file at root (scanners report NOASSERTION) |
| [ObsPy](https://github.com/obspy/obspy) | I/O framework | LGPL-3.0 | 1,332 stars, 16,244 commits | foundational; NumFOCUS affiliated |
| [STEAD](https://github.com/smousavi05/STEAD) | labelled waveforms | CC-BY-4.0 | ~1.2M traces, ~85 GB | mature; near-saturated as a benchmark |
| [MLAAPDE](https://code.usgs.gov/ghsc/neic/neic-mlaapde) | labelled waveforms | USGS public domain | >5.1M recordings, local to teleseismic | published (SRL 2023) |
| [CEED](https://huggingface.co/datasets/AI4EPS/CEED) | labelled waveforms | MIT (HF card); dataset licence unverified | ~653k events, ~4.1M traces, ~575 GB, 2000–2024 | new (2025) |
| [CREW](https://github.com/albertleonardo/CREW) | labelled waveforms | **none** | 1.6M waveforms | dormant since Oct 2024 |
| [SeisLM](https://github.com/liutianlin0121/seisLM) | foundation model | **none** — the CC-BY is the *preprint's* licence | 11.4M / 90.7M params | dormant since Oct 2024; code and weights all-rights-reserved |
| [SeisMoLLM](https://github.com/StarMoonWang/SeisMoLLM) | foundation model | MIT | GPT-2 small backbone (~124M) + embedder | research code, 33 stars |
| [SeisT](https://github.com/senli1073/SeisT) / [SeisCLIP](https://github.com/sixu0/SeisCLIP) | supervised / contrastive models | MIT | 98k–670k params; ViT-small | research code |

### 9.4 Forecasting models and reanalysis code

| Asset | Kind | Licence | Scale | Maturity |
|---|---|---|---|---|
| [RECAST](https://github.com/keliankaz/recast) | neural temporal point process | **UC Santa Cruz Noncommercial** | 22 stars, 15 commits | research code; **reimplement, do not vendor** |
| [FERN](https://github.com/google-research/google-research/tree/master/earthquakes_fern) | neural rate forecaster | not confirmed | single notebook | paper companion, unmaintained |
| [FusionEarthquake](https://github.com/XiongTLu/FusionEarthquake) | hybrid NPP | **none** | 0 stars; large checkpoint bundle | fresh (Aug 2026); all rights reserved |
| [QuakeGen](https://ai4eps.github.io/QuakeGen/) | diffusion forecaster | unconfirmed | trained on 2.2M events / ~2,050 sequences | **repository returned 404 on 2026-09-04**; forecasts archived on OSF |
| [pred_EQ_aftershockXYZ](https://github.com/amignan/pred_EQ_aftershockXYZ) | reproduction | not specified | small | archival; the one-neuron baseline |
| [aftershocks_issues](https://github.com/rajshah4/aftershocks_issues) | leakage reanalysis | **none** | 97 stars | abandoned 2019; cite it, do not depend on it |
| [slow-slip-forecasting](https://github.com/vkeane29/slow-slip-forecasting) | slow-slip forecaster | **none** | 14 commits, single region | prototype (2026); load-bearing for a claim yet legally unusable |

### 9.5 Geodesy, DAS and observation services

| Asset | Kind | Licence | Scale | Maturity |
|---|---|---|---|---|
| [Nevada Geodetic Laboratory](https://geodesy.unr.edu/) | GNSS time series | open, no formal licence; citation requested | 17k–23k stations; final daily (~2-week lag), rapid (24 h), 5-min rapid | operational, daily |
| [EarthScope GNSS products + GeoLab](https://www.earthscope.org/data/cloud/) | GNSS time series | open (EarthScope policy) | >2,000 stations, daily | operational; the independent second processing |
| [GEONET F5 (GSI Japan)](https://www.gsi.go.jp/ENGLISH/geonet_english.html) | GNSS | free **by application**; crawlers prohibited | >1,300 stations, ~20 km spacing, since 1996 | operational |
| [ARIA-S1-GUNW / HyP3](https://hyp3-docs.asf.alaska.edu/guides/gunw_product_guide/) | InSAR products | free and open | >1.1M products | operational |
| [COMET LiCSAR + LiCSBAS](https://comet.nerc.ac.uk/comet-lics-portal/) | InSAR + time series | Copernicus terms; LiCSBAS GPL-3.0 | continental belts | operational |
| [MintPy](https://github.com/insarlab/MintPy) | InSAR time series | GPLv3+ | 832 stars | mature |
| [NISAR (ASF DAAC)](https://nisar-docs.asf.alaska.edu/availability-overview/) | L-band SAR | NASA open data | near-global land since Aug 2025; calibrated provisional since 20 Jul 2026 | early operational; validated products expected Q4 2026 |
| [Sentinel-1](https://dataspace.copernicus.eu/) | C-band SAR | Copernicus free and open | global, 6-day repeat restored June 2026 | operational |
| [Near-real-time Cascadia SSE](https://near-real-time-sse.esc.cam.ac.uk/cascadia/) | slip inversion stream | **no stated licence** | daily, ~232 stations, ~2-day latency | operational research product; the prospective testbed |
| [Coupling Cloud](https://couplingcloud.ucsd.edu) | coupling model database | **no stated licence**; per-model attribution | 96+ models, 55 publications, 21 margins | new (2026); adoption unproven; the aggregator cannot grant rights in the models |
| [GSRM v2.1](https://www.globalquakemodel.org/product/gsrm) | strain-rate model | GEM open product | global | **unchanged since 2014** |
| [PubDAS](https://doi.org/10.1785/0220220279) | DAS datasets | open per paper; per-dataset terms unverified | ~90 TB, 8 datasets | established community resource |
| [DASCore](https://github.com/DASDAE/dascore) / [xdas](https://github.com/xdas-dev/xdas) | DAS processing | LGPL / GPL-3.0 | 162 / 73 stars | stable / active |
| [DAS-realtime](https://github.com/Caltech-DASHub/DAS-realtime) | DAS streaming | GPL-3.0 | 9 stars, one deployment | research code; repository moved from `biondiettore/DAS-realtime` |
| [DAS-N2N-torch](https://github.com/sachalapins/DAS-N2N-torch) | DAS denoiser | GPL-3.0 | released weights | maintained |
| [Raspberry Shake FDSN](https://data.raspberryshake.org/) | citizen network | open via FDSN | 28,028 stations (2026-09-04) | operational; ~0.3 magnitude units worse than broadband |

### 9.6 Simulation, laboratory data and replication packages

| Asset | Kind | Licence | Scale | Maturity |
|---|---|---|---|---|
| [SeisSol](https://github.com/SeisSol/SeisSol) | dynamic rupture + wave propagation | BSD-3-Clause | 346 stars, 7,364 commits; exascale-ready | production HPC |
| [Tandem](https://github.com/TEAR-ERC/tandem) | earthquake-cycle (SEAS) | BSD-3-Clause | ~1,133 commits | research-grade, SEAS-verified |
| [QDYN](https://github.com/ydluo-c/qdyn) | quasi-dynamic cycle simulator | **GPLv3 asserted in a README badge only; no LICENSE file** | v2.3 (2020) | mature but slow-moving; repository renamed from `ydluo/qdyn` |
| [SPECFEM3D](https://github.com/SPECFEM/specfem3d) | wave propagation | GPL-3.0 | 511 stars, 4,414 commits | mature |
| [RSQSim catalogues](https://zenodo.org/records/14532399) | synthetic catalogues | CC-BY-4.0 | 715 GB (California + New Zealand) | published 2024/2025 |
| [OkadaTorch](https://github.com/msomeya1/OkadaTorch) | differentiable dislocation | **none** | 9 stars, 39 commits | early; Okada is reimplementable, so the legal risk is avoidable |
| [Quakeworx](https://quakeworx.org/) | science gateway | framework licence not stated | >1,300 users | staging/early access |
| [Marone lab data (psudata)](http://psudata.s3-website.us-east-2.amazonaws.com/) | lab experiments | **no licence statement found** | tens to >100 GB per experiment; hundreds of cycles each | actively indexed, minimally documented |
| [Kaggle LANL dataset](https://www.kaggle.com/c/LANL-Earthquake-Prediction/data) | lab benchmark | Kaggle competition rules | ~600M samples, 16 labquakes, ~9–10 GB | frozen benchmark; 4,521 teams of prior work |
| [Norisugi et al. 2025 data](https://zenodo.org/records/14925543) | metre-scale lab data | **CC-BY-4.0** (the *paper* is CC BY-NC-ND 4.0) | ~724 MB; 34 events | published 2025 |
| [labquakesde](https://github.com/Geolandi/labquakesde) | chaos characterisation | **none** | 7 stars | dormant since Jan 2023 |
| [DNN-earthquake-prediction-forecasting](https://github.com/lauralaurenti/DNN-earthquake-prediction-forecasting) | labquake deep learning | **none** | 15 commits | dormant since Oct 2022; reimplement from the paper |
| [HKAE forecaster](https://doi.org/10.5281/zenodo.13123381) | lab stress forecaster | CC BY 4.0 | single-repo research code | peer-reviewed (GMD) with archived code |
| [Bletery & Nocquet package](https://zenodo.org/records/8064086) | replication data + scripts | CC-BY-4.0, **but flagged "Embargoed Access"** | 76.5 MB scripts; 14.6 GB processed; 90-event stack | complete for reproduction — confirm downloadability first |
| [BN24](https://github.com/kyleedwardbradley/BN24) / [precursordenoise](https://github.com/kyleedwardbradley/precursordenoise) | adversarial reanalysis | CC0-1.0 / MIT | notebooks | the safer starting point for the geodetic replication |
| [OpenQuake engine](https://github.com/gem/oq-engine) | hazard and risk | **AGPL-3.0** | 448 stars; v3.26 | production; network copyleft if served |
| GEM hazard map, exposure, vulnerability | models | **CC BY-NC-SA 4.0** | global | mature; non-commercial and ShareAlike |
| [GEM Global Active Faults](https://github.com/GEMScienceTools/gem-global-active-faults) | fault database | CC BY-SA 4.0 | ~13,500 fault traces | **last updated 2021**; ShareAlike propagates to derived fault layers |

### 9.7 Licence hazards — read before depending on anything above

The audit found the licence column of the source material to be the least reliable part of it. The
specific traps, all confirmed:

- **No licence at all means all rights reserved, not "unattributed but usable".** Six assets
  circulate with an implied licence and have none: `seisLM`, `FusionEarthquake`,
  `slow-slip-forecasting`, `CREW`, `aftershocks_issues`, `OkadaTorch` (plus `labquakesde` and
  `DNN-earthquake-prediction-forecasting`). Code and weights in these repositories cannot lawfully be
  copied, modified or redistributed. The `seisLM` case is the instructive one: the CC-BY-4.0 in
  circulation is the arXiv **preprint's** posting licence, which covers the paper and not the code.
- **A paper's licence is never the code's licence, and vice versa.** Norisugi et al. (2025) is
  CC BY-NC-ND 4.0 — no commercial reuse, no derivatives, so figures and text cannot be adapted —
  while its Zenodo data is CC-BY-4.0.
- **Three restrictive licences must be planned around, not discovered late.** RECAST is UC Santa Cruz
  Noncommercial; the GEM hazard, exposure and vulnerability products are CC BY-NC-SA 4.0; ISC-GEM is
  CC BY-SA 3.0 with ShareAlike propagating to derived catalogues and a form gate blocking unattended
  ingestion. None is compatible with a permissively licensed downstream product. OpenQuake is
  AGPL-3.0, which is a network-copyleft obligation the moment the engine is exposed as a service.
- **An aggregator cannot grant rights in what it aggregates.** Coupling Cloud states no licence; its
  terms are per-model attribution to the original publications, and rights are held by those authors.
- **A README badge is not a licence grant.** QDYN's GPLv3 is asserted in a badge with no LICENSE file
  on either branch. EQcorrscan and DASCore have the same pattern.
- **Four repositories moved**, and the GitHub API rejects the old paths even where a browser
  redirects — which breaks scripted dependency resolution and SBOM tooling: pyCSEP
  (`SCECcode` → `cseptesting`), QDYN (`ydluo` → `ydluo-c`), EPBench (`CoderZY-X` → `zhiyuxu03`) and
  DAS-realtime (`biondiettore` → `Caltech-DASHub`).
- **Blanket dataset licence claims are unsafe.** The "mostly CC BY 4.0" characterisation of the
  SeisBench dataset family covers eleven datasets with eleven different rights holders, and the page
  it cited returns 404. SeisBench being GPL-3.0 says nothing about the data it downloads. Resolve
  each dataset's licence at its own source.

**Rupture itself is Apache-2.0** (`LICENSE`, ADR-0048), and every dependency must be compatible
with that; CC-BY-4.0 is the default for data Rupture publishes. The review recommended MIT/BSD as a
generic default for a project of this kind, which is not what this repository chose and is recorded
here as the review's advice rather than as Rupture's licence. Anything copyleft or non-commercial
is quarantined explicitly rather than absorbed (ADR-0062).

---

## 10. Maintaining this document

This map goes stale. Three rules keep it honest:

1. **Adding a work means adding its status, and if it is `contested` or `rebutted`, its counterpart
   in the same entry.** An entry that cites only one side of a live dispute is a defect, not an
   omission.
2. **A status changes only with a citation.** Upgrading `single-study` to `replicated` requires
   naming the independent replication. Downgrading requires naming the failure.
3. **The `negative-result` category is used, not avoided.** The most trustworthy entries in this
   entire document are the null results — Hirose et al. 2024, EarthquakeNPP, Moutote et al. 2021,
   Aguilar Suarez & Beroza, Mancini et al. 2022, Jover-Alfaro et al. 2026, Johnson/Wang/Johnson 2025,
   Bakun et al. 2005. A programme built on the field's null results stands on firmer ground than one
   built on its positive claims, which is the single most useful thing the audit had to say.
