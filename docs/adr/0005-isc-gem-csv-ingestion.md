# ADR-0005 — ISC-GEM CSV ingestion via a manual, form-gated download

- **Status:** accepted
- **Date:** 2026-09-03

## Context

The ISC-GEM Global Instrumental Earthquake Catalogue (Storchak et al. 2013, 2015; Di Giacomo et
al. 2015) is the highest-quality homogeneous Mw source for large events since 1900 and is the top
of rupture's merge precedence. It is distributed as a CSV from a download page that requires a
form submission; there is no FDSN or stable direct-download URL, and scripting the form would
bypass the terms-of-use acknowledgement the page asks for.

## Decision

- The user downloads the ISC-GEM CSV manually from the ISC-GEM download page and sets
  `RUPTURE_ISC_GEM_CSV` (documented in `docs/CREDENTIALS.md` and `docs/DATA_SOURCES.md`).
- `adapters/catalogs/isc_gem.py` parses the local CSV, records provenance (`source=isc-gem`,
  download-page URL, `retrieved_at`, `sha256` of the file, catalogue version from the header,
  licence as stated on the page) and fails loudly with the variable name if the file is absent
  or does not parse.
- A small real slice is committed as a fixture so the parser is exercised offline.
- Online catalogue builds proceed without ISC-GEM if the variable is unset, but the
  homogenisation log and `RELEASE_STATUS.md` record that ISC-GEM was not included, and the merge
  precedence falls through to GCMT.

## Consequences

- One manual step in the full online build; documented and recorded, not hidden.
- Reproducibility is preserved by the `sha256` and version string in provenance.
- If ISC-GEM adds a scriptable endpoint, a new ADR can supersede this one.

## Alternatives considered

- **Scrape the form with a scripted POST.** Rejected: fragile and sidesteps the acknowledgement.
- **Commit the full ISC-GEM CSV.** Rejected: licence terms and repository size; only a fixture
  slice with provenance is committed.
- **Skip ISC-GEM.** Rejected: it is the best available Mw for the pre-GCMT era and for
  completeness assessment.
