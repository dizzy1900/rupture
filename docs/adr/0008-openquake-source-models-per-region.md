# ADR-0008 — OpenQuake source models per region: ESHM20 for Türkiye; California and Nepal gaps

- **Status:** accepted
- **Date:** 2026-09-03

## Context

F0 (long-term hazard) needs an OpenQuake source model and GSIM logic tree per test region. The
brief asks for ingestion "where an openly licensed model exists; otherwise an ADR documenting the
gap and the plan." Recon on 2026-09-03 found:

| Region | Finding |
|---|---|
| `turkiye-eaf` | The 2020 European Seismic Hazard Model (ESHM20; Danciu et al. 2021, 2024) covers Türkiye including the East Anatolian Fault, is published on the EFEHR GitLab in OpenQuake (NRML) format under an open licence. |
| `california` | The USGS National Seismic Hazard Model is public domain, but distributed in the `nshmp` format used by the USGS `nshmp-haz` code, not NRML. No openly licensed NRML model for California was verified. |
| `nepal-himalaya` | No openly licensed OpenQuake model was found. The GEM global hazard mosaic covers the region but its regional models are not all openly licensed for redistribution. |

## Decision

- **`turkiye-eaf`**: `adapters/sources/openquake_sources.py` fetches the ESHM20 source model and
  logic-tree files from the EFEHR repository (pinned commit), records provenance (`source=eshm20`,
  URL and commit, `retrieved_at`, `sha256` per file, licence as stated in the repository's licence
  file), and stores the clip metadata for the EAF polygon. A coarse classical PSHA for this
  region runs through the OpenQuake adapter if it fits the time budget; otherwise the ledger says
  it did not run.
- **`california`**: recorded as a **gap**. Plan: convert the public-domain USGS NSHM to NRML with
  GEM's `oq-mbtk` tooling (future work, Prompt 2 or later); until then no California PSHA is
  produced and `RELEASE_STATUS.md` says so.
- **`nepal-himalaya`**: recorded as a **gap**. Plan: (a) watch the licensing of the GEM mosaic
  models covering the Himalaya; (b) if none becomes openly redistributable, consider building a
  coarse area/fault source model from the GEM Global Active Faults (ADR-0007) and the homogenised
  catalogue using `oq-mbtk`, with the b-value and Mc from `rupture catalog build`. Either route is
  a new ADR. Until then no Nepal PSHA is produced.
- No substitute (e.g. a hand-written point source) is ever used in place of a real model; the
  adapter's demo path uses OpenQuake's own bundled demos, which are labelled as demos.

## Consequences

- F0 is available for one of three regions in Prompt 1; the other two are honest gaps in the
  ledger, as the brief anticipates.
- The OpenQuake adapter is exercised end to end (demo + ESHM20 clip), so adding a model later is
  data, not code.
- California hazard through OpenQuake depends on a format conversion nobody has scheduled yet.

## Alternatives considered

- **Run the USGS NSHM through `nshmp-haz` instead of OpenQuake.** Rejected for now: a second
  hazard engine and adapter for one region; revisit if the NRML conversion proves impractical.
- **Use a non-open regional model under a research licence.** Rejected: outputs could not be
  redistributed, and the repository is public.
- **Author a Nepal source model by hand now.** Rejected: fabricating a source model is exactly
  the kind of unprovenanced input the non-negotiables forbid; if built, it is built from GAF and
  the catalogue with recorded methods.
