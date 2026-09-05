# Roadmap — the research programme

**This is what Rupture is trying to do, in what order, and what result would make it stop.**

`docs/RESEARCH_LANDSCAPE.md` is the evidence this document was built from — what has been tried,
what survived, and the closed doors. `docs/ARCHITECTURE.md` Part I is the machinery the programme
needs and does not yet have. This document is the argument that connects them: which lines are worth
a research project's time, why those and not others, and how each one dies.

Two readers are assumed at once, as everywhere else in this repository: a machine-learning
researcher with no seismology, and a seismologist with no machine learning. Where a term from
either side appears for the first time it is expanded, or it is in `GLOSSARY.md`.

Compiled 2026-09-04 from a fourteen-dimension literature survey, an adversarial citation audit of
roughly 230 entries, and the state of this tree. Every external number below is second-hand and
carries the status tag defined in `RESEARCH_LANDSCAPE.md` § 1.1 — including `negative-result`, the
category the source survey lacked and whose absence inverted a citation. Every number about this
repository is checked against the tree and against `RELEASE_STATUS.md`, which is the authority.

**How to read a track.** Every research track below has the same nine parts, in the same order:
the falsifiable claim, why it is tractable now and was not before, who came closest and where they
stopped, what Rupture builds, the success criterion as a specific number, the failure criterion that
says stop, the horizon, who can work on it, and what it depends on. **A track without a stated
failure criterion is not a research track, it is a hope.** If you find one here without one, that is
a defect and it should be filed.

---

## 1. The bet

### 1.1 The field's default position, stated fairly

The mainstream position is not stupid and it is not cowardice, and a roadmap that caricatures it
will be dismissed by the people whose adjudication it needs. Stated at its strongest:

Earthquake occurrence is well described as a clustered point process. Almost all of the
short-term probability gain that has ever been demonstrated comes from clustering — an earthquake
makes further earthquakes more likely, nearby and soon — and that gain is very large: Kagan &
Knopoff (1987) [`established`] reported a rate-uncertainty reduction of more than a thousandfold
from clustering alone. Everything beyond clustering has a thirty-year record of claims that did not
survive scrutiny, and the specific failures are documented rather than vague:
accelerating moment release is a fitting artefact reproducible in synthetic catalogues with no
acceleration (Hardebeck et al. 2008) [`established`]; the Corralitos ultra-low-frequency magnetic
precursor was a sensor malfunction [`established`]; the VAN seismic-electric-signal predictions were
too ambiguous to score and no better than Poisson after declustering [`rebutted`]; "72 % of
mainshocks have foreshocks" falls to 18–33 % under an epidemic-type aftershock sequence (ETAS) null,
and to about 3 of 53 southern Californian mainshocks that look mainshock-specific [`rebutted`]. The
best-instrumented earthquake in history, Parkfield 2004, produced no obvious precursors on the
densest network in the world (Bakun et al. 2005, Nature 437:969–974) [`established`]. Nakatani's
2020 review puts the probability gain of every non-triggering phenomenon at *G* < 20 and mostly
around 2, with p near 0.05 — against clustering gains in the hundreds to thousands.

The institutional expression of that position is the line the International Commission on Earthquake
Forecasting drew in 2011 and that the US National Earthquake Prediction Evaluation Council, the
Japanese Cabinet Office and Mizrahi et al. (2024) have all held since: probabilistic *forecasting*
is operational in Italy, New Zealand and the United States; deterministic *prediction* is endorsed
by no agency. That is a statement about what has been demonstrated, and it is correct.

### 1.2 What Rupture believes instead

Three propositions, weakest first. Each is stated so that it can be shown false, and the programme
is built so that failing at proposition 1 or 2 still produces a result worth publishing.

**Proposition 1 — the measurement apparatus is not honest yet, and the dishonesty is measurable.**
The field evaluates short-term forecasts and precursor detections on final, revised data, and calls
the result out-of-sample because the timestamps are ordered correctly. They are not the same thing.
A catalogue event's magnitude, location and *existence* are revised for months after the event; a
GNSS position solution from the final-orbit product does not exist for about two weeks; the
catalogue in the first hours after a mainshock is a different object from the archive, with a blind
time of roughly 162 s (Hainzl et al. 2024) [`single-study`]. Rupture's belief is that a material
fraction of published short-term skill and precursor detection is an artefact of data vintage rather
than a property of the model, and that nobody knows the size of that fraction because no vintaged
data store exists to measure it.

This is the least glamorous of the three and it is the one with the most evidence behind it. It is
also, note, a claim against a great deal of published work including some of Rupture's own future
work, which is the shape a claim should have when the project making it also has to live under it.

