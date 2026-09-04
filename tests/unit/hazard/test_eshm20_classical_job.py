"""The bridge from a fetched source model to a runnable classical PSHA job (ADR-0008).

The failure this guards against is the one that actually happened: a hand-written job JSON naming
guessed ESHM20 file names in a directory the fetching adapter never wrote to, repeated in two
documents, discovered only when someone tried to run it. ``eshm20_classical_job`` derives both
logic-tree paths from ``data/raw/eshm20/manifest.json`` — the file the adapter itself writes — so
the two cannot drift apart.

Offline. The ESHM20 model (40 MB) is not committed, so the structural tests build a manifest and
two NRML stubs in ``tmp_path``; the one test that needs the real thing skips with a printed reason
when ``data/raw/eshm20`` has not been fetched into this clone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rupture.adapters.hazard import job_builder
from rupture.adapters.sources import openquake_sources
from rupture.domain import Region
from rupture.pipelines import hazard as pipeline

REPO_ROOT = Path(__file__).resolve().parents[3]

NRML_LOGIC_TREE = """<?xml version="1.0" encoding="UTF-8"?>
<nrml xmlns="http://openquake.org/xmlns/nrml/0.4">
  <logicTree logicTreeID="lt1">
    <logicTreeBranchingLevel branchingLevelID="bl1">
      <logicTreeBranchSet uncertaintyType="sourceModel" branchSetID="bs1">
        <logicTreeBranch branchID="b1">
          <uncertaintyModel>source_models/model_a.xml</uncertaintyModel>
          <uncertaintyWeight>1.0</uncertaintyWeight>
        </logicTreeBranch>
      </logicTreeBranchSet>
    </logicTreeBranchingLevel>
  </logicTree>
</nrml>
"""
NRML_GSIM_TREE = """<?xml version="1.0" encoding="UTF-8"?>
<nrml xmlns="http://openquake.org/xmlns/nrml/0.4">
  <logicTree logicTreeID="lt1"/>
