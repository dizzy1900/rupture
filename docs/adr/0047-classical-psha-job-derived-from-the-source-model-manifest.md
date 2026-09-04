# ADR-0047: A classical PSHA job is derived from the source-model manifest, not written by hand

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Relates to:** ADR-0008 (source models per region), ADR-0011 (pinned image), ADR-0030 (runner
  design), ADR-0016 (job manifests)

## Context

D4 fetches an openly licensed OpenQuake source model (ESHM20 for `turkiye-eaf`) with provenance;
F0 runs a classical PSHA from it. The bridge between the two was
`infra/jobs/examples/turkiye-eaf-classical.json`, a `ClassicalPSHAJob` written before the fetching
adapter existed. It named `data/raw/oq_sources/eshm20/source_model_logic_tree.xml` and
`gmm_logic_tree.xml`; the adapter writes
`data/raw/eshm20/oq_computational/oq_configuration_eshm20_v12e_region_main/source_model_logic_tree_eshm20_model_v12e.xml`
and `gmpe_complete_logic_tree_5br.xml`. Its own description admitted the names were placeholders,
its region was a placeholder bounding box rather than the `turkiye-eaf` polygon, and `docs/HAZARD.md`
and `infra/jobs/README.md` repeated the wrong directory. `rupture hazard classical --job` on that
file would have failed at path resolution. ADR-0008 said the adapter would be exercised end to end
(demo + ESHM20); only the demo half was, and the ingested 40 MB was unusable without hand edits.

The general failure is not a typo. Two artefacts described the same files, one produced by code and
one maintained by hand, with nothing making them agree; the hand-maintained one went stale the
moment the adapter chose a different name, and no test could notice because the files are not in
the repository.

Separately, three `job.ini` keys that materially change a real run — `rupture_mesh_spacing`,
`width_of_mfd_bin`, `area_source_discretization` — were hard-coded defaults with no way to set
them, so an ESHM20 run could not be made coarse enough for a first pass.

## Decision

1. **One derived bridge.** `rupture.pipelines.hazard.eshm20_classical_job(region)` builds the
   `ClassicalPSHAJob` from `data/raw/eshm20/manifest.json` — the file the fetching adapter writes —
   taking both logic-tree paths, the pinned commit, the licence and the citation from it, and the
   calculation region from the `Region` record. There is no second place where an ESHM20 file name
   is written down, so there is nothing to drift. It raises rather than guessing when the region has
   no verified model (California, Nepal: ADR-0008), when nothing has been fetched, or when a file
   the manifest names is absent.

2. **`pipelines/hazard.py` is where the two adapter families meet.** The import-linter contract
   keeps `adapters.sources` and `adapters.hazard` independent of each other, which is right — a
   fetcher must not depend on an engine. The pipeline layer is the one place allowed to join them,
   and the bridge lives there for that reason rather than in either adapter.

3. **The calculation is cut to the region polygon, not its bounding box.** OpenQuake's `region` key
   takes an arbitrary simple polygon. A bounding box would compute hazard over sites the region
   record does not claim, and the region would then mean two different things in two places. This
   also settles ADR-0008's "stores the clip metadata for the EAF polygon": no clip is stored,
   because clipping an NRML source model is a modelling operation (sources outside the polygon
   contribute to hazard inside it) and the restriction belongs on the calculation, where it is
   derived from the region on every run.

4. **Inputs are checked before a container starts.** `missing_classical_inputs(job)` resolves the
   logic trees, the sites CSV and every file the source-model logic tree names in
   `<uncertaintyModel>`; `run_classical` refuses on a non-empty result. A stale path costs a
   millisecond instead of an image pull and an hour of staging.

5. **ERF discretisation and reference basin depths are settings of the runner**
   (`OpenQuakeDocker(erf=..., site=...)`), not fields of `ClassicalPSHAJob`. They trade accuracy
   against runtime for a given engine and machine rather than describing the hazard question, and
   the same job should be runnable coarsely for a first pass and finely for a published one.
   Whichever values are used appear in the staged `job.ini` and therefore inside `job_hash`.

6. **The classical path is proven against the engine, not against a fake.**
   `tests/integration/hazard/test_openquake_classical.py` runs GEM's own QA case
   `classical/case_01` through `ClassicalPSHAJob` → `job_builder` → the pinned container →
   `result_parser` and compares the PoEs with the baseline committed in `gem/oq-engine`. Before it,
   every classical calculation the container had ever run was the engine's own demo `job.ini`. Run
   here on 2026-09-04 under emulation: both exported curves are identical to GEM's baseline to the
   last digit. The one non-obvious detail is that the sites file must be written **headerless**
   (`lon,lat,depth`), because the engine drops the depth column when a `lon` header is present.

## Consequences

- ESHM20 is usable: the job resolves all 53 files it names (two logic trees plus the 51 source
  models the tree references), verified offline on a clone with the model fetched.
- The PSHA itself is **still not run** (ADR-0008's "if it fits the time budget"): ESHM20's full
  logic tree is hours of compute on an amd64 machine, and this host is arm64, where the pinned
  amd64 image runs under emulation. That remains a gap in `RELEASE_STATUS.md`, now a scheduling
  gap rather than a missing bridge.
- `infra/jobs/examples/turkiye-eaf-classical.json` and `infra/jobs/oq-classical.yaml` still carry
  the placeholder paths. They are owned elsewhere; the intended replacement is a file generated by
  `write_classical_job`, so the example stops being a hand-maintained duplicate.
- `OpenQuakeDocker(env=...)` passes `-e KEY=VALUE` to the container. The known use is
  `OQ_DISTRIBUTE=no`: under QEMU the engine hangs in its process pool while reading source models,
  and serial execution finishes the QA case in a minute, which is what makes the emulated path
  reproducible on an arm64 machine. Nothing is set by default.
- A fresh clone still cannot obtain the ESHM20 files: `manifest.json` is committed, the 40 MB of
  NRML is neither committed nor DVC-tracked. The manifest is therefore the re-fetch instruction and
  the integrity check, and `openquake_sources.model_present` is what callers branch on.

## Alternatives considered

- **Fix the example JSON's paths.** Rejected as the whole answer: it repairs this instance and
  leaves the mechanism that produced it — a hand-maintained copy of names the adapter chooses —
  in place for the next model.
- **Have the fetching adapter emit the job.** Rejected: it would make `adapters.sources` depend on
  the hazard port and put a calculation decision (grid spacing, IMTs, investigation time) inside a
  downloader.
- **Put ERF settings on `ClassicalPSHAJob`.** Rejected: `ports/` describes the hazard question, and
  a stored job would then encode the machine it was first run on. They are runner settings, visible
  in the rendered ini either way.
