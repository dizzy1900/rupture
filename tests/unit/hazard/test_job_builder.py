"""The job builder renders job.ini text the engine's own parser accepts, with the manual's keys."""

from __future__ import annotations

import configparser
import json
from pathlib import Path

import pytest

from rupture.adapters.hazard import job_builder
from rupture.adapters.hazard.result_parser import parse_job_ini
from rupture.ports.hazard_engine import ClassicalPSHAJob, ScenarioGroundMotionJob
from tests.unit.hazard.conftest import DEMO, QA_CASE_01

EAF_WKT = "POLYGON((35.5 35.5, 42.0 35.5, 42.0 40.0, 35.5 40.0, 35.5 35.5))"


def _classical(**overrides: object) -> ClassicalPSHAJob:
    base: dict[str, object] = {
        "id": "t",
        "description": "test  job",
        "source_model_logic_tree": Path("/in/smlt.xml"),
        "gsim_logic_tree": Path("/in/gslt.xml"),
        "region_wkt": EAF_WKT,
        "region_grid_spacing_km": 20.0,
    }
    base.update(overrides)
    return ClassicalPSHAJob.model_validate(base)


def _parse(text: str) -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_string(text)
    return cp


def test_classical_region_job_round_trips_through_configparser() -> None:
    text = job_builder.classical_job_ini(_classical())
    cp = _parse(text)
    assert cp.sections() == [
        "general",
        "geometry",
        "logic_tree",
        "erf",
        "site_params",
        "calculation",
        "output",
    ]
    assert cp["general"]["calculation_mode"] == "classical"
    assert cp["general"]["description"] == "test job"
    assert cp["geometry"]["region"] == "35.5 35.5, 42 35.5, 42 40, 35.5 40"
    assert cp["geometry"]["region_grid_spacing"] == "20.0"
    assert "sites_csv" not in cp["geometry"]
    assert cp["logic_tree"]["number_of_logic_tree_samples"] == "0"
    for key in ("rupture_mesh_spacing", "width_of_mfd_bin", "area_source_discretization"):
        assert key in cp["erf"]
    assert cp["site_params"]["reference_vs30_value"] == "760.0"
    assert cp["site_params"]["reference_vs30_type"] == "measured"
    calc = cp["calculation"]
    assert calc["source_model_logic_tree_file"] == "smlt.xml"
    assert calc["gsim_logic_tree_file"] == "gslt.xml"
    assert calc["investigation_time"] == "50.0"
    assert calc["truncation_level"] == "3.0"
    assert calc["maximum_distance"] == "200.0"
    imtls = json.loads(calc["intensity_measure_types_and_levels"])
    assert list(imtls) == ["PGA"]
    assert imtls["PGA"][0] == 0.005
    assert cp["output"]["export_dir"] == "out"
    assert cp["output"]["mean"] == "true"


def test_demo_job_ini_keys_are_a_subset_of_what_we_emit_plus_output_options() -> None:
    """The keys the engine's own demo uses are the keys we write (except demo-only outputs)."""
    demo_keys = set(parse_job_ini((DEMO / "job.ini").read_text()))
    ours = set(parse_job_ini(job_builder.classical_job_ini(_classical())))
    demo_only = {"hazard_maps", "uniform_hazard_spectra", "poes"}
    assert demo_keys - demo_only <= ours, demo_keys - demo_only - ours


def test_qa_case_job_ini_sites_keys_match_sites_csv_variant(tmp_path: Path) -> None:
    sites = tmp_path / "sites.csv"
    sites.write_text("site_id,lon,lat\n0,0.0,0.0\n")
    text = job_builder.classical_job_ini(
        _classical(sites_csv=sites, region_wkt=None, region_grid_spacing_km=None)
    )
    cp = _parse(text)
    assert cp["geometry"]["sites_csv"] == "sites.csv"
    assert "region" not in cp["geometry"]
    qa_keys = set(parse_job_ini((QA_CASE_01 / "job.ini").read_text()))
    qa_only = {
        "sites",
        "source_nodes",
        "minimum_engine_version",
        "max_sites_disagg",
        "minimun_magnitude",
    }
    assert qa_keys - qa_only <= set(parse_job_ini(text))


