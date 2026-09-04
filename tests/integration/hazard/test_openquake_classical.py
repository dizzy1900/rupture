"""A classical PSHA rendered by rupture, run by the real engine, checked against GEM's own answer.

Until this test existed, no ``job.ini`` written by ``adapters/hazard/job_builder.classical_job_ini``
had ever been read by OpenQuake: the only calculation the container had run was the engine's own
bundled demo, copied out of the image, and the rendered ini had been consumed only by
``configparser`` and by a fake ``docker``. The rupture-authored half of the classical chain --
key names, the ``region``/``sites_csv`` geometry, the JSON
``intensity_measure_types_and_levels``, staging the source models a logic tree names, the export
key and the CSV parse back -- was therefore unproven against the engine that has to accept it.

The case is ``qa_classical_case_01`` from ``gem/oq-engine`` (``engine-3.26``): one point source,
four sites, ``investigation_time = 1.0``, three intensity levels for PGA and SA(0.1). Its
``expected/`` curves are GEM's own regression baseline, so the run has an external answer to be
right against, and it is small enough to finish in seconds.

What rupture supplies differently from the fixture's ``job.ini`` is the geometry: the fixture
gives four inline ``sites``, while ``ClassicalPSHAJob`` takes a ``sites_csv``. The CSV is written
**headerless** (``lon,lat,depth`` per line) because the engine keeps the depth column on that path
and drops it when a ``lon`` header is present; the QA sites sit at -0.1 km, and a site 100 m
higher would move the PoEs by more than the tolerance below. Everything else -- ERF spacing, site
parameters, truncation, maximum distance -- is set to the fixture's values so that any difference
in the curves is a difference in what rupture rendered.

Needs Docker and the pinned image; skips with the printed reason otherwise, and the CI job
``hazard-integration`` sets ``RUPTURE_HAZARD_REQUIRE=1`` so a skip there fails instead.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from rupture.adapters.hazard.job_builder import ErfSettings, SiteDepthSettings, classical_job_ini
from rupture.adapters.hazard.openquake_docker import ALLOW_EMULATION_ENV, OpenQuakeDocker
from rupture.adapters.hazard.result_parser import check_curve_set, parse_hazard_curve_csv
from rupture.domain import HazardCurveSet
from rupture.pipelines import hazard as pipeline
from rupture.ports.hazard_engine import ClassicalPSHAJob
from rupture.validation.hazard import REQUIRE_ENV, required

pytestmark = pytest.mark.integration

CASE = Path(__file__).resolve().parents[2] / "fixtures" / "hazard" / "qa_classical_case_01"
SITES = ((0.0, 0.0, -0.1), (0.1, 0.0, -0.1), (0.2, 0.0, -0.1), (0.3, 0.0, -0.1))
IMLS = (0.1, 0.4, 0.6)
IMTS = ("PGA", "SA(0.1)")
POE_FLOOR = 1e-6
"""PoEs at or below this are the engine's own zeros; comparing them relatively is meaningless."""


@pytest.fixture(scope="module")
def engine() -> OpenQuakeDocker:
    """The runner with the fixture's own ERF and site settings, so the two jobs differ only in
    geometry (inline ``sites`` there, a ``sites_csv`` here)."""
    # Under QEMU emulation (an arm64 host running the amd64 image, opted into with
    # RUPTURE_OPENQUAKE_ALLOW_EMULATION) the engine hangs at "Reading the source model(s) in
    # parallel". Serial execution gets through it in about a minute, so the emulated path is
    # reproducible rather than merely skipped. On amd64 (CI) nothing is set and the engine uses
    # its own process pool; the calculation is identical either way.
    emulating = os.environ.get(ALLOW_EMULATION_ENV, "").strip().lower() in {"1", "true", "yes"}
    eng = OpenQuakeDocker(
        run_timeout_s=1800.0,
        env={"OQ_DISTRIBUTE": "no"} if emulating else None,
        erf=ErfSettings(
            rupture_mesh_spacing_km=1.0, width_of_mfd_bin=1.0, area_source_discretization_km=10.0
        ),
        site=SiteDepthSettings(
            depth_to_2pt5km_per_sec_km=2.5, depth_to_1pt0km_per_sec_m=50.0, vs30_type="measured"
        ),
    )
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
        path = Path(keep) / "integration-classical"
        path.mkdir(parents=True, exist_ok=True)
        return path
    return tmp_path_factory.mktemp("oq-classical")


