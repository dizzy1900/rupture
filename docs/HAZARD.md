# Hazard (F0): the OpenQuake adapter

rupture does not predict earthquakes. This document describes how rupture computes long-term
probabilities of exceedance of ground motion with the OpenQuake engine, what has been verified
about the pinned image and what is still assumed, and what has and has not been run.
Decisions: ADR-0008 (source models per region), ADR-0011 (pinned image), ADR-0030 (runner design).

## Status (2026-09-03)

| Piece | State |
|---|---|
| `adapters/hazard/job_builder.py` — `ClassicalPSHAJob` / `ScenarioGroundMotionJob` → `job.ini` | working; unit-tested against the engine's own demo and QA `job.ini` keys |
| `adapters/hazard/result_parser.py` — `hazard_curve-*.csv` → `HazardCurveSet` | working; unit-tested on real QA expected outputs from `gem/oq-engine` (`engine-3.26`), contract-validated |
| `adapters/hazard/openquake_docker.py` — `OpenQuakeDocker` (`HazardEngine`) | working offline with an injected fake `docker`; **not yet run against a real container** (no Docker on the development machine) |
| `run_bundled_demo`, `validate-hazard`, `rupture hazard demo` | code complete; skip with reason here; proving ground is CI job `hazard-integration` (runs on pushes to `main` and manual dispatch). Until that job has run green, treat the container path as unverified |
| `run_scenario` | implemented from the manual; no test or CI run exercises it |
| `rupture hazard classical` + `infra/jobs/examples/turkiye-eaf-classical.json` | code complete; the ESHM20 job has **not** been run and its input file names are unconfirmed |
| California, Nepal PSHA | gaps (ADR-0008): no openly licensed NRML model verified |

## Design

```
ClassicalPSHAJob ──job_builder──▶ work_dir/job.ini + copied inputs
                                        │  docker run --rm -v work_dir:/work openquake/engine:3.26.2 \
                                        │    bash -c 'set -e; umask 000; mkdir -p /work/out;
                                        │             oq engine --run /work/job.ini;
                                        │             oq export hcurves -e csv -d /work/out'
                                        ▼
                          work_dir/out/hazard_curve-mean-<IMT>_<calc>.csv, work_dir/oq.log
                                        │  result_parser
                                        ▼
                                  HazardCurveSet (contracts/hazard-curve-set.v0.json)
```

- The adapter talks to Docker only through the `docker` CLI (`subprocess`), never through the
  Docker SDK, and never imports `openquake.*`.
