# ADR-0034: The banned-language allowlist admits published paper titles

- **Status:** accepted
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
  individual earthquakes still fails, because these entries match only the exact published titles.

## Alternatives considered

- **Keep abbreviating titles and cite DOIs.** Rejected: it makes the bibliography wrong, it looks
  like evasion to a reviewer, and it would spread to every future citation.
- **Exempt whole files from the gate.** Rejected: far too broad; a bibliography file would become
  a place where claims could hide.
