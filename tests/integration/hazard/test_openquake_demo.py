"""Runs the OpenQuake bundled demo in the pinned image. Needs Docker; opt-in (-m integration).

CI job ``hazard-integration`` runs this on ubuntu-latest. Locally it skips with the reason from
``OpenQuakeDocker.available()`` when Docker is absent.
"""

from __future__ import annotations

import os
from pathlib import Path

import jsonschema
import pytest

from rupture.adapters.hazard import DEFAULT_DEMO, OpenQuakeDocker
from rupture.adapters.hazard.result_parser import check_curve_set, parse_job_ini
from rupture.domain import HazardCurveSet, contracts
from rupture.pipelines import hazard as pipeline

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> OpenQuakeDocker:
    eng = OpenQuakeDocker(run_timeout_s=2400.0)
    ok, reason = eng.available()
    if not ok:
        pytest.skip(f"Docker not available: {reason}")
    eng.ensure_image()
    return eng


@pytest.fixture(scope="module")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    keep = os.environ.get("RUPTURE_HAZARD_WORK_DIR")
    if keep:
        path = Path(keep) / "integration-demo"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return tmp_path_factory.mktemp("oq-demo")


@pytest.fixture(scope="module")
def curve_set(engine: OpenQuakeDocker, demo_dir: Path) -> HazardCurveSet:
    return pipeline.run_demo(engine, demo_dir, DEFAULT_DEMO)


def test_demo_produces_a_hazard_curve_set(curve_set: HazardCurveSet, demo_dir: Path) -> None:
    assert curve_set.engine == "openquake.engine"
    assert curve_set.engine_version.startswith("3.26"), curve_set.engine_version
    assert curve_set.realisation == "mean"
    assert curve_set.investigation_time_years == 50.0, "the demo job.ini says 50 years"
    sites = {(c.site_longitude, c.site_latitude) for c in curve_set.curves}
    assert len(sites) >= 1
    assert "PGA" in {c.imt for c in curve_set.curves}
    assert (demo_dir / "oq.log").is_file()
    assert (demo_dir / pipeline.CURVE_SET_FILE).is_file()


def test_demo_curves_are_well_formed_and_match_the_job(
    curve_set: HazardCurveSet, demo_dir: Path
) -> None:
    expected = float(parse_job_ini((demo_dir / "job.ini").read_text())["investigation_time"])
    assert check_curve_set(curve_set, expected_investigation_time=expected) == []
    jsonschema.validate(
        curve_set.model_dump(mode="json"), contracts.schema_for("hazard-curve-set.v0.json")
    )


def test_provenance_names_the_pinned_image(
    curve_set: HazardCurveSet, engine: OpenQuakeDocker
) -> None:
    assert curve_set.provenance.source == "openquake.engine"
    assert curve_set.provenance.source_url is not None
    assert curve_set.provenance.source_url.startswith("docker://")
    assert engine.image in (curve_set.provenance.notes or "")
    assert curve_set.provenance.licence is not None
    assert curve_set.provenance.licence.startswith("AGPL-3.0")