@pytest.fixture(scope="module")
def job(tmp_path_factory: pytest.TempPathFactory) -> ClassicalPSHAJob:
    """The QA case as a ``ClassicalPSHAJob``; the sites file lives outside the work directory so
    the run stages it like any other input."""
    sites_csv = tmp_path_factory.mktemp("oq-classical-inputs") / "sites.csv"
    sites_csv.write_text(
        "".join(f"{lon},{lat},{depth}\n" for lon, lat, depth in SITES), encoding="utf-8"
    )
    return ClassicalPSHAJob(
        id="qa-classical-case-01",
        description="OpenQuake QA classical case 1 rendered by rupture (one point source)",
        source_model_logic_tree=CASE / "source_model_logic_tree.xml",
        gsim_logic_tree=CASE / "gsim_logic_tree.xml",
        sites_csv=sites_csv,
        investigation_time_years=1.0,
        imts={imt: IMLS for imt in IMTS},
        truncation_level=2.0,
        maximum_distance_km=200.0,
        reference_vs30=800.0,
        number_of_logic_tree_samples=0,
    )


@pytest.fixture(scope="module")
def curve_set(engine: OpenQuakeDocker, job: ClassicalPSHAJob, work_dir: Path) -> HazardCurveSet:
    return pipeline.run_classical(engine, job, work_dir)


def _expected(imt: str) -> dict[tuple[float, float], tuple[float, ...]]:
    """GEM's baseline PoEs for one IMT, keyed by (lon, lat)."""
    text = (CASE / "expected" / f"hazard_curve-{imt}.csv").read_text(encoding="utf-8")
    parsed = parse_hazard_curve_csv(text)
    return {(c.site_longitude, c.site_latitude): tuple(c.poes) for c in parsed.curves}


def test_the_engine_accepts_the_rendered_job_ini(
    curve_set: HazardCurveSet, engine: OpenQuakeDocker, job: ClassicalPSHAJob, work_dir: Path
) -> None:
    """The gap this test exists for: a rupture-rendered classical ini the engine actually ran."""
    staged = (work_dir / "job.ini").read_text(encoding="utf-8")
    assert staged == classical_job_ini(job, erf=engine.erf, site=engine.site)
    assert "calculation_mode = classical" in staged
    assert curve_set.engine == "openquake.engine"
    assert curve_set.engine_version.startswith("3.26"), curve_set.engine_version
    assert curve_set.realisation == "mean"
    assert curve_set.investigation_time_years == 1.0
    assert (work_dir / "oq.log").is_file()
    assert (work_dir / pipeline.CURVE_SET_FILE).is_file()
    assert check_curve_set(curve_set, expected_investigation_time=1.0) == []


def test_every_requested_site_and_imt_came_back(curve_set: HazardCurveSet) -> None:
    got = {(c.imt, round(c.site_longitude, 5), round(c.site_latitude, 5)) for c in curve_set.curves}
    want = {(imt, round(lon, 5), round(lat, 5)) for imt in IMTS for lon, lat, _ in SITES}
    assert got == want
    for curve in curve_set.curves:
        assert tuple(curve.imls) == IMLS


@pytest.mark.parametrize("imt", IMTS)
def test_poes_match_the_engines_own_qa_baseline(curve_set: HazardCurveSet, imt: str) -> None:
    """A mismatch here is a difference between the fixture's job and the one rupture rendered.

    The likeliest cause would be the sites file: if the engine dropped the depth column, the four
    sites would sit at 0 km instead of -0.1 km and the near-source PoEs would move by ~1 %.
    """
    expected = _expected(imt)
    checked = 0
    for curve in (c for c in curve_set.curves if c.imt == imt):
        key = (round(curve.site_longitude, 5), round(curve.site_latitude, 5))
        want = next(v for k, v in expected.items() if (round(k[0], 5), round(k[1], 5)) == key)
        for level, got_poe, want_poe in zip(curve.imls, curve.poes, want, strict=True):
            if want_poe <= POE_FLOOR:
                assert got_poe <= 10 * POE_FLOOR, f"{imt} {key} iml={level}: {got_poe} should be ~0"
                continue
            assert got_poe == pytest.approx(want_poe, rel=1e-3), f"{imt} {key} iml={level}"
            checked += 1
    assert checked >= 3, "the baseline comparison must actually compare non-zero PoEs"


def test_the_job_hash_is_stable_across_a_rerun(
    engine: OpenQuakeDocker, job: ClassicalPSHAJob, curve_set: HazardCurveSet, work_dir: Path
) -> None:
    """Re-running in the same directory must not change the input hash (exports are not hashed)."""
    again = pipeline.run_classical(engine, job, work_dir)
    assert again.job_hash == curve_set.job_hash