def test_site_definition_must_be_exactly_one() -> None:
    with pytest.raises(job_builder.JobBuilderError, match="needs sites_csv or region_wkt"):
        job_builder.classical_job_ini(_classical(region_wkt=None, region_grid_spacing_km=None))
    with pytest.raises(job_builder.JobBuilderError, match="not both"):
        job_builder.classical_job_ini(_classical(sites_csv=Path("/in/s.csv")))
    with pytest.raises(job_builder.JobBuilderError, match="requires region_grid_spacing_km"):
        job_builder.classical_job_ini(_classical(region_grid_spacing_km=None))


def test_imls_must_be_positive_and_increasing() -> None:
    with pytest.raises(job_builder.JobBuilderError, match="strictly increasing"):
        job_builder.classical_job_ini(_classical(imts={"PGA": (0.1, 0.1)}))
    with pytest.raises(job_builder.JobBuilderError, match="positive"):
        job_builder.classical_job_ini(_classical(imts={"PGA": (0.0, 0.1)}))
    with pytest.raises(job_builder.JobBuilderError, match="at least one"):
        job_builder.classical_job_ini(_classical(imts={}))


@pytest.mark.parametrize(
    ("wkt", "expected"),
    [
        ("POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))", "0 0, 1 0, 1 1, 0 1"),
        ("polygon ((0 0, 1 0, 1 1))", "0 0, 1 0, 1 1"),
        ("POLYGON ((-1.0 -1.5, -1.0 0.7, 1.0 0.7, 1.0 -1.5))", "-1 -1.5, -1 0.7, 1 0.7, 1 -1.5"),
    ],
)
def test_wkt_polygon_to_region(wkt: str, expected: str) -> None:
    assert job_builder.wkt_polygon_to_region(wkt) == expected


@pytest.mark.parametrize(
    "wkt",
    [
        "POINT(0 0)",
        "POLYGON((0 0, 1 0, 0 0))",
        "POLYGON((0 0, 1 0, 1 1, 0 0), (0.1 0.1, 0.2 0.1, 0.2 0.2, 0.1 0.1))",
        "POLYGON((0 0, 200 0, 1 1))",
    ],
)
def test_bad_wkt_is_rejected(wkt: str) -> None:
    with pytest.raises(job_builder.JobBuilderError):
        job_builder.wkt_polygon_to_region(wkt)


def test_scenario_job_ini() -> None:
    job = ScenarioGroundMotionJob(
        id="s",
        description="scenario",
        rupture_model=Path("/in/rupture.xml"),
        gsim="BooreAtkinson2008",
        sites_csv=Path("/in/sites.csv"),
        imts=("PGA", "SA(0.3)"),
        number_of_ground_motion_fields=10,
    )
    cp = _parse(job_builder.scenario_job_ini(job))
    assert cp["general"]["calculation_mode"] == "scenario"
    assert cp["geometry"]["sites_csv"] == "sites.csv"
    assert cp["rupture"]["rupture_model_file"] == "rupture.xml"
    calc = cp["calculation"]
    assert calc["intensity_measure_types"] == "PGA, SA(0.3)"
    assert calc["gsim"] == "BooreAtkinson2008"
    assert calc["number_of_ground_motion_fields"] == "10"
    assert "reference_vs30_value" in cp["site_params"]


def test_referenced_inputs_and_name_collisions() -> None:
    job = _classical()
    assert job_builder.referenced_inputs(job) == {
        "smlt.xml": Path("/in/smlt.xml"),
        "gslt.xml": Path("/in/gslt.xml"),
    }
    with pytest.raises(job_builder.JobBuilderError, match="share the file name"):
        job_builder.referenced_inputs(_classical(gsim_logic_tree=Path("/other/smlt.xml")))


def test_referenced_source_models_from_real_logic_trees() -> None:
    demo_smlt = (DEMO / "source_model_logic_tree.xml").read_text()
    assert job_builder.referenced_source_models(demo_smlt) == ["source_model.xml"]
    qa_smlt = (QA_CASE_01 / "source_model_logic_tree.xml").read_text()
    assert job_builder.referenced_source_models(qa_smlt) == ["source_model.xml"]
    gmlt = (DEMO / "gmpe_logic_tree.xml").read_text()
    assert job_builder.referenced_source_models(gmlt) == [], "GSIM names are not files"
