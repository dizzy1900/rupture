# ADR-0033: GSIM coefficient provenance and the AGPL question

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

The `native_gsim` adapter (ADR-0020) needs the coefficient tables of the GSIMs it evaluates.
They are extracted verbatim from the `gem/oq-engine` source at tag `engine-3.26` by a refresh
script and stored under `src/rupture/adapters/groundmotion/data/` with a `provenance.json`. They
are never hand-typed, because a hand-typed coefficient table is a transcription error waiting to
become a loss number.

oq-engine is **AGPL-3.0-or-later**. rupture is **Apache-2.0**. The risk engineer flagged the
tension rather than resolving it, which was the right call. The same question already applies to
the OpenQuake QA fixtures committed in Prompt 1 and to the GSIM verification tables.

## Decision

rupture's position, recorded so a reviewer can judge it rather than discover it:

1. **What is used is numeric fact, not code.** The coefficients were first published in the
   journal articles — Boore, Stewart, Seyhan & Atkinson (2014), doi:10.1193/070113EQS184M, and
   Abrahamson, Gregor & Addo (2016), doi:10.1193/051712EQS188MR. The papers are the source of
   record; oq-engine is the machine-readable transcription rupture happened to read.
2. **rupture ships no oq-engine code**, links against none, and imports none. It ships numeric
   tables and its own independent implementation of the equations.
3. **Attribution is explicit.** Every extracted file records the upstream repository, tag, URL,
   sha256 and `AGPL-3.0-or-later (oq-engine transcription)` in its provenance, and `docs/RISK.md`
   names GEM. Attribution is given whether or not it is legally required.
4. **The re-derivation path is documented.** `tests/fixtures/risk/gsim/refresh_coefficients.py`
   records exactly what was extracted from where, so a maintainer who wants a clean-room table can
   replace the source with the papers without touching the implementation.
5. **This is an engineering position, not legal advice.** A maintainer intending commercial
   redistribution should take their own advice. The conservative alternative — transcribe from the
   papers — is available and costs a day; it was not taken because the papers are paywalled and a
   hand transcription is less trustworthy than an automated extraction that is verified against
   the reference implementation's own test vectors.

## Consequences

- A downstream user with a strict AGPL policy has everything needed to assess and, if they choose,
  replace the tables.
- If GEM objects, the fix is bounded and local: replace three data files and their provenance.
- The verification tables under `tests/fixtures/risk/gsim/` and the Prompt 1 OpenQuake QA fixtures
  are covered by the same reasoning.

## Alternatives considered

- **Hand-transcribe from the papers.** Rejected for now: paywalled, and error-prone in exactly the
  way that matters. Recorded as the mitigation if the position is ever challenged.
- **Fetch coefficients at runtime instead of committing them.** Rejected: it breaks the offline
  convention and makes a loss number depend on a network fetch.
- **Relicense rupture as AGPL.** Rejected: the brief specifies Apache-2.0 and the question does not
  warrant it, since no AGPL code is used.