**Proposition 2 — the machine-learning forecasting result does not exist yet, because it has been
scored against the wrong baseline.** As of September 2026 no machine-learning model has beaten a
properly fitted ETAS in a registered prospective test (`RESEARCH_LANDSCAPE.md` § 1.2 defines what
that means, and almost nothing qualifies). The apparent wins concentrate in exactly one regime —
small events below the completeness threshold, where plain ETAS degrades — and none of them has been
compared against ETAS-I, the incompleteness-aware variant that has existed since 2021 under an MIT
licence and exists precisely for that regime (Mizrahi et al. 2021) [`single-study`]. Stockman et al.
(2023, Earth's Future 11(9) e2023EF003777) [`single-study`] beat ETAS at input Mcut 1.2 on an
incomplete enhanced catalogue and **tie at M3+**; that scope condition is routinely dropped in the
retelling. Rupture's belief is that against ETAS-I with an explicit completeness field, most of the
claimed gain vanishes — and that whatever survives is the first real machine-learning forecasting
result in this field.

Note the direction. Proposition 2 predicts a negative. If Rupture is right about it, the deliverable
is a definitive null that closes catalogue-only neural forecasting as a line, and that is worth more
to the field than another parity claim.

**Proposition 3 — the actual bet.** There exists at least one natural fault system where a
continuously observed, below-catalogue quantity carries information about the fault's *future*
state, not merely its present state, at a lead time inside that system's measured predictability
horizon; and this is demonstrable prospectively by an open project within a decade.

Everything in propositions 1 and 2 is measurement infrastructure and negative-result hygiene. This
is the part that is a bet. It is not "earthquakes are predictable"; that sentence has no protocol.
It is narrower and harder to wriggle out of: *below-catalogue observables carry future-state
information somewhere, and it can be shown prospectively.*

The honest case for it is thin and specific, and the honest case against it is strong. For it: the
one laboratory result that replicated is that a sheared fault's continuous low-amplitude acoustic
emission reads its instantaneous frictional state (Rouet-Leduc et al. 2017, R² = 0.89
[`replicated`]; Norisugi, Kaneko & Rouet-Leduc 2025, R²(log) = 0.84 on a 1.5 m rock fault with 34
events, against an inter-event baseline at R² = −0.28 [`single-study`]) — and the second paper
identifies the predicted latent as shear stress on velocity-strengthening creeping patches, which is
a quantity that exists in the Earth. In Cascadia, tremor power tracks GPS slip rate and 8–13 Hz
energy builds up roughly 100 days before slow-slip events (Hulbert et al. 2020) [`single-study`] —
and that build-up is explicitly *below* the tremor-catalogue detection threshold, which is the
cleanest single argument for a below-catalogue port.

Against it: every attempt on a *locked* natural fault has failed, most cleanly at Kīlauea, where a
wav2vec-2.0 model nowcasts contemporaneous displacement at R² = 0.63 and identifies future slip
onset for **3 of 20 events** (Johnson, Wang & Johnson 2025) [`negative-result`]. That is the
programme's own strongest counter-evidence and it is quoted here rather than buried in a track.

### 1.3 What would settle each proposition

| Proposition | Settled in favour by | Settled against by |
|---|---|---|
| 1. Latency leakage is material | A published table of (final-data skill − as-of skill) for ≥ 3 previously published short-term models across ≥ 2 sequences in which at least one result changes sign or loses significance at α = 0.05 | The same table with every delta inside its bootstrap interval. Then the as-of layer is a data-engineering convenience, not an evaluation requirement, and it is demoted to one |
| 2. The ML gain is a baseline artefact | Positive paired information gain per event over **ETAS-I** with a 95 % interval excluding zero on ≥ 5 of the 7 EarthquakeNPP California datasets — i.e. Rupture is wrong about proposition 2, which is the better outcome | Gains over plain ETAS fully absorbed by ETAS-I on every dataset. Publish the null; stop work on catalogue-only forecasting |
| 3. Below-catalogue future-state information exists | Any one of: pre-registered Cascadia slow-slip onset forecasts beating an inter-event-time baseline across 3–5 successive events; a non-cascading foreshock census with geodetic transients significantly above shuffled-time nulls; out-of-sequence probe skill above ETAS nulls on ≥ 20 held-out mainshock sequences | All three failing at their stated thresholds. Then the Kīlauea negative generalises: continuous data carries present state and not future state, and the largest remaining hope closes with a number attached |

Proposition 3 is a decade. Propositions 1 and 2 are not, and they come first for that reason as
well as because they gate the third.

### 1.4 One objection, recorded rather than resolved

The review's closing judgement on positioning disagrees with this repository's own framing and it is
recorded here rather than smoothed away, as it is in ADR-0053. The review argues that "measurably
raise forecast information gain toward the predictability limit, and find out where that limit is"
is falsifiable, attracts geophysicists, and is fully compatible with privately believing the limit
is higher than the field assumes — whereas "predict earthquakes" as a headline repels the exact
community whose tests confer legitimacy, and Rupture cannot self-certify a prediction claim.

CLAUDE.md has settled the positioning and this document does not reopen it. What it does is adopt
the review's sentence as the *operational* form of the target: § 1.2's three propositions are
information-gain claims with baselines and protocols attached, because that is the only form in
which the ambition can be scored. The objection is testable and ADR-0053 states its test: if after
twelve months no external group has submitted a model and no testing centre has adopted the as-of
API, the review's warning was right about the framing and the framing should change.

---

## 2. How these tracks were chosen

The synthesis ranked ten openings. This roadmap does not simply adopt that ranking, because a
ranking by scientific interest is not the same as a ranking for *this* project. Each opening was
weighted by three factors and the third is the one that moves things:

1. **P(real)** — the probability the line yields a result that survives, in either direction. A high
   probability of a clean negative counts, because a published null with a bound is a deliverable
   under principle 7.
2. **Magnitude** — how much it changes what the field can do if it works.
3. **Open-project fit** — how much an open repository with volunteer contributors, no
   instrumentation and no data agreements can actually move it, as against a funded laboratory. This
   is where several of the most interesting lines lose.

| Opening (synthesis rank) | P(real) | Magnitude | Open fit | Verdict here |
|---|---|---|---|---|
| #1 as-of layer and latency-honest replay | high | medium-high | **very high** — pure engineering on public data, and nobody has it | **T1**, first, gates everything |
| #3 completeness as a field, Mc(x,t) | medium-high | high — four lines stalled on it | high, with one caveat (§ T2 depends on station metadata this repository does not ingest) | **T2** |
| measurement layer (synthesis § "The measurement problem"; parts of #4) | high | medium-high | very high — the alarm-forecast class is a gap in the field's own open toolchain | **T3** |
| #2 adjudicate Bletery & Nocquet | high (as adjudication; the verdict itself is likely negative) | medium-high — the reusable product is the detectability harness | medium — needs a geodesist, the scarcest profile, and one data-access question is unresolved | **T4** |
| #5 beat ETAS-I, not ETAS | high (most likely a negative) | high either way | very high — datasets, splits, harness and both baselines are permissively licensed | **T5** |
| #7 residual non-cascading foreshocks | medium | high — would unify the foreshock and slow-slip literatures | medium-high | **T6** |
| #6 prospective Cascadia slow-slip timing | medium | high — the only prospective test of the transferred lab result | medium-high — labels and stream are public and update themselves | **T7** |
| #8 global reanalysis from 4.3 billion picks | medium-high | very high — the ERA5-shaped public good | **medium, not high** — see below | **T8**, staged regionally first |
| #10 below-catalogue multimodal fault-state model | low | very high | medium | **T9**, the moonshot, a decade |
| #9 fault-state assimilation, ROM plus ensemble Kalman filter | medium | high | **low for this project** | **not staffed**; § 8 |

**Two places where this roadmap departs from the synthesis's ranking, with reasons.**

*#8 is demoted from "achievable by an open project" to "achievable by an open project with a budget
it does not have".* The review's argument is that the expensive part — picking 1.3 PB — is done and
released (Ni et al. 2025, Seismica 4(2), doi 10.26443/seismica.v4i2.1738, 4.3 billion picks from
47,354 stations 2002–2025, data CC0-1.0 and code MIT) [`single-study`], leaving association and
location, which cost tens of thousands of dollars of cloud rather than a national programme. That is
right about the cost and it understates the risk: the authors themselves report no formal validation
against analyst picks, no ocean-bottom-seismometer model, and a conservative association-rate
estimate of about 25 %. A conservative 25 % association rate is the difference between a global
catalogue and an expensive disappointment, and there is no way to find out except by doing a region
first. So T8 is staged: one well-instrumented region against a known comparator, and the global run
only if the regional one clears its bar. Rupture has no funding model and this document does not
pretend one exists; § 8 says what that costs.

*#9 is not staffed at all.* Kaveh, Avouac & Stuart (2025) [`single-study`] built a 40-mode reduced-order
model 338× faster than the QDYN rate-and-state solver and coupled it to an ensemble Kalman filter,
forecasting large *synthetic* slow-slip events at 75 % true-positive rate with a reliable horizon of
about 0.4 yr; Kano et al. (2024) showed Markov-chain assimilation on 86 real GEONET stations is
feasible for the 2010 Bungo Channel event [`single-study`]. This is good science and it is the wrong
shape for this project: it needs a numerical-methods specialist, a GPL-licensed forward solver, and
a geodetic observation operator, and the warning sign is already in the record — Kano's posteriors
were implausibly tight, which indicates an over-constrained model, which is to say that model error
rather than observational information is the binding problem. Rupture will host such a track if a
contributor with that background arrives and will not open it speculatively. Stated as a rule
because it applies more widely: **a track nobody in the project can staff is not a plan, it is a
wish list entry.**

---

## 3. Foundation tracks

These three are infrastructure and they gate the science. That ordering is not modesty about
ambition; it is the ambition. The review's clearest practical finding is that the evaluation
machinery, not the modelling, is what an open project can contribute and what buys the credibility
that makes a later claim survive. Ship the scoring function before the first model.

Be honest about the cost of that ordering: **for roughly the first year Rupture will publish
infrastructure and negative results and no prediction claims at all.** A contributor who wants to
train a model in month two can do so — T5 is open from the start — but the scored, publishable
version of that work waits on T2 and T3.

### T1 — The as-of layer: vintaged data and a latency-honest replay harness

**The claim.** A measurable fraction of published short-term forecasting and precursor skill is
*latency* leakage rather than *timestamp* leakage: the model read values that were correct in
hindsight and did not exist at the moment it claims to have issued. It is currently unmeasurable
because no vintaged data store exists. If one is built, at least one published result will lose
significance when replayed on the data that was actually available.

**Why now, and not before.** Three things changed. floatCSEP (JOSS, February 2026) [`single-study`]
made prospective containerised experiments cheap, so data vintage is the remaining obstacle to
honest evaluation rather than one obstacle among many. Cloud object storage made daily catalogue
snapshots trivially affordable — a region's daily event records compress to something a DVC remote
absorbs without discussion. And the field produced a clean worked example of the failure: Girona &
Drymoni's Anchorage detection (Nature Communications, 2024) depends on USGS catalogue events that
were later deleted and vanishes on the current catalogue [`rebutted`]; the published model was the
best of twenty configurations and failed on more than fifteen subsequent qualifying events.

**Who came closest, and where they stopped.** Rhoades et al. (2018) [`established`] state plainly
that the New Zealand CSEP testing centre "did not consistently capture the real-time catalog", so
most of its results are reprocessed — the field's own flagship prospective experiment, evaluated on
revised data, admitted in a methods paragraph and not treated as a finding. Hainzl et al. (2024)
[`single-study`] quantified short-term aftershock incompleteness as a blind time of roughly 162 s,
which makes the real-time catalogue in the window that matters a different object from the archive
rather than a lagged version of it. Li & Luo (2024) [`single-study`] showed that maximum-likelihood,
b-positive and KMS b-value estimators all fail under realistic real-time incompleteness and
magnitude error — which is why the Gulia–Wiemer traffic-light dispute cannot be settled on archival
catalogues at all. Bradley & Hubbard demonstrated catalogue-revision sensitivity by hand, for one
claim, outside peer review (their critiques carry DOIs but are Substack posts). **Nobody built the
general capability.** Mizrahi et al. (2024) note that catalogue-based consistency tests have not yet
been used in a truly prospective experiment.

**What Rupture builds.** The port set in `ARCHITECTURE.md` § 2–3, concretely:

- A vintage store: daily content-addressed snapshots of ComCat, SCEDC, INGV and GeoNet for the
  active regions, with a manifest per `(source_id, snapshot_time)` recording sha256, parent snapshot
  and window covered. Revision diffs are *derived* from two payloads rather than stored, so a diff
  can never disagree with the snapshots it describes.
- `ObservationSource[T].available_as_of(as_of, window)` as the only accessor a scored model holds.
  Not a filter over a fuller object — a source that cannot serve the requested vintage raises
  `VintageUnavailable` rather than falling back to current values, which is the "adapters fetch or
  fail loudly" rule applied on the time axis.
- Both times on every observation: `valid_time` (when the thing happened) and `available_time` (when
  the provider first published *this value*). `Provenance.retrieved_at`, which the tree has today,
  is neither — it is when Rupture fetched a payload. Conflating the two is the subtle version of the
  bug this track exists to prevent.
- Per-source latency models with the documented lag and revision policy (`ARCHITECTURE.md` § 3.2).
  Every figure in that table is currently tagged `documented:<url>` and **none has been measured by
  Rupture**; measuring the realised distribution against Rupture's own snapshot series is the first
  work item, not a footnote.
- A `validate-replay` gate that fails any evaluation reading a value whose `available_time` is not
  strictly before the issue time, wired the repository's way (`mk/replay.mk`, a `GATES` entry, a CI
  step, and its name in the workflow's `covered` list).
- A replay report for every model in this repository: skill on final data minus skill on as-of data.

**Success criterion.** A published table of (final-data skill − as-of skill) for at least three
previously published short-term models across at least two sequences, in which **at least one result
changes sign or loses 95 % significance**; and adoption of the as-of API — the two-timestamp
observation type and the availability check — by pyCSEP or by a CSEP testing centre.

**Failure criterion (abandon).** If the (as-of minus final) delta lies inside its bootstrap interval
for every model and every sequence tested, latency is not a practical leakage class. Publish that,
with the interval widths, and demote the layer from an evaluation requirement to a data-engineering
convenience. `RESEARCH_LANDSCAPE.md` § 8 item 10 already records that this is a hypothesis and not a
finding; this criterion is what turns it into one or the other.

**Horizon.** 0–9 months to the first replay table for this repository's own models; 12–18 months to
the three-external-model table, because reproducing someone else's published short-term model end to
end is the slow part and not the store.

**Who can work on it.** CONTRIBUTING Path C (data and infrastructure) primarily. A seismologist
(Path B) is needed for catalogue-revision semantics — what it means when an event is deleted, when a
magnitude scale changes under a fixed event id, what "the same event" is across two agencies. A
statistician for the bootstrap on paired, dependent windows.

**Depends on.** Nothing. This is the root of the dependency graph and it is why it is first.

**Known risk, stated.** `ARCHITECTURE.md` § 3.3 is the honest bound: reconstruction can withhold a
value that was not yet published, but it cannot recover a *wrong* value that was published and later
corrected, unless the provider exposes per-event revision history. Whether ComCat, SCEDC, INGV or
GeoNet exposes enough revision history to reconstruct a past vintage is **unresolved** — ADR-0054
flags it and the review does not settle it. If none of them does, the retrospective half of this
track shrinks to "vintages from the day the store starts", the store's value becomes prospective
only, and the horizon for the external-model table moves out by however long it takes to accumulate
snapshots. That is a real risk to the track and it is not currently priced.

### T2 — Completeness as a field: Mc(x, t) shipped with every catalogue

**The claim.** A spatially and temporally resolved, uncertainty-bearing magnitude-of-completeness
field is the single missing piece that several independent research lines each stalled on, and
shipping it converts dense machine-learning catalogues from a liability into an asset.

For the ML reader: Mc is the magnitude above which a catalogue is believed to contain every
earthquake. It is not a constant. It varies with station geometry, with time of day, with how many
stations were running, and it degrades catastrophically in the minutes after a large event when
small signals are buried in the coda of the large one. Treating it as a scalar is the source of
several results in `RESEARCH_LANDSCAPE.md` § 3.1 and § 3.6.

**Why now, and not before.** Machine-learning catalogues now have *documented*, spatially
non-uniform, diurnally varying completeness rather than assumed-uniform completeness: Chung et al.
(2026) [`single-study`] report station-level Mc dropping from about 1.6 to 0.5 but with greater
variability than the routine catalogue, and Becker et al. (2024) [`single-study`] show diurnal
detection fluctuations after the 2023 Türkiye doublet. The inputs needed to model it — pick
residuals, station noise power spectral densities, station metadata, and 4.3 billion open picks —
are all public for the first time.

**Who came closest, and where they stopped.** Mizrahi et al. (2021) [`single-study`] built ETAS-I,
which models incompleteness and significantly outperforms plain ETAS pseudo-prospectively in
California precisely by simulating the small events the catalogue is missing — but with a *global
blind-time parameterisation*, not a field. Mignan (2014) [`established`] showed that foreshock
anomalies appear only when completeness reaches about three magnitude units below the mainshock,
which makes Mc the gating variable for the entire foreshock literature. Mancini et al. (2022)
[`negative-result`] diagnosed magnitude inconsistency between catalogue versions as one of three
causes of the forecasting failure they measured — feeding four catalogues from Mc 2.3 down to Mc 0.2
into ETAS and Coulomb rate-state models produced *no* significant M3+ information gain and
information *loss* at M1–M2. D'Alessandro (2026) [`single-study`] derives minimum detectable rate
changes under negative-binomial overdispersion, which is the same quantity approached from the alarm
side. **Nobody ships Mc as a field.**

**What Rupture builds.** `CompletenessField` as a first-class domain type (`ARCHITECTURE.md` § 2.2,
ADR-0060): station-level detection-probability models estimated from pick residuals and noise
spectra, aggregated to a probabilistic Mc(x, t) grid carrying its own uncertainty; uniform magnitude
re-estimation across catalogue versions of the same sequence; and two hard rules — **no Rupture
catalogue is published without its completeness field, and no forecast is scored without one.** The
existing scalar `Region.mc` becomes a degenerate field labelled `degenerate=True` so that a scalar
is never silently mistaken for a fitted Mc(x, t).

**Success criterion.** ETAS and ETAS-I fits on Mc-corrected dense catalogues recover **stable
b-values and productivity parameters across catalogue versions of the same sequence** — Central
Italy CAT0–CAT5, Ridgecrest, Türkiye 2023 — where "stable" means the parameter's 95 % interval on
version *k* contains the point estimate from version *k+1* for every consecutive pair. The
instability Mancini reported disappears.

**Failure criterion (abandon).** If parameter stability across catalogue versions does not improve
after Mc correction, the Mancini failure is caused by spatial discretisation rather than by
completeness, and effort moves to sub-kilometre triggering kernels instead. Publish the comparison
either way: "we corrected for completeness and the instability remained" is a result the field does
not have.

**Horizon.** 0–12 months for the catalogue-derived version; 12–24 months for the station-metadata
version, which is the one that is actually a field rather than an inference.

**Who can work on it.** Path B (seismologist) leads — this is a seismology problem with an
engineering tail. Path C for the pipeline and the station-metadata ingestion. Path A can contribute
the detection-probability models, which are ordinary supervised learning on pick residuals.

**Depends on.** T1 in one direction only: the "across catalogue versions" test needs versioned
catalogues, which is what T1's store provides. The catalogue-derived Mc estimate can start
immediately using `pipelines/completeness.py`, which exists.

**Known gap, stated.** ADR-0060 records it and it is the honest weakness of this track: the Mc(x, t)
construction needs station metadata, pick residuals and noise power spectra that Rupture does not
ingest today. Until that ingestion lane exists, Mc can only be estimated *from the catalogue
itself*, which is circular exactly where the catalogue's completeness is the question. The
catalogue-derived version is worth shipping anyway — it is what everyone else uses — but it must not
be described as the thing this track claims to build.

### T3 — The scoring layer: alarms, power, and the predictability budget

**The claim.** Three specific holes in the field's open evaluation toolchain are why several classes
of prediction claim cannot currently be adjudicated at all, and closing them is a
contribution independent of whether any Rupture model ever works: pyCSEP has no alarm-forecast
class, test power is essentially never reported, and no one has computed how much predictability is
theoretically left.

**Why now, and not before.** The alarm gap is longstanding and simply unfilled. The power problem
acquired its number recently: Khawaja et al. (2023) [`single-study`] showed that the CSEP spatial
(S) test cannot reject a *uniform global forecast* on a 0.1° grid without roughly 32,000 events —
while the same discrimination needs about 8 events on a data-driven quadtree grid. A test that
cannot reject a uniform forecast is not evidence of anything, and results are routinely reported
without saying which regime they are in. And the budget acquired a framework five weeks before this
document was written: Zhuang & Sornette (arXiv, July 2026) [`preprint`] define predictability as the
entropy gap between a Poisson process and the true generating process, decomposable into time, space
and magnitude components, with auxiliary observations contributing exactly their mutual information,
plus an over-performance diagnostic — a model scoring better on real data than on its own synthetics
has not reached the data's ceiling. **Adopt the framework; treat its specific claims as untested.**
It is an unreviewed preprint and this document says so rather than leaning on it.

**Who came closest, and where they stopped.** pyCSEP (BSD-3, now at `cseptesting/pycsep` after a
repository transfer) implements catalogue-based non-Poissonian consistency tests and information
gain per earthquake, and stops at rate forecasts. Zhang et al. (2024) [`single-study`] demonstrated
why the alarm gap matters: an LSTM's apparent skill vanished when the reference moved from a uniform
Poisson to a spatially varying Poisson process. Luen & Stark [`established`] showed that a trivial
"alarm after every M5.5" rule reaches p < 0.001 purely from clustering. Kagan (2007) proposed
information scores; Helmstetter & Sornette (2003) [`established`] bounded ETAS predictability and
identified the irreducible stochastic component. Berman et al. (2024, arXiv:2408.02129)
[`single-study`] report the only quantified magnitude gain, about 0.07 bits per event over
Gutenberg–Richter, unreplicated and contradicted by Stockman (2023) and by Fusion (2026).

**What Rupture builds.** Three deliverables, each separable and each upstreamable:

1. **An alarm-forecast class**, written in pyCSEP's shape and offered upstream: Molchan trajectory
   (miss rate against the alarmed fraction of space-time), area skill score, ROC, and probability
   gain *G* always reported with the alarm fraction at which it was achieved, scored against three
   mandatory references — an alarm-rate- and footprint-matched random alarm set, a spatially varying
   Poisson model, and a clustering reference derived from ETAS alarms (ADR-0059). This is the
   `ALARM_SET` arm of `ARCHITECTURE.md` § 4.
2. **Power reporting as a required field.** `Scorer.power` and `Scorer.minimum_detectable_effect`
   are methods on the port, not optional extras, and a `Score` without them does not serialise. The
   effect size the field must be powered to detect is set by Nakatani (2020): *G* < 20 and mostly
   around 2 for every non-triggering phenomenon. An alarm experiment that cannot detect *G* = 2 has
   not tested the claim it thinks it tested.
3. **A predictability-budget library** on top of pyCSEP: per-region H(Poisson), H(ETAS), H(ETAS-I)
   with confidence intervals and the time/space/magnitude decomposition, the over-performance
   diagnostic run on every submitted model, and a reported gain expressed as a fraction of the
   estimated remaining budget rather than as a bare likelihood.

**Success criterion.** Two numbers and one adoption event. (a) The alarm class merged upstream into
pyCSEP, or — if upstream declines — used by at least one external group in a published paper. (b)
A reproducible published table of predictability budgets for 5–10 regions with the
time/space/magnitude decomposition and confidence intervals. (c) Every score this repository emits
carries its power and its minimum detectable effect, enforced by a gate rather than by review.

**Failure criterion (abandon), per deliverable.** For the alarm class: if after twelve months it is
neither merged nor used by anyone outside this repository, it is a private convenience and should be
maintained as one rather than presented as a contribution to the field. For the budget: if
entropy-rate estimates prove unstable to ETAS parameterisation and catalogue version — confidence
intervals spanning an order of magnitude — the budget is not measurable at current data volumes;
drop it and report paired information gain alone. Power reporting has no abandon criterion; it is
arithmetic and it stays.

**Horizon.** 0–12 months. The alarm class is a paper-sized contribution and the smallest useful unit
in this document.

**Who can work on it.** Path A or Path C for the alarm class and the power arithmetic — no
seismology is needed to implement a Molchan diagram correctly. Path B to review the reference
models, which is where the domain knowledge actually lives. A statistician or information theorist
for the budget.

**Depends on.** Nothing hard. The budget's ETAS-I terms want T2's completeness field to be
meaningful, but the Poisson and plain-ETAS terms can be computed today against
`adapters/evaluation/pycsep.py` and the pinned `lmizrahi/etas` at commit `097f08b6`.

---

## 4. The adjudication track

### T4 — Adjudicate Bletery & Nocquet, and ship the detectability harness that outlives it

**The claim.** The stacked ~2-hour precursory slip signal reported in GNSS data is common-mode
noise; and — the part that matters more — the reusable product of establishing that is an
injection–recovery curve giving the minimum detectable precursory moment as a function of lead time
and station density, against which every future geodetic precursor claim must be scored.

**Why now, and not before.** Both sides released code and data. Four new M7.5+ events (Kahramanmaraş
2023, Noto 2024, Hyuga-nada 2024, Kamchatka 2025 M8.8, Myanmar 2025 M7.7) are out of sample with
respect to the original stack. The Nevada Geodetic Laboratory serves 5-minute series for roughly
17,000 stations. The dispute is stalled for one specific reason: nobody has run injection tests as a
pre-registered protocol, so each side's analysis is a demonstration rather than a test.

**Who came closest, and where they stopped.** Bletery & Nocquet (Science 2023; Seismica 2025)
[`contested`, leaning `rebutted`] concede that the signal disappears under common-mode filtering but
argue the filter removes real tectonic signal, and put the noise explanation below 1 %. Bradley &
Hubbard (2023/2024) — carrying DOIs but published as Substack posts, not peer-reviewed — show that
the filter preserves 80–95 % of injected earthquake-like signal, that three events (El
Mayor-Cucapah plus two Tohoku-related) drive the final spike, and that far-field noise alone
regenerates the characteristic shape. **The peer-reviewed piece of that record is a null with a
bound**: Hirose, Kato & Kimura (GRL 2024) [`negative-result`] stacked independent tiltmeters, found
no acceleration, and bounded Tohoku preslip below 5 × 10¹⁸ N m, about Mw 6.4 — smaller than the
~Mw 6.9 the GNSS stack implies. Nobody has published recovery curves, which is what would convert an
argument into a measurement.

**What Rupture builds.** A pre-registered adversarial re-analysis: both pipelines reproduced end to
end; synthetic near-field preslip (Mw 5.5–7, 1–48 h) injected into real NGL and, where licensing
permits, GEONET series through realistic Green's functions; recovery scored under multiple denoisers
— far-field common-mode filtering, a learned single-station network, a spatio-temporal graph model —
with leave-one-event-out, noise-only surrogate stacks, and the post-2023 events held out. The
injection and recovery machinery is packaged as a general `null_test` module, which is the piece
that outlives the verdict. The pre-registration declares the decision threshold and the failure
criterion before any of it runs (ADR-0056).

**Success criterion.** A published receiver-operating characteristic and a stated detection
threshold curve — minimum detectable precursory moment against lead time and station density — plus
a verdict carrying a false-positive rate estimated from shuffled-origin-time nulls. Ideally, a
protocol that both original groups endorse before results are seen. That last clause is the whole
point of the track: a project trusted to referee is worth more than a project trusted to model.

**Failure criterion (abandon).** Inverted, and deliberately so. If the signal survives independent
processing, survives exclusion of the three dominant events, and reproduces on the post-2023 events
at pre-registered significance, then Rupture was wrong, the door reopens, and the project pivots to
per-event detectability. That is the more valuable outcome and the less likely one. The track's
*actual* abandon condition is access: if the Bletery & Nocquet Zenodo record (8064086) cannot be
downloaded and no equivalent is obtainable, the adjudication half is not runnable and only the
detectability harness proceeds.

**Horizon.** 3–12 months, conditional on recruiting a geodesist. Without one, this track does not
start; see below.

**Who can work on it.** Path B, specifically a geodesist, and this is the scarcest profile in the
project. The review recommends recruiting deliberately, ideally by co-authoring with participants
from both sides of the dispute — which is also the strongest available guarantee that the protocol
is fair. Path A can build the learned denoisers. A statistician owns the null construction.

**Depends on.** T1 for the vintage discipline (the GNSS final-orbit product is the textbook latency
leak: reading a two-week-latency product at a one-hour lead time), and T3 for the power and minimum
detectable effect reporting, which is the harness's entire output.

**Two access facts that block this track if assumed rather than checked.** The Zenodo record 8064086
carries both a CC-BY-4.0 licence and a DataCite "Embargoed Access" flag, so its actual availability
must be confirmed in writing before work is scheduled on it (`kyleedwardbradley/BN24` is CC0 and
unrestricted). And GEONET data is by application. Neither is resolved.

---

## 5. Science tracks

### T5 — Beat ETAS-I, not ETAS

**The claim.** Every claimed machine-learning forecasting gain that comes from small events is a
robustness-to-incompleteness gain measured against a baseline that was never designed for incomplete
data. Against ETAS-I with an explicit Mc field, most of that gain will vanish — and whatever
survives is the first real machine-learning forecasting result in this field.

For the seismologist: this is the track where the ML community's own tools are turned on its own
strongest claim, and the expected outcome is that the claim does not survive. For the ML researcher:
this is the track that starts on day one, because the datasets, the splits, the harness and both
baselines are already permissively licensed and downloadable.

**Why now, and not before.** ETAS-I has existed since 2021 under an MIT licence and **no
machine-learning paper has ever used it as the comparator**. That sentence is the whole opening.
EarthquakeNPP (TMLR 2026) [`negative-result`] supplies seven California catalogues with splits and a
harness, so the comparison is a matter of running it rather than of building a corpus. Three
independent groups — Stockman (2023) on the Apennines at Mcut 1.2, Google's FERN+ on Japan, and
Fusion (2026) — find machine-learning gains *only* when small events are included, which localises
the effect precisely where ETAS-I is the correct baseline.

**Who came closest, and where they stopped.** EarthquakeNPP tested five off-the-shelf
spatio-temporal neural point processes (NSTPP, DeepSTPP, AutoSTPP, DSTPP, SMASH) on seven California
catalogues; **none beat ETAS** on temporal or spatial log-likelihood, and the generative variants
failed CSEP consistency tests badly (DSTPP scoring 0 % on the N-test on two datasets) — they
collapse during large sequences for want of magnitude marks and long memory. Stockman et al. (2023)
beat ETAS at input Mcut 1.2 and tie at M3+ [`single-study`]. Fusion (2026) and NMRP (2026) claim
temporal-likelihood parity with ETAS priors, retrospectively, and **ran no CSEP generative tests**
[`single-study`]. QuakeGen (2026) beats the weak USGS Reasenberg–Jones baseline and only *matches*
tuned ETAS regionally; its code repository returns 404 [`single-study`]. RECAST wins only above
about 10⁴ events and is UC Santa Cruz **Noncommercial**, so it must be re-implemented rather than
vendored (ADR-0062).

This repository has its own entry in that record, arrived at independently on different regions.
The neural temporal point process scored **+0.394 nats per event on Türkiye** — but with **1
paired-T win in 10 windows and 0 Wilcoxon wins in 29** — and **−0.346 nats per event on Nepal**. A
positive mean carried by one window in ten is a heavy tail, not a win. The log-linear ensemble beat
ETAS on information gain in Türkiye only (**+0.335 nats per event, interval [+0.267, +0.404]**) and
was **not promoted**, because the promotion rule encoded in `promotion.py` requires 12 consecutive
windows in 2 of 3 regions at α = 0.05. That interval assumes independent events, which is the wrong
assumption for a clustered catalogue, and replacing it with a block bootstrap is a first task in
CONTRIBUTING Path A.

**What Rupture builds.** A magnitude-marked, long-memory spatio-temporal model — summed-kernel or
full-history attention — with a neural non-stationary background and an explicit Mc(x, t) input from
T2, scored by paired information gain against **both** ETAS and ETAS-I with block-bootstrap
confidence intervals, plus roughly 10,000-catalogue CSEP N/S/M/PL consistency tests, which is the
test no 2026 hybrid has run. The harness refuses to report a score on a catalogue below the routine
Mc without its ETAS-I baseline computed on the same data (ADR-0059); that refusal is the track's
central mechanism, not a nicety.

**Success criterion.** Positive paired information gain per event over **ETAS-I** with a 95 %
interval excluding zero on at least **5 of the 7** EarthquakeNPP datasets, plus CSEP consistency
pass rates at or above ETAS's, including during the El Mayor-Cucapah and Ridgecrest windows — the
sequences where the off-the-shelf models collapsed.

**Failure criterion (abandon).** If gains over plain ETAS are **fully absorbed by ETAS-I on every
dataset**, the small-event machine-learning result is an artefact of baseline choice. Publish that
as a definitive negative — with the per-dataset gains and intervals, so that it is a measurement and
not an opinion — and **stop work on catalogue-only forecasting entirely.** That is a real abandon
condition with a real consequence: it closes a line this repository has already invested two phases
in.

**Horizon.** 6–24 months. The ETAS-I comparison alone is 3–6 months and is worth publishing on its
own, whichever way it goes.

**Who can work on it.** Path A leads. Path B for the ETAS-I fitting and its diagnostics, which is
where an ML researcher will get it wrong without noticing.

**Depends on.** T2 for the Mc field — this is the hard dependency, because "explicit Mc input" is
the difference between this track and the papers it is criticising. T3 for power reporting. T1 for
the as-of reads, without which the result is not prospective in the sense `RESEARCH_LANDSCAPE.md`
§ 1.2 defines. A weaker version can start immediately with the catalogue-derived Mc estimate; it
should be labelled as the weaker version.

### T6 — The residual non-cascading foreshocks, and whether they are aseismic slip in disguise

**The claim.** The 3–20 % of foreshock sequences that survive an ETAS null are not cascades, are
driven by aseismic slip, and are therefore detectable in geodesy. That coincidence is testable, and
if it holds it unifies the foreshock and slow-slip literatures into one below-catalogue observable.

For the ML reader: "cascade" here means the foreshocks caused the mainshock the same way any
earthquake makes further earthquakes more likely — no special precursory process required. The ETAS
null is the test of whether ordinary triggering explains the observed foreshocks. What survives that
null is the interesting population, and it is small.

**Why now, and not before.** The prevalence argument is settled enough to define a target rather
than argue about one: the famous 72 % became 18–33 % under an ETAS null, and about 3 of 53 southern
Californian mainshocks look mainshock-specific [`rebutted`]. Nishikawa & Koyama (2025)
[`single-study`] find significant acceleration before only 3–4 % of large earthquakes globally —
but report that where it occurs it is **not** explained by aftershock cascades, which implies an
aseismic driver they could not observe. Meanwhile the geodetic side shows the same signature from
the other direction in specific sequences: Iquique 2014 (four slow-slip events Mw 5.8–6.2 with
migrating foreshocks), Tohoku 2011 (migrating repeaters), Kamchatka 2025 (foreshock migration at
roughly 7 km/day at a locking boundary), Hyuga-nada 2024 (slow-slip recurrence shortening from about
2 years to 1). **Nobody has run the two censuses against each other.**

**Who came closest, and where they stopped.** Trugman & Ross (2019) [`contested`] found widespread
foreshocks; van den Ende & Ampuero (2020) and Moutote et al. (2021) established the ETAS-null
methodology that cut the number down — these must be cited together, never separately.
Mignan (2014) [`established`] established the precondition: foreshock anomalies appear only when
completeness reaches about M−3 below the mainshock, which is why this track cannot start before T2.
Martínez-Garzón & Poli (2024, 33 sequences) [`single-study`] argue that cascade-versus-preslip is a
false dichotomy. Lippiello et al. (2025) [`single-study`] propose a falsifiable 45-minute waveform Q
index (10 of 11 foreshocks against 4 of 57 non-foreshocks) — on a region-selected sample, which is
the caveat that travels with it. Norisugi et al. (2025) supply the physical target: the predictive
latent in the laboratory is stress on creeping patches, which is the same object the geodesy would
be measuring.

**What Rupture builds.** A standardised ETAS-null foreshock-significance library, run across all
machine-learning-complete catalogues (QTM, Central Italy, Japan, Chile, Türkiye) **with completeness
fields**; a global census of the sequences that survive; and, for each survivor, a matched geodetic
search — NGL 5-minute and daily, tilt, strain, InSAR — with nulls pre-registered before the search,
reporting either a detection or a moment upper bound.

**Success criterion.** A published census with confidence intervals in which non-cascading foreshock
sequences show geodetic transients **at rates significantly above shuffled-origin-time nulls at
α = 0.05**; or, failing that, a quantitative statement that any associated aseismic moment is below
current sensitivity — **with the sensitivity number**, in the form Hirose et al. (2024) established.
Either output is publishable and the second one is the more likely.

**Failure criterion (abandon).** If the non-cascading population is statistically indistinguishable
from ETAS surrogates once completeness fields are applied, the residual is an artefact of
completeness heterogeneity and **the whole foreshock line closes.** Note what that would also mean:
it would be a second, independent confirmation that Mc heterogeneity manufactures apparent signals,
which is T2's thesis arriving from an unexpected direction.

**Horizon.** 12–30 months, and it cannot start before T2 has a completeness field, because the whole
question is whether the residual survives completeness correction.

**Who can work on it.** Path B jointly — a seismologist for the census, a geodesist for the matched
search — with a statistician owning the null construction. Path A can build the significance library
and the surrogate generator, which are ordinary statistical computing.

**Depends on.** T2, hard. T3 for the power reporting, without which "no transient found" is not a
result. T1 for vintage honesty on the geodetic products.

**Known difficulty, stated.** `RESEARCH_LANDSCAPE.md` § 8 item 7 records that the prevalence numbers
are unstable across studies (33 %, 19 %, 3 of 53, 3–4 % globally) because they measure different
things on different catalogues with different nulls. Anyone working this track should expect to
spend real effort defining the quantity before measuring it, and that definitional work is itself a
deliverable.

### T7 — Prospective Cascadia slow-slip timing from continuous seismic energy

**The claim.** The one machine-learning result that held up — that a fault's continuous
low-amplitude emission encodes its frictional state — transfers to the Earth only where a fault
broadcasts a slip-modulated continuous signal, and Cascadia is the only place where that can now be
tested prospectively against ground truth the forecaster did not construct.

**Why now, and not before.** Hulbert et al. (2020) was retrospective on a 50/50 split with tremor
logs as labels. Since then: six more slow-slip cycles (2018–2026); Gualandi (2025) publishes a
daily-updated Cascadia slip inversion with roughly 2-day latency, explicitly positioned as a
forecasting base (daily folders run 2024-07-08 to 2026-09-02); Costantino (2023/2026) provide
independent machine-learning slow-slip catalogues (78 events at 87.5 % recall) and denoised 15-year
slip histories. **The labels are now independent of the model, and the evaluation stream updates
itself** — which is what makes a genuinely prospective test possible rather than a better
retrospective one.

**Who came closest, and where they stopped.** Rouet-Leduc et al. (2019) [`single-study`] ran a
random forest on 40 Hz continuous data and estimated GPS displacement rate at correlation above 0.6
on 60-day windows. Hulbert et al. (2020) [`single-study`] ran gradient boosting on 8–13 Hz
interquantile-range energy from borehole stations and estimated time-to-next-slow-slip-event at
correlation about 0.56, with an exponential energy build-up beginning roughly 100 days ahead — and
**missed the 2018 event**. Two things about that result matter for the architecture: a model trained
on catalogued tremor alone cannot reproduce it, because the signal is below the tremor-catalogue
detection threshold; and the split was retrospective, so its skill is unestablished prospectively.
Gualandi et al. (2020) [`single-study`] bound the deterministic horizon: Cascadia slow slip is
low-dimensional chaos with correlation dimension below 5 and a predictability horizon of 2–65 days
by segment. Keane et al. (arXiv 2608.30861, 31 August 2026) [`preprint`] claim 37.9 ± 4.3 days on
Hikurangi; that was four days old at survey and **nothing here is built on it**.

**What Rupture builds.** A hash-timestamped public forecast log for the next 3–5 Cascadia slow-slip
onsets, each issued *before* the event, from borehole continuous-energy features (2005–present,
roughly 7–9 Vancouver Island stations), scored against Gualandi's daily stream and Costantino's
catalogues, with an inter-event-time baseline and — mandatory — an embedding-estimated predictability
horizon published alongside every lead-time claim. A lead-time claim exceeding that bound is rejected
mechanically by the harness rather than argued about (`ARCHITECTURE.md` § 1.3).

**Success criterion.** Pre-registered onset forecasts for 3–5 successive slow-slip events beating an
inter-event-time baseline on both mean absolute error and Brier skill score, with every forecast
timestamped in public history before the event and every lead time inside the estimated horizon.

**Failure criterion (abandon).** If prospective forecasts do not beat the inter-event-time baseline
across three consecutive slow-slip events, the Hulbert result was a retrospective-split artefact.
Publish the null — which also closes the strongest remaining transfer path from the laboratory
literature to the Earth, and is therefore one of the more consequential negatives available.

**Horizon.** 18–48 months, and the horizon is set by geophysics rather than by engineering: Cascadia
slow-slip events recur on roughly a 14-month cycle, so three successive events is about three and a
half years of waiting no amount of compute shortens. The forecast log can open within 6 months; the
verdict cannot arrive before then.

**Who can work on it.** Path A and Path B jointly, with a geodesist for label semantics — what
counts as an "onset" in a slip inversion is a modelling choice and it must be fixed in the
pre-registration, not after.

**Depends on.** T1 for the as-of layer, and here the dependency is not decorative: Gualandi's
inversion has about 2-day latency and updates in place, so a forecast scored against today's version
of a stream that was different two days ago is exactly the leak T1 exists to prevent. T3 for the
alarm-style scoring and power reporting.

**One boundary, stated.** This track forecasts *slow-slip onsets*, not earthquakes. The review is
explicit that slow-slip-as-precursor is a closed door — rates rise only up to about 3× during
slow-slip events and relax quickly, and most are followed by nothing, so the false-alarm rate is
crippling (Dascher-Cousineau & Bürgmann 2024) [`single-study`]. Nothing in T7 may be presented as an
earthquake forecast, and the tractable follow-on question is whether a given slow-slip event *loads
a locked asperity*, not whether one occurred.

---

## 6. The public-good track

### T8 — Regional reanalysis first; the global catalogue only if the region clears its bar

**The claim.** Associating and locating an open pick database into a versioned, uniformly processed
catalogue with per-cell completeness is the ERA5-shaped public good this field lacks; and it is
achievable by an open project *because the expensive part has already been done and released* — but
the association step is unvalidated and must be proven on one region before anyone spends money on
the globe.

**Why now, and not before.** Ni et al. (2025) [`single-study`] ran a deep-learning picker over 1.3 PB
from 47,354 stations spanning 2002–2025 in under three days on cloud infrastructure, and released
4.3 billion P and S picks (data CC0-1.0, code MIT). Nobody has associated and located them. PyOcto
is 10–70× faster than the alternatives and VORA is training-free; GraphDD and SPIDER handle millions
of relocation parameters on GPU. The unit economics changed from "national programme" to something
an open project could plausibly fund.

**Who came closest, and where they stopped.** QuakeFlow is the reference pipeline. Becker et al.
(2024) [`single-study`] showed a deep picker plus a graph associator beating both the routine and
the GaMMA catalogues on the Türkiye doublet. Puente Huerta et al. (2025) [`single-study`] rank two
associators top on synthetic benchmarks. **The pick-database authors themselves left the association
layer explicitly open**, noting no formal validation against analyst picks, no ocean-bottom model,
and a conservative association-rate estimate of about 25 %. ISC-GEM (roughly 74,100 events M5+,
1904–2021, CC BY-SA 3.0, form-gated) is the comparator any reanalysis must beat on completeness —
and its ShareAlike term propagates to derived catalogues, which is a licensing constraint on the
output and not merely on the input (ADR-0062).

**What Rupture builds, in two stages.**

*Stage 1 (the decision point).* One well-instrumented region — California, where the label
environment is richest — associated and located end to end from the public picks, with uniform
magnitude estimation and a per-cell completeness field from T2, released as cloud-optimised
Parquet/Zarr under CC-BY with full versioning and provenance. Compared against the routine regional
catalogue on recall, on Omori consistency and on completeness.

*Stage 2 (only if Stage 1 clears its bar).* The same pipeline at global scale.

**Success criterion.** Stage 1: re-detection of **> 95 % of ISC M3+ events** in the region, Omori
consistency of the aftershock decay, and completeness **one magnitude unit below** the routine
catalogue, shipped with per-cell completeness fields. Stage 2: the same, globally, plus adoption as
an input by at least one external forecasting group — which is the only success criterion that
actually tests whether it is a public good rather than an artefact.

**Failure criterion (abandon).** If association rates on single-model picks stay near the authors'
conservative 25 % estimate and the resulting catalogue cannot match routine recall at M3+, the pick
database is too noisy to reanalyse without re-picking. Fall back to regional reprocessing from
waveforms where licensing permits, and publish the association-rate measurement, which is itself
information the pick database's own authors flagged as missing.

**Horizon.** 12–24 months for Stage 1. 24–48 months for Stage 2 and only with funding.

**Who can work on it.** Path C leads. Path B for velocity models and quality control, which is
where a reanalysis is won or lost.

**Depends on.** T2 for the completeness fields, which are the thing that distinguishes this from
"more events". Money for Stage 2, which does not exist; see § 8.

**The honesty note this track needs.** Mancini et al. (2022) [`negative-result`] is the reason Stage
1 exists as a decision point rather than as a formality: feeding four catalogues from Mc 2.3 down to
Mc 0.2 into ETAS and Coulomb rate-state models produced no significant M3+ information gain and
information *loss* at M1–M2. **A denser catalogue is not automatically a better one.** T8 is only
worth doing if T2 works, and if T2's failure criterion fires then T8's premise is damaged and it
should be re-argued rather than continued.

---

## 7. The moonshot

### T9 — A below-catalogue multimodal fault-state model, evaluated on forecasting rather than perception

**The claim.** Every seismic foundation model to date demonstrates only *perceptual* capability —
picking, polarity, magnitude estimation — and every one is single-station and single-modality. A
model that fuses continuous waveform, geodetic and catalogue state and is evaluated on **forecast
information gain** would either produce the first non-catalogue forecasting skill or close the
question definitively.

This is proposition 3 from § 1.2 in its most direct form, and it is a decade.

**Why now, and not before.** The component backbones all arrived in 2024–2026 and none of them have
been fused. SeisLM demonstrates waveform self-supervision with label-efficiency gains at 5 % labels
(a NeurIPS 2024 *workshop* poster, and its code carries **no licence at all**, which under default
copyright means it cannot be used — ADR-0062). PhaseNO shows multi-station picking beating
single-station [`single-study`]. GNSS-FM (June 2026) is the strongest geodetic result — 359M
parameters, 17,652 stations, 73.4M station-days, and a 90-day forecast RMSE of 6.78 mm against
58.77 mm — with **no weights released**, and one of its headline figures is internally inconsistent
in the source material (`RESEARCH_LANDSCAPE.md` § 8 item 3 flags the seismic-step localisation F1 as
`unverified`; do not quote it). The corpora are on public cloud storage at the hundreds-of-terabytes
scale, with billions of picks available as weak labels. Compute is now the least binding constraint,
which was not true five years ago.

**Who came closest, and where they stopped.** Johnson, Wang & Johnson (2025) [`negative-result`] is
the decisive precedent and it is negative in exactly the right way: a self-supervised waveform model
on Kīlauea nowcasts *contemporaneous* displacement at R² = 0.63 and identifies *future* slip onset
for only **3 of 20 events**. The model reads present state and not future state. Jafari et al.
(2024) [`negative-result`] show generic time-series foundation models pretrained on weather and
traffic underperform models trained directly on catalogues, with the gains coming from graph
structure rather than from pretraining. Laurenti et al. (2026) and the Norcia
foreshock/aftershock classifier show that fault-state information is recoverable *retrospectively*
[`single-study`]. **Nobody has probed frozen embeddings across many sequences with pre-registered
nulls**, which is the experiment that distinguishes "the representation contains state" from "the
representation predicts".

**What Rupture builds.** An analysis-ready, cloud-optimised continuous corpus (California first,
built on T8 Stage 1) with aligned catalogue, pick, geodetic and completeness labels;
self-supervised pretraining across modalities with station-geometry-aware tokens; and — the actual
deliverable, and the part that is not a compute exercise — **frozen-embedding linear probes across
20+ mainshock sequences, trained only on earlier sequences**, scored against ETAS and Markov nulls.

**Success criterion.** Out-of-sequence area under the ROC curve for pre-mainshock against background
windows significantly above the null on held-out sequences, with an ablation showing the gain
**disappears when the waveform and geodetic inputs are removed**. That ablation is the whole
experiment: without it, a fused model beating a catalogue null has demonstrated that catalogues are
in the fusion.

**Failure criterion (abandon).** If probes trained on earlier sequences show no out-of-sequence
skill above ETAS nulls across 20+ sequences, the Kīlauea negative generalises: continuous waveform
data carries present state but not future state. Publish it as a clean, bounded closure of the
largest remaining hope, with the minimum detectable effect at the achieved sensitivity. This is the
one track where the failure is arguably a bigger contribution than the success, because it would be
the first well-powered test of the question rather than another anecdote.

**Horizon.** A decade to a defensible verdict, and this document says so rather than compressing it.
The corpus is 2–3 years; the pretraining and probing is 2–3 years after that; and a *prospective*
version — which is the only version that settles anything under `RESEARCH_LANDSCAPE.md` § 1.2 —
needs several years of forward issuance after that. Anyone promising this in three years is
promising a retrospective result.

**Who can work on it.** Path A leads, at scale. Path C for the corpus, which is most of the work by
volume. Path B for null design, which is most of the work by risk.

**Depends on.** T8 Stage 1 for the corpus, T2 for completeness labels, T3 for the null and power
machinery, T1 for as-of honesty. It is downstream of everything, which is another way of saying it
is the last thing to start and the reason the first four exist.

---

## 8. Tracks Rupture is not running, and why

Saying this plainly is more credible than pretending otherwise, and some of the best available
science in this field is in these categories.

**Fault-state assimilation by reduced-order model plus ensemble Kalman filter (synthesis #9).** Not
staffed, per § 2. The reasons are the specialist background required, a GPL-licensed forward solver
that constrains what can be redistributed, and the model-error warning already in the record. The
trigger that would open it: a contributor with numerical-methods and data-assimilation experience
who wants to own it, plus T7 running so that Cascadia gives the verification stream. Rupture will
host it; it will not open it speculatively.

**Instrumentation of any kind.** Borehole observatories, drilling, dense fibre-geodesy field
campaigns and cabled seafloor deployments are capital projects requiring observatory partnerships.
The lesson the review draws from SAFOD is specific: its durable output was fault-rock mechanics, not
precursors. Rupture ingests other people's products — including the operational DAS array now
streaming 100 km of telecom fibre into a regional network at 0.6 s latency, and NISAR's calibrated
L-band products released from 20 July 2026 — and does not attempt to acquire them.

**Japanese and Chinese waveform corpora.** NIED prohibits redistribution of its networks, so no
openly licensed Japanese waveform corpus can legally exist; access terms for the Chinese national
datasets are unverified for non-Chinese users. Treat both as **code-only regions**: ship code that
users run against their own downloads, or work with derived products. This is a legal constraint,
not a preference, and no amount of contributor enthusiasm changes it.

**Operational alerting.** Rupture is a research repository and every artefact says so in its
metadata, with `research_use_only` unsettable by a caller (`ARCHITECTURE.md` § 4.1 — a
`Literal[True]` on `HypothesisBase`, and **not built**). The reasoning
is not reputational: the failure mode of a research forecast escaping into an operational channel is
measured in lives. The institutional record is also unambiguous — NEPEC states that broadcasting
predictions before expert evaluation is strongly discouraged and that USGS will not consider a
method not first tested and vetted, and the L'Aquila convictions were about communication rather
than about failing to predict.

**A parallel benchmark of the arms CSEP already scores.** The architect's pre-review thesis
proposed a continuously-running Rupture leaderboard as the contributor magnet, and the review
contradicts it: pyCSEP (BSD-3), floatCSEP (BSD-3), EarthquakeNPP (MIT) and the CSEP California
archive (56.4 GB, CC BY 4.0) exist and are permissively licensed, and extending them buys the
adjudication Rupture needs while forking them buys isolation. The 2024 Delphi elicitation of 20
experts found 74 % agreeing that a model is ready when tested by a third party such as CSEP and
79 % considering benchmark comparison important — the only near-consensus requirements in the whole
survey.

**Where that leaves the board, stated exactly, because the two ADRs are easy to misread as
agreeing more than they do.** ADR-0061 settles the rate-grid and simulated-catalogue arms: package
models as floatCSEP containers, submit to a live CSEP experiment, offer the alarm-forecast class
upstream to pyCSEP, and never restate in Rupture's vocabulary an arm CSEP already scores. ADR-0057
separately *accepts* operating a forward-in-real-time board for the arms no testing centre scores —
alarms, hazard functions, state estimates — on the ground that a submitted precursor claim has
nowhere else to be adjudicated, and it prices that honestly: continuous operation is an indefinite
duty roster, targets arrive at the earthquake rate, and a board cannot be quietly abandoned after a
bad quarter. Its failure criterion is twelve months: no external submission and no external
adoption of the as-of API means the board is a private scoreboard, Rupture folds its models into
the CSEP experiments, keeps the as-of layer as internal infrastructure, and publishes the operating
experience as a negative result about open benchmark design.

**This roadmap does not staff that board and has no track for it.** It is an accepted decision
without a research track, which is a real gap rather than a tidy division of labour: T3 builds the
scorers the board would need and stops there, and nobody has costed the operating half.
`ARCHITECTURE.md` § 4.4 is the mechanism; § 13 item 11 records the gap.

**Money, stated rather than assumed.** None of the horizons above are costed and Rupture has no
funding. The review identifies funding lines whose wording permits this work — USGS Earthquake
Hazards Program external grants list "earthquake rupture forecasting and occurrence prediction"
among FY2027 priorities (solicitation G27AS00075, up to $5M/yr, with a stated deadline of
4 June 2026 that has now passed); NSF CAIG; Horizon Europe Cluster 3 DRS-02 (EUR 8M, 2026, requiring
a civil-protection partner); MEXT STAR-E in Japan. It also names four programmes that will *not*
fund this because none of them names earthquakes. **T8 Stage 2 is the only track that is blocked on
money rather than on people**, which is a useful thing to know: everything else is limited by
contributors, and T4 specifically by one contributor profile.

---

## 9. Sequencing and dependencies

The infrastructure gates the science. That is the honest statement and it is worth making
uncomfortably plainly: **T5, T6, T7 and T9 all produce results that are not defensible until T1, T2
and T3 exist**, because without them a result is scored on revised data, against the wrong baseline,
with unknown power. A model trained in month two is welcome; a *claim* made in month two is not.

```
T1 as-of layer ────────┬──────────────────────────────────► T4 adjudication
  (0-9mo, no deps)     │                                     (3-12mo, needs a geodesist)
                       ├──────────────────────────────────► T7 Cascadia SSE
T2 completeness field ─┼───► T5 beat ETAS-I ───────────┐     (18-48mo)
  (0-12mo, soft T1)    │      (6-24mo)                 │
                       ├───► T6 foreshocks ────────────┤
T3 scoring layer ──────┘      (12-30mo)                │
  (0-12mo, no deps)                                    │
                                                       ▼
T2 ──► T8 reanalysis ──────────────────────────────► T9 moonshot
        (12-24mo stage 1)                              (a decade)
```

**What unblocks what, in words.**

*T1, T2 and T3 have no upstream dependencies and can run in parallel from day one.* They want
different contributor profiles (infrastructure, seismology, statistics respectively), which makes
parallelism genuine rather than nominal.

*T5 has a hard dependency on T2* and a soft one on T1. Hard, because "explicit Mc(x, t) input" is
the entire difference between this track and the literature it is criticising; a version using the
catalogue-derived Mc estimate can start immediately and must be labelled as the weaker version.
Soft, because the ETAS-I comparison is informative even on final data — it just is not prospective.

*T6 cannot start before T2* at all. Mignan's precondition — that foreshock anomalies appear only
when completeness reaches about M−3 below the mainshock — means that a foreshock census on
uncorrected catalogues measures completeness heterogeneity and calls it physics.

*T7 has a hard dependency on T1* for a reason specific to its data: the verification stream updates
in place with about 2-day latency, so scoring against today's version of it is a live latency leak.

*T4 is gated on people, not on code.* It is the only track whose start date depends on recruiting a
single profile.

*T8 Stage 1 gates T8 Stage 2 and T9's corpus.* T9 is downstream of everything.

**The parallelism this repository can actually sustain.** The worktree rule in CLAUDE.md — parallel
agents in separate `git worktree`s, touching only their own subtrees plus their own tests, docs and
`mk/<name>.mk` gate file, with real merges performed serially — is what makes three or four
simultaneous tracks possible without merge chaos. It is also the practical limit: shared files are
pre-sectioned for append-only edits, and beyond about four concurrent lanes the serial merge and
full `make validate-rupture` after each merge becomes the bottleneck. Plan for three or four active
tracks, not nine.

---

## 10. The measurement problem

### 10.1 How a Rupture claim is scored

Four layers, all mandatory, none optional. This is the synthesis's scoring function, and
`ARCHITECTURE.md` § 4.2 is the registry that enforces it.

**Layer 1 — paired information gain, in nats or bits per event, against the correct baseline.**
Every model emits per-event log-likelihoods so that a paired gain against a reference can be
computed with bootstrap confidence intervals. The reference set (ADR-0059): plain ETAS
(`lmizrahi/etas`, MIT, pinned here at commit `097f08b6`); **ETAS-I whenever sub-completeness events
are used**; Reasenberg–Jones for aftershock forecasts; Helmstetter-style smoothed seismicity for
time-independent claims; and the two-parameter logistic regression for any spatial aftershock model.
The single commonest failure in the surveyed literature is beating the weakest available baseline,
and the reference set exists to make that impossible rather than merely discouraged. One nat is
about 1.44 bits; this repository reports nats and most of the literature reports bits, which is a
conversion error waiting to happen and is why both units appear in `GLOSSARY.md`.

**Layer 2 — CSEP consistency tests on simulated catalogues.** Roughly 10,000 simulated catalogues
per forecast, scored with the catalogue-based non-Poissonian analogues of the N, S, M and
pseudo-likelihood tests. Poisson grid tests are inadequate for over-dispersed seismicity. **Every
test result ships with its statistical power**, computed on data-driven quadtree grids where power
demands it (Khawaja et al. 2023: the S-test cannot reject a uniform global forecast on a 0.1° grid
without roughly 32,000 events, against about 8 on a quadtree).

**Layer 3 — alarm-based scoring for anything that is not a rate forecast.** Molchan diagram, area
skill score, and probability gain *G* always reported with the alarm fraction at which it was
achieved, against a **clustering-aware** reference. The clustering-aware part is the binding
requirement, not the diagram: an LSTM's apparent skill vanished when the reference moved from
uniform to spatially varying Poisson (Zhang et al. 2024), and a trivial post-M5.5 rule reaches
p < 0.001 purely from clustering (Luen & Stark). Nakatani's *G* < 20 finding sets the effect size
experiments must be powered to detect.

**Layer 4 — the predictability budget as denominator.** Report gain not only in absolute bits but as
a fraction of the estimated remaining gap, with the over-performance diagnostic: a model that scores
better on real data than on its own synthetics has not reached the ceiling. The framework is
five weeks old and unreviewed; adopt it, and label its outputs as provisional until it has been
independently checked.

### 10.2 Nulls carry bounds

The fifth requirement, which the field does not currently impose. A negative result in this
repository does not say "we saw nothing". It says what Hirose, Kato & Kimura (2024) said: *any
preslip was below 5 × 10¹⁸ N m, about Mw 6.4.* Every Rupture negative result reports the minimum
detectable effect at the achieved sensitivity, and a null without a bound is to be refused by the
scorer registry in the same way a score without its baseline is refused.

This is why `Scorer.power` and `Scorer.minimum_detectable_effect` are required methods on the port
rather than optional extras (ADR-0055). A rule that lives in prose is a rule that is followed until
someone is in a hurry — which is exactly the position this rule is in today, because **the scorer
registry does not exist and no result in this repository reports its power or its minimum
detectable effect** (`RELEASE_STATUS.md` § Known gaps). Every number in this repository predates
the rule and none has been recomputed under it. T3 is what turns the paragraph above from a
standard into a check.

### 10.3 The programme scorecard

How Rupture will know whether the *programme*, rather than a track, succeeded. These are checked and
published on the stated dates whatever they say, and the answers go in `RELEASE_STATUS.md`, which
under-claims by design.

**At 12 months.** Has the as-of layer produced a replay table with a delta outside its bootstrap
interval for at least one model (T1)? Is Mc shipping as a field with at least one catalogue (T2)? Is
the alarm-forecast class merged upstream or used externally (T3)? Has any external group submitted a
model or a hypothesis card? Has any testing centre adopted the as-of API? The last two are the test
of ADR-0053's framing bet, and a "no" to both is evidence the review's positioning objection was
right.

**At 24 months.** Has the ETAS-I comparison been published, in whichever direction (T5)? Is there at
least one published negative result with a stated bound that another group has cited? Is at least
one Rupture model registered in a live CSEP experiment as a floatCSEP container? Are there
contributors from all three CONTRIBUTING paths, or only from Path A?

**At 60 months.** Has any track produced a positive result — an information gain over its correct
baseline, with a 95 % interval excluding zero, on a pre-registered prospective test? If not, have
the negatives closed lines that the field can now stop working on, and can that be evidenced by
citation? Is the measurement infrastructure in use by people who are not Rupture contributors?

**The uncomfortable one.** If at 60 months the answer is "no positive result and no adopted
infrastructure", the programme has failed on both of its bets and should say so in exactly those
words. A project whose scorecard cannot return "failed" is not measuring anything.

### 10.4 What will not be accepted as evidence of success

Stated so that it cannot be negotiated later, and drawn from `RESEARCH_LANDSCAPE.md` § 4.1:

- A result on a random (non-chronological) split of a clustered catalogue.
- Accuracy, F1 or AUC on grid cells as a headline metric — AUC 0.85 concealed a precision of 5.4 %
  in the worked example of § 5 of the landscape, and a replicated 97.97 %-accuracy random forest fell
  to 21–24 % under walk-forward validation against a 27.69 % majority-class baseline.
- RMSE or MAE on next-event time or magnitude, which assume Gaussian or Laplacian noise on power-law
  targets.
- A window, region or magnitude range chosen after the data was seen.
- The best of N configurations reported as one model. Report the selection procedure and score the
  selection.
- A gain over a baseline that was not fitted, or over the weaker of two available baselines.
- Any result whose inputs were read at a `available_time` later than its issue time.

These are to be refused by the scorer registry and by CI rather than by review, because the whole
argument of `ARCHITECTURE.md` is that domain knowledge belongs in the tooling rather than in the
documentation. **Today they are refused by review.** One of the seven has a mechanical check —
`docs/EVALUATION_PROTOCOL.md` § 7 rule 6 forbids k-fold in the catalogue lane, and the leakage
assertions in `src/rupture/adapters/forecasting/leakage.py` enforce the time cut with four injected
violations that must each be refused. The other six are enforced by a reviewer reading a pull
request, and the first task in CONTRIBUTING Path A — a unit test that fails if any scoring path
reports accuracy or AUC over grid cells — converts one more of them. Listing them here while the
tooling is a proposal is the point of the list; it is not a description of a gate that runs.

---

## 11. Explicitly out of scope

Each of these is a closed door in `RESEARCH_LANDSCAPE.md` § 4 with a "reopens if" condition. They
are out of scope for Rupture's *own* research, which is not the same as saying the questions are
uninteresting, and several of them are welcome as *submissions to be scored*.

| Out of scope | Why | Where it is argued |
|---|---|---|
| Building another picker, associator or waveform benchmark | The detection layer is won and permissively licensed; scaling model size is explicitly inefficient (+15.6 % precision for −87 % throughput in one teleseismic case). Reviving the frozen picker-benchmark repository is worth more than a new model | Landscape § 3.1, § 4.2 |
| Deep networks on engineered static-stress features | Matched by a two-parameter logistic regression (AUC 0.85 against 0.849) and beaten by distance-plus-slip (0.86), with documented target leakage between collocated ruptures and precision of 5.4 % | Landscape § 3.5, § 5 |
| Off-the-shelf spatio-temporal neural point processes on catalogues | Five tested on seven California catalogues; none beat ETAS; generative variants failed CSEP badly. The failure mode is diagnosed — do not rediscover it | Landscape § 3.3 |
| Neural magnitude prediction beyond Gutenberg–Richter | ETAS with Gutenberg–Richter beat the neural magnitude model; the one positive (~0.07 bits/event) is unreplicated and operationally negligible even if real | Landscape § 4.2 |
| Reading final magnitude from rupture onsets | Large and small earthquakes have identical onsets across roughly 100,000 co-located events | Landscape § 4.2 |
| *Generating* non-seismic precursor claims — electromagnetic, ionospheric, thermal, radon, animal | The record is closed with specific mechanisms for each failure, and every non-triggering phenomenon sits at *G* < 20. **Rupture scores submitted alarm functions from these communities; it does not generate claims in them** | Landscape § 3.10, § 4.3 |
| Slow-slip events as an earthquake alarm | Rates rise only up to ~3× during slow slip and relax quickly; most are followed by nothing, so the false-alarm rate is crippling. The tractable question is whether a slow-slip event *loads a locked asperity* | Landscape § 4.3; T7's boundary note |
| Long-horizon deterministic prediction | Cascadia slow slip is low-dimensional chaos with a 2–65 day predictability horizon by segment. A lead-time claim beyond an embedding-estimated horizon is rejected by CI rather than argued about | Landscape § 3.8 |
| A parallel benchmark of the arms CSEP already scores — rate grids and simulated catalogues | Interoperate, do not fork. **Not** out of scope: a board for the arms no testing centre scores (alarms, hazard functions, state estimates), which ADR-0057 designs, prices and gives a twelve-month failure criterion — and which is `proposed`, not accepted, precisely because this roadmap does not staff it | § 8 above; ADR-0061 for the fork rule, ADR-0057 for the board |
| Instrumentation, and non-redistributable data | Capital projects and legal constraints respectively | § 8 above |
| Operational alerting | Research repository; the escape of a research forecast into an operational channel is measured in lives | § 8 above; CLAUDE.md § How Rupture writes about results |

One class deserves separating from the rest. **The precursor communities are not being excluded;
they are being offered the one thing they have never had, which is a scorer.** The alarm arm exists
so that a frozen alarm function from any data source can be adjudicated on a Molchan diagram against
a clustering-aware reference, with its probability gain and its statistical power published. That is
a service the field has no open implementation of, and it is the role in which a project is trusted
rather than suspected.

---

## 12. What would make us wrong

The strongest case that this whole programme is misconceived, stated as well as its proponents would
state it, with the observation that would confirm it. This section is not a formality; if one of
these is right, the correct response is to stop.

**Objection 1 — the ceiling is where the field says it is, and this is a well-instrumented way of
finding nothing.** The null hypothesis that predictability beyond clustering is negligible is
consistent with every observation in `RESEARCH_LANDSCAPE.md`. Clustering gives probability gains in
the hundreds to thousands; every non-triggering phenomenon ever measured gives *G* < 20 and mostly
around 2. Thirty years of increasingly good instrumentation has not moved that, and the best case
Rupture can make — that the record was made with less data and worse methods — is exactly the case
that was made in 1990 and in 2005. On this reading, propositions 1 and 2 are true and boring
(measurement hygiene finds measurement errors), and proposition 3 is false.

*What would confirm it.* Every science track failing at its stated criterion — T5's gains absorbed
by ETAS-I, T6's residual indistinguishable from surrogates, T7 failing to beat inter-event time
across three events, T9's probes showing no out-of-sequence skill. Four independent negatives at
four different scales is not bad luck. And the honest response would be that Rupture will have
produced four well-bounded nulls and a measurement apparatus, which is a real contribution and is
not the contribution it set out to make.

**Objection 2 — this is engineering wearing science's clothes.** Three of the first four tracks
build infrastructure. The bet is that infrastructure buys credibility and unblocks science, and the
counter-argument is that infrastructure buys infrastructure: the field already has pyCSEP,
floatCSEP, SeisBench and EarthquakeNPP, and the marginal value of one more layer is small,
particularly one maintained by volunteers with no institutional home. Meanwhile the actual science
in the field is being done by people with instruments.

*What would confirm it.* The 12-month scorecard returning "no external submission, no testing-centre
adoption" and the 24-month scorecard returning "the alarm class was not merged and nobody outside
the repository used it". At that point the infrastructure is a private convenience and the honest
move is to stop calling it a contribution to the field.

**Objection 3 — "below the catalogue" is a hope with two negatives already against it.** The
architectural argument — that the signals with surviving evidence live below the catalogue —
depends on a laboratory result whose Earth analogue works only where a fault broadcasts a
slip-modulated continuous signal, and the cleanest field test of the transfer is negative (future
slip onset for 3 of 20 events at Kīlauea). Parkfield is the other one: the densest network in the
world recorded no obvious precursors before the 2004 M6.0. A programme that reorganises its entire
architecture around a class of observable that has twice failed where it was best measured has made
an expensive bet on an analogy.

*What would confirm it.* T7 and T9 both failing, and — the sharper version — T9's ablation showing
that whatever skill a fused model has *does not disappear* when waveform and geodetic inputs are
removed, which would mean the catalogue was carrying the result all along and the below-catalogue
architecture bought nothing.

**Objection 4 — the open-project premise is wrong for this problem.** The interesting instrumentation
is closed (borehole observatories, cabled seafloor networks, dense fibre), the richest waveform
corpora are legally non-redistributable (Japan, China), the strongest recent geodetic model released
no weights, and the most interesting 2026 forecasting result published no code. An open project can
have the leftovers and the evaluation, and evaluation does not discover anything. On this reading
Rupture's comparative advantage is real and small.

*What would confirm it.* Every positive result in the field over the next five years coming from
data or instruments Rupture cannot obtain — which is checkable, and should be checked explicitly at
the 60-month scorecard rather than felt.

**Objection 5, the internal one — this repository has already run the experiment in miniature and it
lost.** Two phases produced a neural temporal point process, a gridded model and an ensemble, on a
protocol written before any model was fitted. **No challenger was promoted.** The one metric beaten
(+0.335 nats per event on Türkiye) rests on an interval assuming independent events and corrects a
baseline over-forecast rather than adding information. And the deliberately leaky ablations show
that when apparent skill did appear, the leakage controls removed **9 %, 63 %, 97 % and 181 %** of
it in the four cases where a leaked model had anything to lose — on Nepal, a −0.346 loss became a
+0.429 apparent win, which is the sign as well as the magnitude. The pessimistic reading of that is
not that the models were bad; it is that this is what the honest version of the result looks like,
every time, and the roadmap is a plan to obtain more of them at greater cost.

*What would confirm it.* T5 finishing with ETAS-I absorbing every gain, which would make the
Prompt-2 result the general case rather than a first attempt.

**What none of these objections is.** None of them is an argument that the *question* is illegitimate
or that asking it is unscientific, and that argument — which the field's culture sometimes makes
implicitly — is the one this project rejects. "Nobody has done it" was never the same claim as "it
cannot be done". The objections above are much better than that one, and they are the reason every
track above carries a failure criterion.

---

## 13. Known gaps in this roadmap

Stated rather than smoothed over.

1. **Nothing here is costed in people or in money.** Horizons are elapsed time assuming someone is
   working on the track, and no track has an owner today except by analogy with the roles in
   CLAUDE.md. T4 will not start without a geodesist and T8 Stage 2 will not start without funding;
   those two are named, and the others are equally unowned.

2. **The horizons are judgement, not estimates from measured throughput.** The two anchored to
   physical rather than engineering time (T7's slow-slip recurrence, T9's requirement for years of
   forward issuance) are the more trustworthy ones, precisely because nothing about them depends on
   how fast anyone works.

3. **Every external number here is second-hand.** No paper cited has been read in full by the author
   of this document; the source is a fourteen-dimension survey plus an adversarial audit that
   checked existence and metadata rather than content. The audit found no fabricated papers, no
   invented authors and no dead DOIs across roughly 230 entries — and status inflation everywhere,
   plus two sign inversions. Verify before building on any single number.

4. **Two success criteria depend on other people's decisions.** T1's and T3's adoption criteria
   ("adopted by pyCSEP or a testing centre", "merged upstream") are not fully in Rupture's control,
   and an upstream project can decline a good contribution for reasons that have nothing to do with
   its quality. Both criteria have a fallback clause naming external *use* rather than merge, which
   is weaker and is labelled as such.

5. **The dependency graph in § 9 asserts a soft-versus-hard distinction that has not been tested.**
   The claim that T5 can usefully start on a catalogue-derived Mc estimate before T2 delivers a real
   field is an engineering judgement, and if it is wrong the whole science programme is serialised
   behind T2 rather than partly parallel to it.

6. **No track here addresses two areas the survey could not cover**: the Chinese and Japanese
   prediction literatures, which were surveyed only through English-language secondary sources, and
   Transformer-Hawkes and large-language-model catalogue forecasters, which one review dimension ran
   out of search budget before reaching. Their absence from this roadmap is not evidence that they
   are unimportant.

7. **The programme scorecard in § 10.3 has no owner and no mechanism.** It is a list of questions
   with dates and nothing in the repository causes them to be asked. A recurring issue, a calendar
   entry, or a gate that fails on a stale date would fix that; none exists, and until one does the
   scorecard is an intention.

8. **This document and `RESEARCH_LANDSCAPE.md` overlap.** The landscape owns the evidence and the
   status vocabulary; this document owns the plan and cites the landscape for evidence. Where a
   number appears in both, the landscape is authoritative, and if they ever disagree that is a defect
   to be filed rather than a judgement call for the reader.

9. **The T1 reconstruction limit is not priced.** Whether any of ComCat, SCEDC, INGV or GeoNet
   exposes enough per-event revision history to reconstruct a *past* vintage is unresolved
   (ADR-0054). If none does, T1's retrospective half shrinks to "vintages from the day the store
   starts" and its 12–18 month horizon for the external-model replay table is wrong by however long
   it takes to accumulate snapshots.

10. **The framing question in § 1.4 is deferred rather than settled.** CLAUDE.md has decided the
    positioning and this document builds on it. ADR-0053 turns the review's objection into a
    twelve-month test. If that test fires, someone has to decide what changes — the framing, or the
    conclusion drawn from the test — and this roadmap does not say which.

11. **ADR-0057's prospective board is deferred, and the tracks that depended on it need re-reading.**
    The gap was real: § 8 explained what the board is and why it is not simply "a parallel
    benchmark", but nothing here scheduled, staffed or costed it, while ADR-0057 stood as
    `accepted`. On 2026-09-05 that ADR was downgraded to `proposed` rather than a T10 being
    invented for it; its decisions 2, 3 and 4 (multi-arm scoring, as-of reads, continuous
    baselines) are unaffected because ADR-0055, ADR-0054 and ADR-0059 already carry them and T1
    and T3 build them. T3 delivers the scorers a board would need and nothing more.
    ADR-0053's third falsification condition, ADR-0057's failure criterion and the § 10.3 12-month
    question "has any external group submitted a model or a hypothesis card?" are all stated
    against a board that nothing here plans to switch on, so none of them can currently fire in
    either direction. Either a track is written for it or those three are rewritten against
    something this programme actually does; leaving it as it stands is the quiet kind of gap this
    repository is meant to catch.
