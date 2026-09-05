# ADR-0058 — The evidence-status vocabulary, and the `negative-result` category it was missing

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Related:** [ADR-0034](0034-cite-published-titles-verbatim.md) (superseded, but its surviving
  distinction — a citation attributes a statement to its author — is the premise of this ADR),
  [ADR-0053](0053-rupture-targets-earthquake-prediction.md),
  [ADR-0062](0062-third-party-licence-quarantine.md)

## Context

CLAUDE.md requires that rupture distinguish claim, replication and rebuttal when citing others, and
that `docs/RESEARCH_LANDSCAPE.md` tag every cited work with its evidence status. The re-aim makes
that register load-bearing in a way it was not before: a prediction project's roadmap is built out
of other people's results, and a mis-tagged result sends someone after a signal that is not there.

The adversarial audit of the literature review this project was re-aimed against establishes both
that the danger is real and where exactly it sits. Across roughly 230 entries it found **no
fabricated papers, no invented authors and no dead DOIs** — every arXiv identifier resolved to the
paper implied, every Zenodo DOI resolved with a matching title, every repository resolved directly
or through an owner rename, including all the 2026-dated items, which are the usual failure
surface. The bibliography is trustworthy about what exists.

It is not trustworthy about what things mean, and the failure mode has a name: status inflation,
with one outright sign inversion.

- **Warden et al. (2020) was tagged `replicated` and is a failed replication.** The paper
  approximates earlier Kakioka ULF findings for 2001–2010, then reports that alternative outlier
  rejection and alternative catalogues give inconsistent results, that extending to 2013–2018 shows
  no significant precursory activity, and explicitly urges caution about future electromagnetic
  earthquake-precursor research. As tagged, it was the strongest apparent positive in the precursor
  section and contradicted two other entries in the same section. It is a **negative result**, and
  a roadmap that had trusted the tag would have funded magnetometer work on the strength of a null.
- **Cullen et al. (2024) was tagged `replicated`** while the paper's own headline is that there is
  no significant, consistent global pre-earthquake ionospheric anomaly. The same inversion.
- **Works weeks or months old were tagged `widely-used` or `replicated`** — Zhuang & Sornette
  (preprint dated 29 July 2026), the Coupling Cloud, EarthquakeNPP, Ni et al. (2025), Sun et al.
  (PhaseNO). None can have those properties yet.
- **The same work carries different statuses in different sections** in at least eight cases
  (Trugman & Ross `contested`/`rebutted`; EarthquakeNPP `replicated`/`single-study`; Münchmeyer,
  Gualandi, Keane, QuakeScope, RECAST, CEED). Roughly thirteen works are duplicated across sections
  altogether.

The root cause is identified and is structural rather than careless: **the status vocabulary had no
category for a work whose finding is that there is nothing there.** With `replicated`,
`widely-used`, `single-study`, `contested` and `rebutted` as the only options, four debunking papers
were filed under tags that read as neutral or positive, because none of the available tags said
"this paper looked and found nothing". A vocabulary that cannot express a null in a field whose
most trustworthy results are nulls will keep producing this error.

## Decision

1. **The tag set is fixed and includes `negative-result`.**

   | Tag | Means |
   |---|---|
   | `established` | reproduced by independent groups and/or in operational use for years — the strongest tag, and the one that needs the longest record |
   | `replicated` | at least one *named* independent group reproduced the finding on data the original authors did not supply |
   | `widely-used` | third parties depend on it in published work or shipped software; the dependants are nameable |
   | `single-study` | one group, one result, not yet reproduced — the default for anything new |
   | `contested` | a substantive published challenge exists and the question is open |
   | `rebutted` | a specific published rebuttal stands and has not been answered |
   | `negative-result` | the work's own finding is an absence, a failed replication, or an upper bound on an effect |
   | `preprint` | not peer-reviewed — a *modifier*, always combined with one of the tags above, never used alone |
   | `unverified` | rupture has not checked it; permitted only as a temporary state, and never on a load-bearing citation |

   `established` and `preprint` are in the set because the register uses both heavily and a
   vocabulary that the register cannot be written in is not the vocabulary. `established` sits
   above `replicated` and carries the same twelve-month bar as decision 3, only harder: it is for
   Omori decay and Gutenberg–Richter, not for a result two groups have now seen.

   **`docs/RESEARCH_LANDSCAPE.md` § 1.1 is the normative copy of this table.** `CONTRIBUTING.md`
   reproduces it for contributors. Three copies is two too many, and a document disagreeing with
   the register about a *tag definition* is the same defect as one disagreeing about a paper's
   status.

   One thing this vocabulary does not do, stated because the register uses the same words for it:
   the per-line **Status** field in `docs/RESEARCH_LANDSCAPE.md` § 3 describes the state of a
   *research line* ("`rebutted` for the automatic downstream benefit"), not the tag of any single
   work. Read a bare tag in backticks as a work's status and a `**Status.**` paragraph as a line's.

2. **One canonical record per DOI.** A work carries exactly one status across the whole tree.
   `docs/RESEARCH_LANDSCAPE.md` is the register; every other document cites the register rather
   than restating a status. Two documents disagreeing about a paper is a defect, not a difference
   of opinion.

