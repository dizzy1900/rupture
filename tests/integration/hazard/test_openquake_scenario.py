"""``run_scenario`` against the real engine: does the rendered ini run, and where do GMFs land?

``job_builder.scenario_job_ini`` was unit-tested to produce parseable ini text and
``OpenQuakeDocker.run_scenario`` had zero callers and zero tests, so half of the D7 job-builder
requirement rested on reading the manual: whether the engine accepts the keys, whether staging a
rupture model and a sites CSV works, and whether the ``gmf_data`` export lands in the directory the
adapter returns had never been observed anywhere.

The case is ``scenario/case_1`` from ``gem/oq-engine`` (``engine-3.26``): one vertical simple-fault
rupture at Mw 6.5, three sites, PGA with BooreAtkinson2008, 102 ground-motion fields.

**The engine's expected file is a reference distribution here, not a target.** It was generated
with ``ses_seed = 3``; ``ScenarioGroundMotionJob`` carries ``random_seed`` and the builder writes
that key, so the sampled values differ run to run and cannot be compared value by value. What is
compared is the shape of the output — one row per event and site, finite positive PGA — and the
median PGA per site against the fixture's own, which the ground-motion model fixes and sampling
only jitters. Making the values reproducible would mean giving the port a ``ses_seed`` field, which
is a design change for the owner of ``ports/`` and is not smuggled in through a test.

Needs Docker and the pinned image; skips with the printed reason otherwise.
"""

from __future__ import annotations

import csv
import io
import os
import statistics
from pathlib import Path

import pytest

from rupture.adapters.hazard.openquake_docker import ALLOW_EMULATION_ENV, OpenQuakeDocker
from rupture.ports.hazard_engine import ScenarioGroundMotionJob
from rupture.validation.hazard import REQUIRE_ENV, required

pytestmark = pytest.mark.integration

CASE = Path(__file__).resolve().parents[2] / "fixtures" / "hazard" / "qa_scenario_case_01"
SITES = ((0.0, 0.0), (0.0, 0.1), (0.0, 0.2))
N_FIELDS = 102


@pytest.fixture(scope="module")
def engine() -> OpenQuakeDocker:
    emulating = os.environ.get(ALLOW_EMULATION_ENV, "").strip().lower() in {"1", "true", "yes"}
    eng = OpenQuakeDocker(run_timeout_s=1800.0, env={"OQ_DISTRIBUTE": "no"} if emulating else None)
    ok, reason = eng.available()
    if not ok:
        if required():
            pytest.fail(f"container cannot run here but {REQUIRE_ENV} is set: {reason}")
        pytest.skip(f"cannot run the container here: {reason}")
    eng.ensure_image()
    return eng


@pytest.fixture(scope="module")
def work_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    keep = os.environ.get("RUPTURE_HAZARD_WORK_DIR")
    if keep:
        path = Path(keep) / "integration-scenario"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return tmp_path_factory.mktemp("oq-scenario")


@pytest.fixture(scope="module")
def job(tmp_path_factory: pytest.TempPathFactory) -> ScenarioGroundMotionJob:
    sites_csv = tmp_path_factory.mktemp("oq-scenario-inputs") / "sites.csv"
    sites_csv.write_text("".join(f"{lon},{lat}\n" for lon, lat in SITES), encoding="utf-8")
    return ScenarioGroundMotionJob(
        id="qa-scenario-case-01",
        description="OpenQuake QA scenario case 1 rendered by rupture (Mw 6.5 simple fault)",
        rupture_model=CASE / "rupture_model.xml",
        gsim="BooreAtkinson2008",
        sites_csv=sites_csv,
        imts=("PGA",),
        number_of_ground_motion_fields=N_FIELDS,
        truncation_level=1.0,
        maximum_distance_km=5.0,
        reference_vs30=800.0,
    )


@pytest.fixture(scope="module")
def gmf_rows(
    engine: OpenQuakeDocker, job: ScenarioGroundMotionJob, work_dir: Path
) -> list[dict[str, str]]:
    out_dir = engine.run_scenario(job, work_dir)
    assert out_dir == work_dir / "out", "run_scenario must return the directory it exported into"
    paths = sorted(out_dir.glob("gmf-data*.csv")) or sorted(out_dir.glob("*gmf*.csv"))
    assert paths, f"no gmf_data CSV exported into {out_dir}; see {work_dir / 'oq.log'}"
    rows: list[dict[str, str]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
        rows.extend(csv.DictReader(io.StringIO(body)))
    return rows


def _reference_median() -> float:
    text = (CASE / "expected" / "BooreAtkinson2008_gmf.csv").read_text(encoding="utf-8")
    body = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
    values = [float(r["gmv_PGA"]) for r in csv.DictReader(io.StringIO(body))]
    return statistics.median(values)


def test_the_engine_accepts_the_rendered_scenario_ini(
    gmf_rows: list[dict[str, str]], work_dir: Path
) -> None:
    ini = (work_dir / "job.ini").read_text(encoding="utf-8")
    assert "calculation_mode = scenario" in ini
    assert "rupture_model_file = rupture_model.xml" in ini
    assert "gsim = BooreAtkinson2008" in ini
    assert f"number_of_ground_motion_fields = {N_FIELDS}" in ini
    assert (work_dir / "rupture_model.xml").is_file(), "the rupture model was staged"
    assert (work_dir / "sites.csv").is_file(), "the sites CSV was staged"
    assert (work_dir / "oq.log").is_file()
    assert gmf_rows, "the run produced ground-motion values"


def test_the_ground_motion_values_are_well_formed(gmf_rows: list[dict[str, str]]) -> None:
    column = next(k for k in gmf_rows[0] if k.startswith("gmv_"))
    assert column == "gmv_PGA", gmf_rows[0]
    values = [float(r[column]) for r in gmf_rows]
    assert all(v > 0.0 for v in values), "PGA is a positive ground-motion value"
    assert all(v < 10.0 for v in values), "PGA in g; 10 g would be an ordering or units error"
    events = {r["event_id"] for r in gmf_rows}
    assert len(events) == N_FIELDS, f"{len(events)} events for {N_FIELDS} requested fields"


def test_the_sampled_distribution_sits_where_the_engines_own_reference_does(
    gmf_rows: list[dict[str, str]],
) -> None:
    """Not a value comparison -- the seeds differ (see the module docstring) -- but the median is
    set by the ground-motion model and the geometry, which are identical, so it must agree well
    inside the sampling spread of 102 fields at truncation level 1."""
    values = [float(r["gmv_PGA"]) for r in gmf_rows]
    assert statistics.median(values) == pytest.approx(_reference_median(), rel=0.2)