- Run and export happen inside **one** container because `--rm` discards the engine's datastore.
- `HazardCurveSet.job_hash` = sha256 over `job.ini` and every staged input file (name + bytes,
  sorted); `provenance.sha256` = sha256 over the exported CSV text; `provenance.source_url` =
  `docker://openquake/engine@sha256:<digest>` (the local image's repo digest);
  `provenance.licence` = `AGPL-3.0 (engine); inputs per source model`; `engine_version` is what
  the CSV header's `generated_by` reports (so a fixture produced by 3.20 says 3.20).
- `available()` → `(False, reason)` when `docker` is not on `PATH` or `docker info` fails. Every
  entry point prints that reason and does not pretend to run:
  `make validate-hazard` → `SKIPPED` (non-blocking), `rupture hazard demo|classical|check` →
  exit 3, the integration test → `pytest.skip`.

### `job.ini` keys written

Classical (`calculation_mode = classical`): `[general] description, calculation_mode,
random_seed`; `[geometry] sites_csv` **or** `region` + `region_grid_spacing` (km; the WKT polygon
of the job is converted to OpenQuake's open `lon lat, ...` ring); `[logic_tree]
number_of_logic_tree_samples`; `[erf] rupture_mesh_spacing, width_of_mfd_bin,
area_source_discretization` (defaults 5.0 / 0.1 / 10.0 — not fields of `ClassicalPSHAJob`;
`job_builder.ErfSettings` overrides them); `[site_params] reference_vs30_type = measured,
reference_vs30_value, reference_depth_to_2pt5km_per_sec = 5.0, reference_depth_to_1pt0km_per_sec
= 100.0` (depths as in the bundled demo; `SiteDepthSettings` overrides); `[calculation]
source_model_logic_tree_file, gsim_logic_tree_file, investigation_time,
intensity_measure_types_and_levels` (JSON dict), `truncation_level, maximum_distance`;
`[output] export_dir = out, mean = true, hazard_maps = false, uniform_hazard_spectra = false`.

Scenario (`calculation_mode = scenario`): `[geometry] sites_csv`; `[rupture] rupture_model_file,
rupture_mesh_spacing = 2.0`; `[site_params]` as above; `[calculation] intensity_measure_types,
gsim, number_of_ground_motion_fields, truncation_level, maximum_distance`; export key
`gmf_data`.

The engine flattens all sections into one dictionary, so section names are the manual's
conventions and nothing more. Input files are referenced by bare name and copied next to
`job.ini`; the source-model files a source-model logic tree names in `<uncertaintyModel>` are
copied too (relative to the logic tree).

## Verified vs assumed about `openquake/engine:3.26.2`

Verified on 2026-09-03 by reading the `engine-3.26` branch of `gem/oq-engine` and the manual
(no container was run):

| Fact | Source |
|---|---|
| Tag `3.26.2` exists on Docker Hub (pushed 2026-07-23, amd64, ~0.98 GB, digest `sha256:e932bf70…`) | Docker Hub API |
| Base `python:3.12.6-slim`; user `openquake` uid 1000; `HOME=/home/openquake`; venv `/opt/openquake` on `PATH`; `WORKDIR $HOME`; `mkdir oqdata` | `docker/Dockerfile.engine` |
| `ENTRYPOINT ["./oq-start.sh"]` (relative path), default `CMD` starts the WebUI | `docker/Dockerfile.engine` |
| `oq-start.sh` runs `oq dbserver start &`, waits for TCP 1908, then `exec "$@"` when no TTY | `docker/scripts/oq-start.sh` |
| `oq engine --run <ini>` runs a calculation; `oq engine --lo`, `--export-outputs` exist | `openquake/commands/engine.py`, manual |
| `oq export <key> [calc_id] -e csv -d <dir>`; `calc_id` defaults to `-1` = the latest job | `openquake/commands/export.py`, `openquake/server/db/actions.py::get_job` |
| Hazard curves export as `hazard_curve-<kind>-<IMT>_<calc>.csv` with the `#` metadata header shown above; `kind` is `mean` by default (`mean = true`) | `openquake/calculators/export/hazard.py`, `oqvalidation.py`, QA expected files |
| Default `openquake.cfg`: `oq_distribute = processpool`, dbserver file `~/oqdata/db.sqlite3`, port 1908 | `openquake/engine/openquake.cfg` |
| Demos are installed as setuptools `data_files` with relative target dirs (`demos/hazard/...`) | `setup.py`, `MANIFEST.in` |
| Demo `AreaSourceClassicalPSHA`: 2112 sites, 1 realisation, `BooreAtkinson2008`, `investigation_time = 50.0`, ~2 min stated runtime | `demos/hazard/AreaSourceClassicalPSHA/{job.ini,README.txt}` (copied to `tests/fixtures/hazard/`) |

Assumed (stated in code, overridable):

| Assumption | Where it bites | Mitigation |
|---|---|---|
| Demos live at `/opt/openquake/demos/<demo>` (relative `data_files` land under the venv prefix) | `run_bundled_demo` | `RUPTURE_OPENQUAKE_DEMOS_DIR`; `find / -path '*/demos/<demo>/job.ini'` fallback in the same container |
| A `chmod 777` work dir + `umask 000` is enough for uid 1000 to write and the host user to clean up | every run | logged; CI uploads the work dir on failure |
| The whole demo (2112 sites × 8 IMTs) finishes well inside 25 min on a 2-vCPU runner | CI | per-step `timeout-minutes`, adapter `run_timeout_s`; if too slow, switch `DEFAULT_DEMO` to a smaller demo by ADR |
| `oq engine --run` returns non-zero when the calculation fails | error handling | the export step then finds no CSV and fails loudly anyway |

## Running the demo locally (once Docker exists)

```bash
docker pull openquake/engine:3.26.2
uv run rupture hazard check                 # image + daemon status
uv run rupture hazard demo --work-dir /tmp/oq-demo
make validate-hazard                        # the gate; PASSED/FAILED with findings
uv run pytest tests/integration/hazard -m integration -ra
```

The work directory holds `job.ini`, the demo inputs, `out/hazard_curve-mean-*.csv`,
`hazard-curve-set.json` and `oq.log`. `RUPTURE_HAZARD_WORK_DIR` makes the gate keep its work
directory (CI uses this for artifact upload).

## A coarse classical PSHA for `turkiye-eaf` from ESHM20 — what it needs (not run)

`infra/jobs/examples/turkiye-eaf-classical.json` is the `ClassicalPSHAJob`:
a 0.2° grid (`region_grid_spacing_km = 20.0`, about 0.2° at 36–40° N) over the bounding box
`POLYGON((35.5 35.5, 42.0 35.5, 42.0 40.0, 35.5 40.0, 35.5 35.5))` — an approximation of the
East Anatolian Fault zone from Karlıova to the Hatay region, to be replaced by the bounding box of
the `turkiye-eaf` polygon in `data/regions/` once merged — `investigation_time_years = 50`,
PGA / SA(0.3) / SA(1.0), `maximum_distance_km = 300`, full logic-tree enumeration.

To run it:

1. `adapters/sources/openquake_sources.py` (catalog-engineer, ADR-0008) fetches the ESHM20
   source model and logic-tree NRML files under `data/raw/oq_sources/eshm20/` with provenance.
   The example points at `source_model_logic_tree.xml` and `gmm_logic_tree.xml` in that
   directory; **these names are placeholders** until the adapter's output is known — set them to
   the real file names (the ESHM20 release ships one source-model logic tree and one GMM logic
   tree, each referencing further XML files that the adapter copies by their relative names).
2. `uv run rupture hazard classical --job infra/jobs/examples/turkiye-eaf-classical.json
   --work-dir reports/hazard/turkiye-eaf` on a machine with Docker. ESHM20's full logic tree is
   large; expect hours, not minutes, at this resolution and consider
   `number_of_logic_tree_samples > 0` for a first pass (an ADR if it becomes the published run).
3. The result is `reports/hazard/turkiye-eaf/hazard-curve-set.json` conforming to
   `contracts/hazard-curve-set.v0.json`.

This has **not** been run in Prompt 1. Nepal and California have no openly licensed NRML model
(ADR-0008); no PSHA is produced for them and no substitute model is used.

## Fixtures

`tests/fixtures/hazard/` holds verbatim copies from `gem/oq-engine` (`engine-3.26`), each
directory with a `provenance.json` (URL, `retrieved_at`, sha256 per file, licence
AGPL-3.0-or-later): `qa_classical_case_01` (job + inputs + expected PGA and SA(0.1) curves),
`qa_classical_case_02` (job + expected PGA curve), `demo_AreaSourceClassicalPSHA` (the demo's
inputs; no outputs, because the demo was not run here). Nothing in these directories is edited by
hand.
