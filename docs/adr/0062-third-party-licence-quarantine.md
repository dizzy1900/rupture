# ADR-0062 — No explicit grant means all rights reserved: the third-party licence quarantine

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Extends:** [ADR-0039](0039-gem-exposure-licence.md) (GEM products are not openly licensed),
  [ADR-0033](0033-gsim-coefficient-provenance-and-licence.md) (the AGPL question),
  [ADR-0048](0048-licence-and-ci-platform.md) (Apache-2.0 for this repository)
- **Related:** [ADR-0058](0058-evidence-status-vocabulary.md),
  [ADR-0061](0061-interoperate-with-csep-do-not-fork.md)

## Context

The re-aim widens the set of third-party assets rupture might consume from "catalogues, fault
databases and hazard models" to "any code, weights or dataset that a prediction claim depends on".
That surface is where the asset audit found its worst problems, and they are not problems of
existence — every repository and dataset checked resolved — but of rights.

Four assets listed with a licence in the inherited review have **no licence at all**: seisLM,
FusionEarthquake, slow-slip-forecasting and CREW. The most instructive is seisLM, listed as
CC-BY-4.0 "per arXiv page": the preprint's licence was mistaken for the code's. Under default
copyright, no licence means all rights reserved — the code is not merely unattributed, it is not
usable. Three restrictive licences are stated in the review but easy to miss: RECAST is UC Santa
Cruz **Noncommercial**; the GEM hazard, exposure and vulnerability products are CC BY-NC-SA 4.0
(already ADR-0039); ISC-GEM is CC BY-SA 3.0, where ShareAlike propagates into any derived
catalogue (relevant to ADR-0005's ingestion). SeisBench and QDYN are GPL. OpenQuake is AGPL-3.0,
whose network clause matters the moment anything is served (ADR-0033, and rupture already runs
OpenQuake only in a container, ADR-0011). Coupling Cloud states no licence and, being an
aggregation of third-party models, could not grant rights in them even if it did. The Norisugi et
al. (2025) paper is CC BY-NC-ND although its Zenodo data is CC-BY. And the review's licence column
contradicts itself on four assets — QuakeScope, seisLM, RECAST and CEED each carry two different
licences in different sections.

The pattern is the same as [ADR-0058](0058-evidence-status-vocabulary.md)'s: the column that looks
like a fact is a transcription, and transcriptions of licences are wrong in the direction that
makes work look permissible.

## Decision

1. **No explicit grant means all rights reserved.** An asset without a licence file or an explicit
   statement from the rights holder is recorded as `no-explicit-grant` and may not be vendored,
   redistributed, or used in anything rupture publishes. It may be read, and its *method* may be
   re-implemented from its paper.

2. **The licence is read from the artefact, not from the paper, the portal or a survey.** A
   preprint's CC-BY says nothing about the code's rights. Where the artefact carries no licence and
   the work matters, the action is to ask the authors, and the asking is recorded.

3. **Quarantine list, as of this date**, carried in `docs/DATA_SOURCES.md` and re-checked rather
   than trusted:
   - `no-explicit-grant`, do not vendor: seisLM, FusionEarthquake, slow-slip-forecasting, CREW,
     OkadaTorch, labquakesde.
   - Noncommercial, re-implement rather than vendor: RECAST (UC Santa Cruz Noncommercial).
   - Copyleft with propagation, keep behind an adapter and out of any published wheel: SeisBench
     and QDYN (GPL), OpenQuake (AGPL-3.0, network copyleft on serving).
   - ShareAlike with propagation into derived products: ISC-GEM (CC BY-SA 3.0).
   - Non-commercial share-alike: GEM hazard, exposure and vulnerability (CC BY-NC-SA 4.0).
   - No licence and no authority to grant one: Coupling Cloud — attribute per aggregated model.
   - Non-redistributable waveform corpora: NIED Hi-net / K-NET / KiK-net prohibit redistribution,
     so no openly licensed Japanese waveform corpus can legally exist; CSNCD access terms for
     non-Chinese users are unverified. Treat Japan and China as **code-only** regions.

4. **Defaults for what rupture produces:** CC-BY-4.0 for data, and the repository's own Apache-2.0
   for code (ADR-0048). A rupture product derived from a ShareAlike input carries the ShareAlike
   obligation and says so on the artefact rather than in a footnote.

5. **A mechanical check.** Every third-party asset referenced from `data/`, `baselines/` or
   `pyproject.toml` carries an SPDX identifier or the literal string `no-explicit-grant`, and
   `no-explicit-grant` blocks the publication path. The check verifies presence and vocabulary; it
   cannot verify that the recorded licence is the true one, and that limit is stated rather than
   implied.

## Consequences

- Several attractive assets are unusable as code and usable only as papers. That is a real cost to
  the prediction programme — seisLM and the geodetic foundation-model line are exactly the sort of
  thing a contributor would otherwise pick up on a weekend — and the alternative is a repository
  that cannot be redistributed.
- Re-implementation from a paper is slower and produces a different artefact, and any comparison
  against the original's published numbers is not like-for-like. Where rupture re-implements, it
  says so and does not claim to have reproduced.
- The quarantine list will go stale. Licences are added, repositories move — the audit found four
  owner renames — and an unchecked list is worse than none, so each entry carries the date it was
  checked and the URL it was checked at.
- Nothing here changes rupture's existing arrangements: the OpenQuake container (ADR-0011), the
  GSIM coefficient provenance (ADR-0033) and the GEM position (ADR-0039) are all consistent with
  it, which is some evidence that the rule is the one the project was already following.

## Alternatives considered

- **Assume permissive unless stated otherwise, as the review's column effectively did.** Rejected:
  it is wrong as a matter of copyright law, and it is wrong in the direction that creates liability
  for downstream users of an Apache-2.0 repository.
- **Vendor anyway and ask forgiveness.** Rejected. An open scientific project's redistribution
  terms are part of its credibility, and a project that plays loose with other people's licences
  will not be trusted about leakage either.
- **Avoid every restrictively licensed asset entirely.** Rejected as too strong: GPL and AGPL tools
  behind an adapter, and NC data used non-commercially with attribution, are legitimate and rupture
  already does both. The rule is quarantine and label, not exclusion.
- **Keep the list in an ADR only.** Rejected: an ADR records the decision and does not rot
  gracefully. The list lives in `docs/DATA_SOURCES.md` with check dates; this ADR is the rule.
