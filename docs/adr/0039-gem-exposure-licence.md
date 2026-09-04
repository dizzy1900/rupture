# ADR-0039: GEM's global exposure and vulnerability models are not openly licensed

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

The brief asked for exposure builders from "(a) GEM global exposure **where openly licensed**".
That parenthesis is the whole decision, and it had not been answered anywhere in the repository:
nothing in `src/`, `docs/`, `contracts/` or `RELEASE_STATUS.md` mentioned GEM exposure at all, so a
reader could not tell whether it had been assessed and refused or simply forgotten.

## Decision

**The licence was read, and it fails.** Both

- GEM's Global Exposure Model — `github.com/gem/global_exposure_model`, and
- GEM's Global Vulnerability Model — `github.com/gem/global_vulnerability_model`

are released under **Creative Commons Attribution-NonCommercial-ShareAlike 4.0** (read from each
repository's `LICENSE.txt` on 2026-09-03; the exposure repository's README carries the same badge).
That is not an open licence under the Open Definition or the OSI: the NonCommercial term restricts
a field of use, and ShareAlike would propagate to derived works. rupture is Apache-2.0.

Therefore:

1. **rupture redistributes none of it.** No GEM exposure or vulnerability data is committed to this
   tree — no fixture, no slice, no derived table. A unit test asserts the absence rather than
   trusting the rule. The consequence is accepted: there is no offline GEM fixture, so
   `validate-risk` does not exercise this adapter against real data.
2. **rupture ships the adapter anyway.** `rupture.adapters.exposure.gem_global.GemExposureSource`
   implements the `ExposureSource` port over the OpenQuake exposure CSV format that GEM
   distributes the disaggregated model in. It reads a copy the consumer already holds under GEM's
   own terms; it never fetches and never caches. A consumer who has done the licence request
   should not also have to write a loader.
3. **`fetch_summary` covers the public tables only**, prints the attribution and licence before it
   writes anything, and writes outside the repository. GEM publishes only summary tables
   (`Exposure_Summary_Adm0/Adm1/Taxonomy.csv`) publicly; the spatially disaggregated model is on
   licence request. The summaries carry no coordinates, so they can be reported but cannot become
   a portfolio, and `read_summary` refuses to pretend otherwise.

### The second half of the requirement is declined

Pairing GEM exposure with a building-class fragility set needs an openly licensed one, and this
pass has none:

- GEM's own vulnerability database is CC BY-NC-SA — the same problem;
- HAZUS 5.1 is a US Government work and does publish general building-stock fragility, but those
  tables are **not** among the blocks committed under `tests/fixtures/risk/vulnerability/hazus51/`,
  and transcribing them from memory rather than from the document is precisely the fabrication this
  project refuses.

So a GEM portfolio imported through this adapter is reported **wholly unmodelled**, asset by asset,
with the reason. That is the honest outcome of an exposure source with no matching vulnerability
model, and it is what the existing coverage machinery already does for the corridor's bridge,
border post and settlements.

## Consequences

- The requirement is answered rather than silent: the licence was assessed, the assessment is
  recorded here and in `docs/RISK.md`, and the refusal to redistribute is asserted by a test.
- rupture still cannot price a settlement, a region or a general building portfolio. The blocking
  item is a **sourced building-class fragility set**, not the exposure; adding the HAZUS 5.1
  building tables as committed fixtures (the same treatment Tables 7-9, 8-29, 8-31, 8-32, 11-10 and
  11-18 already have) would unblock it, and is recorded as an open gap.
- A commercial consumer of rupture cannot use GEM's model through this adapter either. That is
  GEM's licence, not rupture's choice, and the adapter's docstring says so.

## Alternatives considered

- **Commit a small GEM slice as a fixture and rely on NonCommercial being satisfied for research
  use.** Rejected: rupture is a redistributor here, not a user, and the ShareAlike term would
  reach the repository. A licence that "probably applies" is not a licence position.
- **Say nothing, as before.** Rejected. A requirement that was assessed and refused, and a
  requirement that was forgotten, look identical from outside unless the refusal is written down.
- **Invent replacement costs or fragilities for GEM taxonomies to make the adapter produce a
  number.** Rejected outright.