3. **`replicated` and `widely-used` are unavailable to a work less than twelve months past its
   first public release.** The threshold is a judgement, not a measurement, and it is written down
   so that it is arguable rather than tacit. A preprint from last month is `single-study` however
   good it is.

4. **A work tagged `contested` or `rebutted` is never cited as support without its rebuttal in the
   same sentence**, and the rebuttal's own status travels with it — specifically whether it is peer
   reviewed. Two live examples this repository must get right: the Girona & Drymoni (2024) Anchorage
   result is `contested` on the strength of Bradley & Hubbard's Substack analysis, which carries a
   DOI and is not peer review; and DeVries et al. (2018) is `rebutted` by Mignan & Broccardo (2019),
   which is a *Nature* Matters Arising and is.

5. **Never count sources.** No document in this tree says "N sources agree", because the
   bibliography this project inherited contains roughly thirteen duplicated works, sometimes with
   contradictory statuses, and a count over it overstates the evidence base by an unknown factor.
   Name the works or say nothing.

6. **Scope conditions travel with the claim.** Two correctly cited results in the inherited review
   will be read as stronger than they are unless their scope is attached every time: QuakeGen
   (2026) beats the weak USGS Reasenberg–Jones baseline on 80 global mainshocks and only *matches*
   well-tuned ETAS regionally, and its code repository returns 404; Stockman et al. (2023, *Earth's
   Future* 11(9) e2023EF003777) beats ETAS specifically at input M_cut 1.2 on an incomplete enhanced
   catalogue and *ties* at M3+. The difference between those scopes and their unscoped versions is
   the difference between "neural forecasting has overtaken ETAS" and "neural forecasting reaches
   parity under specific data conditions".

7. **A citation rupture cannot source is written as "citation needed".** Not inferred, not
   reconstructed from memory, not filled in with the nearest plausible paper.

8. **A mechanical check where one is possible.** A gate can verify: one status per DOI across the
   tree; no `replicated` or `widely-used` on a work whose recorded first-release date is under
   twelve months old; every `contested` or `rebutted` entry carrying a rebuttal reference and a
   peer-review flag; and no occurrence of the "N sources" construction. The *semantic* obligations —
   that the rebuttal is in the same sentence, that the tag matches the paper's actual finding — are
   not mechanically checkable and stay with the reviewer. Saying which half the machine covers is
   the point of writing this down.

## Consequences

- Several entries inherited from the review are re-tagged on arrival, and the re-tagging is
  recorded rather than done silently: Warden et al. (2020) and Cullen et al. (2024) to
  `negative-result`; Zhuang & Sornette (`single-study`, `preprint`), Ni et al. (2025), PhaseNO and
  the Coupling Cloud down to `single-study`. **EarthquakeNPP is the case that shows where this
  vocabulary strains.** The review tagged it `replicated` in one section and `single-study` in two
  others, and the audit's recommendation was one consistent `single-study`; but the paper's own
  headline is that none of five neural point processes beat ETAS, which is what `negative-result`
  is for. The register (`docs/RESEARCH_LANDSCAPE.md` § 3.3) carries it as `negative-result`,
  because the tag's job is to tell a reader what the work found, and the reproduction level is
  stated in the annotation instead: one group, one benchmark, peer-reviewed at TMLR 2026, not
  independently reproduced. Where the two axes pull apart like this the finding wins and the
  reproduction level goes in the prose beside it.
- The register's most valuable rows will be the negative ones. The audit's own verdict is that the
  strongest and cleanest entries in the whole bibliography are the nulls — Hirose et al. (2024),
  EarthquakeNPP, Moutote et al. (2021), van den Ende & Ampuero (2020), Aguilar Suarez & Beroza
  (3.9 % label errors across 8.6 million examples), Mancini et al. (2022), Jover-Alfaro et al.
  (2026), Bakun et al. (2005) on Parkfield — and that a roadmap built on them stands on firmer
  ground than one built on the positive claims. The `negative-result` tag is what lets the register
  say that.
- Seeding the register with the existing rebuttal record — AMR as a fitting artefact, Corralitos
  ULF as a sensor fault, VAN, Heki-type TEC, the 72 % foreshock prevalence that fell to 18–33 %,
  the Norcia animal-behaviour study whose own authors conceded no predictions are possible — means
  a contributor cannot reopen a closed case without new data, and can see immediately what new data
  would have to look like.
- Under-claiming has a cost: a work that is genuinely replicated but whose replication rupture has
  not verified sits at `single-study` and is cited more weakly than it deserves. That is the
  intended direction of error.

## Alternatives considered

- **Drop status tags and cite plainly.** Rejected: the alternative to a wrong tag is not no tag, it
  is a reader who has to re-derive thirty years of the field's consensus for every citation. The
  tag is where rupture does that work once.
- **A numeric confidence score.** Rejected: it collapses "failed replication" and "not yet
  replicated" onto one axis, which is precisely the compression that produced the Warden inversion.
  Kind of evidence and weight of evidence are different questions.
- **Inherit the review's tags and correct them as problems surface.** Rejected: the audit already
  surfaced them, and carrying a known-inverted tag into the register would be the one thing the
  audit exists to prevent.
- **Tag only the works rupture depends on.** Rejected: the works rupture chose *not* to build on
  are the ones a future contributor most needs to see tagged, because the register's main job is to
  stop the next person burning a year.
