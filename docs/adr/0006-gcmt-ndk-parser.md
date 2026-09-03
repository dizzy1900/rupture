# ADR-0006 — In-house GCMT NDK parser

- **Status:** accepted
- **Date:** 2026-09-03

## Context

The Global CMT catalogue (Ekström, Nettles & Dziewoński 2012) supplies authoritative Mw, centroid
locations and moment tensors from 1976. It is distributed as NDK files: a fixed-width text format
with five lines per event, documented by the project. The full 1976–2020 file is about 23 MB; later
months are separate "quick" files. obspy can read NDK into QuakeML `Catalog` objects, but that
path is heavyweight for what rupture needs (Mw, centroid time and location, hypocentre, nodal
planes, event name) and buries the fields rupture wants in a generic event model.

## Decision

- `adapters/catalogs/gcmt.py` implements a small in-house NDK parser (five lines per record,
  fixed columns per the GCMT format description) that yields `Event` records with `magnitude_type
  = Mw`, centroid and hypocentre, moment tensor components and nodal planes, and GCMT event name.
- Provenance per file: `source=gcmt`, file URL, `retrieved_at`, `sha256`, licence as stated by
  the project, adapter version.
- The parser is tested against a committed real NDK slice (Gorkha 2015 window) and against
  obspy's NDK reader on the same slice as a cross-check in an integration test.
- GCMT Mw is authoritative in the merge precedence for magnitude (below ISC-GEM); GCMT centroid
  location is not used for hypocentre position unless no other source has one.

## Consequences

- A few hundred lines of well-specified parsing code that rupture owns and can type strictly.
- No dependency on obspy's NDK plugin behaviour or its QuakeML mapping.
- Format changes upstream (rare) are a local fix.

## Alternatives considered

- **obspy `read_events(format="NDK")`.** Rejected for the main path: generic QuakeML model,
  slower, and hides the fields; kept as a cross-check.
- **Query GCMT through a web search form.** Rejected: NDK files are the published bulk format.