</nrml>
"""


@pytest.fixture
def eaf_region() -> Region:
    """The real ``turkiye-eaf`` record: the polygon the job must be cut to."""
    return Region.model_validate(
        json.loads((REPO_ROOT / "data" / "regions" / "turkiye-eaf" / "region.json").read_text())
    )


@pytest.fixture
def fake_raw_dir(tmp_path: Path) -> Path:
    """A ``data/raw/eshm20``-shaped tree: the manifest layout with two-line NRML stubs.

    Not ESHM20 data and never presented as such — the point is only that the paths in the manifest
    are the paths the job builder resolves.
    """
    raw = tmp_path / "eshm20"
    model_dir = raw / openquake_sources.MAIN_REGION_DIR
    (model_dir / "source_models").mkdir(parents=True)
    (raw / openquake_sources.SOURCE_MODEL_LOGIC_TREE).write_text(NRML_LOGIC_TREE)
    (raw / openquake_sources.GSIM_LOGIC_TREE).write_text(NRML_GSIM_TREE)
    (model_dir / "source_models" / "model_a.xml").write_text(NRML_GSIM_TREE)
    (raw / "manifest.json").write_text(
        json.dumps(
            {
                "source": openquake_sources.SOURCE_ID,
                "repository": openquake_sources.PROJECT_URL,
                "commit": "0" * 40,
                "licence": openquake_sources.LICENCE_SPDX,
                "source_model_logic_tree": openquake_sources.SOURCE_MODEL_LOGIC_TREE,
                "gsim_logic_tree": openquake_sources.GSIM_LOGIC_TREE,
                "files": [],
            }
        )
    )
    return raw


def test_the_job_takes_both_logic_trees_from_the_manifest(
    eaf_region: Region, fake_raw_dir: Path
) -> None:
    job = pipeline.eshm20_classical_job(eaf_region, raw_dir=fake_raw_dir)
    manifest = openquake_sources.read_manifest(fake_raw_dir)
    assert job.source_model_logic_tree == fake_raw_dir / manifest["source_model_logic_tree"]
    assert job.gsim_logic_tree == fake_raw_dir / manifest["gsim_logic_tree"]
    assert pipeline.missing_classical_inputs(job) == []


def test_the_job_covers_the_region_polygon_not_a_bounding_box(
    eaf_region: Region, fake_raw_dir: Path
) -> None:
    job = pipeline.eshm20_classical_job(eaf_region, raw_dir=fake_raw_dir)
    assert job.region_wkt is not None
    ring = job_builder.wkt_polygon_to_region(job.region_wkt)
    vertices = [tuple(float(v) for v in pair.split()) for pair in ring.split(",")]
    assert vertices == [(lon, lat) for lon, lat in eaf_region.polygon]
    assert len(vertices) > 4, "a bounding box would have four vertices; the EAF octagon has eight"


def test_a_rendered_job_ini_names_the_staged_file_names(
    eaf_region: Region, fake_raw_dir: Path
) -> None:
    job = pipeline.eshm20_classical_job(eaf_region, raw_dir=fake_raw_dir)
    ini = job_builder.classical_job_ini(job)
    assert f"source_model_logic_tree_file = {job.source_model_logic_tree.name}" in ini
    assert f"gsim_logic_tree_file = {job.gsim_logic_tree.name}" in ini
    assert "calculation_mode = classical" in ini


def test_a_missing_source_model_is_reported_before_any_container_starts(
    eaf_region: Region, fake_raw_dir: Path
) -> None:
    job = pipeline.eshm20_classical_job(eaf_region, raw_dir=fake_raw_dir)
    (fake_raw_dir / openquake_sources.MAIN_REGION_DIR / "source_models" / "model_a.xml").unlink()
    missing = pipeline.missing_classical_inputs(job)
    assert [Path(m).name for m in missing] == ["model_a.xml"]
    with pytest.raises(FileNotFoundError, match=r"model_a\.xml"):
        pipeline.run_classical(_NeverCalled(), job, fake_raw_dir / "work")


def test_regions_with_no_verified_model_refuse_rather_than_guess(fake_raw_dir: Path) -> None:
    for region_id in ("california", "nepal-himalaya"):
        region = Region.model_validate(
            json.loads((REPO_ROOT / "data" / "regions" / region_id / "region.json").read_text())
        )
        with pytest.raises(ValueError, match="no OpenQuake source model"):
            pipeline.eshm20_classical_job(region, raw_dir=fake_raw_dir)


def test_an_unfetched_model_says_so(eaf_region: Region, tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"manifest\.json"):
        pipeline.eshm20_classical_job(eaf_region, raw_dir=tmp_path / "nothing-here")


def test_written_job_round_trips_through_the_cli_loader(
    eaf_region: Region, fake_raw_dir: Path, tmp_path: Path
) -> None:
    job = pipeline.eshm20_classical_job(eaf_region, raw_dir=fake_raw_dir)
    path = pipeline.write_classical_job(job, tmp_path / "jobs" / pipeline.JOB_FILE)
    reloaded = pipeline.load_classical_job(path)
    assert reloaded.source_model_logic_tree.resolve() == job.source_model_logic_tree.resolve()
    assert reloaded.gsim_logic_tree.resolve() == job.gsim_logic_tree.resolve()
    assert reloaded.region_wkt == job.region_wkt
    assert pipeline.missing_classical_inputs(reloaded) == []


def test_the_real_fetched_model_resolves_every_file_it_names(eaf_region: Region) -> None:
    """When ESHM20 is present, the job must be runnable as it stands: no path needs editing.

    A committed ``manifest.json`` alone is not enough — the 40 MB of NRML is neither committed nor
    DVC-tracked — so this skips with the re-fetch instruction rather than passing on nothing.
    """
    raw = REPO_ROOT / openquake_sources.DEFAULT_RAW_DIR
    if not openquake_sources.model_present(raw):
        pytest.skip(
            f"ESHM20 model files are not in this clone ({raw}); manifest.json is committed but "
            "the 40 MB of NRML is neither committed nor DVC-tracked, so re-run "
            "openquake_sources.fetch_eshm20() (network) to exercise this test"
        )
    job = pipeline.eshm20_classical_job(eaf_region, raw_dir=raw)
    assert pipeline.missing_classical_inputs(job) == []
    named = job_builder.referenced_source_models(job.source_model_logic_tree.read_text())
    assert named, "the ESHM20 source-model logic tree names source-model files"


class _NeverCalled:
    """A ``HazardEngine`` that fails the test if the pre-flight check lets a run through."""

    engine_id = "never"
    engine_version = "0"

    def available(self) -> tuple[bool, str]:  # pragma: no cover - not reached
        return False, "never"

    def run_classical(self, job: object, work_dir: Path) -> object:  # pragma: no cover
        raise AssertionError("run_classical was reached despite a missing input")

    def run_scenario(self, job: object, work_dir: Path) -> Path:  # pragma: no cover
        raise AssertionError("run_scenario is not used here")
