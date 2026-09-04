"""The engine's event-based path: job rendering and export parsing, offline (ADR-0043).

The container itself cannot run on this project's arm64 development machine, so what is tested
here is everything either side of the container: the ``job.ini``, the source model, the GSIM
logic tree and every export parser. ``tests/integration/risk/`` runs the container in CI.
"""

from __future__ import annotations

import json

import pytest

from rupture.adapters.groundmotion import logic_trees as lt
from rupture.adapters.groundmotion import openquake_event_based as oqeb
from rupture.adapters.hazard.openquake_docker import OpenQuakeError
from rupture.domain.forecast import ForecastGrid
from rupture.domain.groundmotion import GsimBranch, GsimLogicTree, Site
from tests.unit.risk.conftest import RISK_FIXTURES, site

SLICE_FILE = RISK_FIXTURES / "forecast" / "trishuli-corridor-slice.json"
SITES: tuple[Site, ...] = (site("a", 85.30, 28.05), site("b", 85.35, 28.10))

EVENTS_CSV = "#some,header\nevent_id,rup_id,rlz_id\n0,7,0\n1,7,0\n2,9,0\n"
RUPTURES_CSV = (
    "#header\nrup_id,multiplicity,mag,centroid_lon,centroid_lat\n"
    "7,2,6.4,85.3,28.1\n9,1,7.1,85.4,28.2\n"
)
SITEMESH_CSV = "#h\nsite_id,lon,lat\n0,85.300000,28.050000\n1,85.350000,28.100000\n"
GMF_CSV = "#h\nevent_id,site_id,gmv_PGA\n0,0,0.31\n0,1,0.28\n1,0,0.11\n1,1,0.09\n2,0,0.72\n"


@pytest.fixture(scope="module")
def grid() -> ForecastGrid:
    return ForecastGrid.model_validate(json.loads(SLICE_FILE.read_text(encoding="utf-8")))


def test_job_ini_asks_for_an_event_based_calculation_with_the_tree(grid: ForecastGrid) -> None:
    text = oqeb.event_based_job_ini(
        description="rupture event based",
        imt="PGA",
        investigation_time_years=1000.0,
        ses_per_logic_tree_path=2,
        n_logic_tree_samples=30,
        truncation_level=3.0,
        maximum_distance_km=300.0,
        random_seed=7,
        minimum_magnitude=5.0,
    )
    assert "calculation_mode = event_based" in text
    assert "investigation_time = 1000.0" in text
    assert "ses_per_logic_tree_path = 2" in text
    assert "number_of_logic_tree_samples = 30" in text
    assert f"gsim_logic_tree_file = {oqeb.GSIM_LOGIC_TREE}" in text
    assert f"source_model_logic_tree_file = {oqeb.SOURCE_MODEL_LOGIC_TREE}" in text
    assert "ground_motion_fields = true" in text
    assert "minimum_magnitude = 5.0" in text


def test_the_source_model_carries_the_grids_own_annualised_rates(grid: ForecastGrid) -> None:
    xml = oqeb.grid_source_model_nrml(grid, min_magnitude=5.0)
    assert "<sourceModel" in xml
    assert "pointSource" in xml
    assert "<incrementalMFD" in xml
    assert "<occurRates>" in xml
    # Every rate in the document must be the grid's own count divided by its horizon in years.
    years = grid.horizon.total_seconds() / oqeb.SECONDS_PER_YEAR
    keep = [
        j
        for j, edge in enumerate(grid.magnitude_bin_edges)
        if edge + grid.magnitude_bin_width > 5.0
    ]
    total_in_xml = sum(
        float(v)
        for block in xml.split("<occurRates>")[1:]
        for v in block.split("</occurRates>")[0].split()
    )
    expected = sum(row[j] for row in grid.expected_counts for j in keep) / years
    assert total_in_xml == pytest.approx(expected, rel=1e-6)


def test_a_grid_with_nothing_above_the_threshold_is_refused(grid: ForecastGrid) -> None:
    with pytest.raises(OpenQuakeError, match="no magnitude bin"):
        oqeb.grid_source_model_nrml(grid, min_magnitude=99.0)


def test_a_weighted_tree_may_not_be_enumerated() -> None:
    engine = oqeb.OpenQuakeEventBasedEngine()
    with pytest.raises(OpenQuakeError, match="not equally likely"):
        engine._samples(lt.ACTIVE_SHALLOW_CRUST_Q, None)
    assert engine._samples(lt.ACTIVE_SHALLOW_CRUST_Q, 40) == 40
    single = GsimLogicTree(
        id="one",
        branches=(GsimBranch(id="a", gsim="BooreEtAl2014", weight=1.0, rationale="only"),),
    )
    assert engine._samples(single, None) == 0


def test_events_and_ruptures_exports_are_parsed() -> None:
    assert oqeb.parse_events_export(EVENTS_CSV) == {"0": "7", "1": "7", "2": "9"}
    assert oqeb.parse_ruptures_export(RUPTURES_CSV) == {"7": 6.4, "9": 7.1}


def test_the_gmf_export_keeps_events_apart_and_fills_unreached_sites_with_zero() -> None:
    grouped = oqeb.group_gmf_by_event(GMF_CSV, SITEMESH_CSV, SITES, "PGA")
    assert set(grouped) == {"0", "1", "2"}
    assert grouped["0"] == (0.31, 0.28)
    assert grouped["2"] == (0.72, 0.0)


def test_an_export_with_no_rows_for_the_imt_fails_loudly() -> None:
    with pytest.raises(oqeb.EventBasedExportError, match="no gmv_PGV column"):
        oqeb.group_gmf_by_event(GMF_CSV, SITEMESH_CSV, SITES, "PGV")


def test_parse_run_gives_every_event_the_same_rate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    out = tmp_path / "out"
    out.mkdir()
    (out / "events_1.csv").write_text(EVENTS_CSV, encoding="utf-8")
    (out / "ruptures_1.csv").write_text(RUPTURES_CSV, encoding="utf-8")
    (out / "gmf-data_1.csv").write_text(GMF_CSV, encoding="utf-8")
    (out / "sitemesh_1.csv").write_text(SITEMESH_CSV, encoding="utf-8")
    engine = oqeb.OpenQuakeEventBasedEngine()
    result = engine.parse_run(
        out,
        SITES,
        imt="PGA",
        tree=lt.ACTIVE_SHALLOW_CRUST_Q,
        investigation_time_years=1000.0,
        ses_per_logic_tree_path=2,
        n_logic_tree_samples=30,
        truncation_level=3.0,
        seed=1,
    )
    assert len(result.fields) == 3
    assert result.magnitudes == (6.4, 6.4, 7.1)
    assert result.occurrence_rate_per_year == pytest.approx(1.0 / (1000.0 * 2 * 30))
    assert all(f.n_realisations == 1 for f in result.fields)
    assert all(f.gsim == f"logic-tree:{lt.ACTIVE_SHALLOW_CRUST_Q.id}" for f in result.fields)


def test_the_event_based_path_refuses_to_run_without_a_work_dir() -> None:
    with pytest.raises(OpenQuakeError, match="work_dir"):
        oqeb.OpenQuakeEventBasedEngine().event_based(
            "<nrml/>",
            SITES,
            tree=lt.ACTIVE_SHALLOW_CRUST_Q,
            n_logic_tree_samples=10,
        )
