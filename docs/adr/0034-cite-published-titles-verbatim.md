# ADR-0034: The banned-language allowlist admits published paper titles

- **Status:** superseded on 2026-09-04 by
  [ADR-0053](0053-rupture-targets-earthquake-prediction.md), which removed the banned-language gate
  (see the Supersession note at the end of this file). Retained as the record of a decision that
  was correct while the gate existed.
- **Date:** 2026-09-03 (UTC)

## Context

CLAUDE.md bans the forbidden verb and its derivatives, and says the allowlist may not be
extended without an ADR. That rule has now collided with something it was never meant to stop: the two ground-motion
papers rupture depends on have the banned word in their **published titles**.

- Boore, Stewart, Seyhan & Atkinson (2014), *Earthquake Spectra* 30(3), 1057–1085:
  "NGA-West2 Equations for Predicting PGA, PGV, and 5% Damped PSA for Shallow Crustal Earthquakes"
- Abrahamson, Gregor & Addo (2016), *Earthquake Spectra* 32(1), 23–44:
  "BC Hydro Ground Motion Prediction Equations for Subduction Earthquakes"

The risk engineer worked around this by abbreviating both titles and citing DOIs instead, and said
so. That is a correct response to the rule as written, and a bad outcome: a scientific repository
that cannot cite its sources by their real names has a gate that has stopped serving its purpose.

The gate exists so that **rupture** never claims to forecast individual earthquakes. Quoting the
title of somebody else's paper is not such a claim; it is the opposite of a claim, since a citation
attributes a statement to its author. The same reasoning already admits the glossary headings that
define what rupture is not, and the traditional expansion of the acronym GMPE.

## Decision

Add to `src/rupture/validation/banned_language_allowlist.txt` the exact fragments needed to cite
these two titles verbatim, and restore the verbatim titles in the code, data provenance and
`docs/RISK.md`.

The rule for future entries stays narrow: **a published title, quoted exactly, of a work rupture
cites.** Not a paraphrase, not a description of a capability, and never a sentence rupture asserts
in its own voice. Each entry names the work in a comment.

## Consequences

- rupture cites its sources by name, which is the minimum a reviewer expects.
- The allowlist grows by two entries, each traceable to a specific paper.
- The gate keeps its teeth where they matter: any *new* sentence that claims rupture forecasts
  individual earthquakes still fails, because an allowlisted fragment now exempts **only itself**.

## Correction (2026-09-03, same day)

The consequence above was **false when written**, and a review caught it. The scanner skipped the
*entire line* on which an allowlisted fragment appeared, so a claim could ride along beside a
permitted phrase. The reviewer demonstrated it: a markdown table row containing a permitted paper
title, followed on the same line by a sentence making a deterministic claim about a named city,
passed the gate. Citation tables are exactly where these titles live, and a table row is one line, so the
attack was not hypothetical.

This defect predated ADR-0034 — the single permitted sentence had the same effect — but ADR-0034
doubled the exposure while asserting it had not.

`scan_text` now removes each allowlisted fragment from the line and scans the remainder, so a
fragment exempts itself and nothing else. The four bypasses the reviewer constructed are all
caught, and legitimate citations still pass. The inline marker `# lang-gate: allow` deliberately
keeps whole-line semantics, because it exists for test strings that must spell out a violation.

Making the check strict immediately caught rupture's own documentation of the banned list in
`CLAUDE.md`, which had been riding on the loose behaviour. Those entries are now exact strings
rather than line prefixes. That is the gate working, and it is the argument for strictness: the
loose version was hiding something on the day it was written.

## Alternatives considered

- **Keep abbreviating titles and cite DOIs.** Rejected: it makes the bibliography wrong, it looks
  like evasion to a reviewer, and it would spread to every future citation.
- **Exempt whole files from the gate.** Rejected: far too broad; a bibliography file would become
  a place where claims could hide.


## Supersession (2026-09-04) — by [ADR-0053](0053-rupture-targets-earthquake-prediction.md)

The banned-language gate was removed when Rupture was re-aimed at earthquake prediction as an open
research target ([ADR-0053](0053-rupture-targets-earthquake-prediction.md) records the re-aim, what
was removed with the gate and what was deliberately kept), so the problem this ADR solved no longer
exists: published titles need no
allowlist because there is no list. The reasoning is kept because it was right about something that
outlived the gate — **a citation attributes a statement to its author and is not a claim in
Rupture's own voice** — and that distinction is now carried by CLAUDE.md § How Rupture writes about
results, which requires every cited work to be tagged with its evidence status and never to be
cited without its published rebuttals.
