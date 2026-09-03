"""Real OpenQuake QA expected outputs parse into a valid HazardCurveSet (contract-checked)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import jsonschema
import pytest

from rupture.adapters.hazard import result_parser as rp
from rupture.domain import Provenance, contracts
from tests.unit.hazard.conftest import DEMO, QA_CASE_01, QA_CASE_02

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
PROV = Provenance(
    source="openquake.engine",
    retrieved_at=NOW,
    adapter_version="0.1.0",
    licence="AGPL-3.0 (engine); inputs per source model",
)


def _files(case_dir: str) -> dict[str, str]:
    root = QA_CASE_01 if case_dir == "case_01" else QA_CASE_02
    return {p.name: p.read_text() for p in sorted((root / "expected").glob("hazard_curve-*.csv"))}


def test_header_metadata_is_parsed() -> None:
    line = (QA_CASE_01 / "expected" / "hazard_curve-PGA.csv").read_text().splitlines()[0]
    meta = rp.parse_header_metadata(line)
    assert meta["kind"] == "mean"
    assert meta["imt"] == "PGA"
    assert meta["investigation_time"] == "1.0"
    assert meta["checksum"] == "2107362341"
    assert meta["generated_by"].startswith("OpenQuake engine 3.20.0")


def test_case_01_pga_file() -> None:
    parsed = rp.parse_hazard_curve_csv(_files("case_01")["hazard_curve-PGA.csv"])
    assert parsed.imt == "PGA"
    assert parsed.kind == "mean"
    assert parsed.investigation_time == 1.0
    assert parsed.engine_version == "3.20.0-git6a5db97d59"
    assert len(parsed.curves) == 4
    first = parsed.curves[0]
    assert first.imls == (0.1, 0.4, 0.6)
    assert first.poes == pytest.approx((4.553861e-01, 5.754043e-02, 6.354517e-03))
    assert (first.site_longitude, first.site_latitude) == (0.0, 0.0)


def test_case_01_builds_a_contract_valid_curve_set() -> None:
    curve_set = rp.build_curve_set(
        _files("case_01"),
        set_id="qa-case-01",
        source_model_id="source_model_logic_tree",
        gsim_logic_tree_id="gsim_logic_tree",
        job_hash="0" * 64,
        computed_at=NOW,
        provenance=PROV,
        engine_version_fallback="3.26.2",
    )
    assert curve_set.realisation == "mean"
    assert curve_set.investigation_time_years == 1.0
    assert curve_set.engine_version == "3.20.0-git6a5db97d59", "what produced the numbers"
    assert len(curve_set.curves) == 8, "4 sites x 2 IMTs"
    assert sorted({c.imt for c in curve_set.curves}) == ["PGA", "SA(0.1)"]
    assert curve_set.notes is not None
    assert "start_date" in curve_set.notes
    payload = json.loads(json.dumps(curve_set.model_dump(mode="json")))
    jsonschema.validate(payload, contracts.schema_for("hazard-curve-set.v0.json"))
    assert rp.check_curve_set(curve_set, expected_investigation_time=1.0) == []


def test_case_02_single_site_and_engine_style_file_name() -> None:
    text = _files("case_02")["hazard_curve-PGA.csv"]
    curve_set = rp.build_curve_set(
        {"hazard_curve-mean-PGA_7.csv": text},
        set_id="qa-case-02",
        source_model_id="source_model_logic_tree",
        gsim_logic_tree_id=None,
        job_hash="1" * 64,
        computed_at=NOW,
        provenance=PROV,
        engine_version_fallback="3.26.2",
    )
    assert len(curve_set.curves) == 1
    assert curve_set.curves[0].poes[0] == pytest.approx(1.084106e-01)
    jsonschema.validate(
        curve_set.model_dump(mode="json"), contracts.schema_for("hazard-curve-set.v0.json")
    )


def test_realisation_selection_prefers_mean_and_rejects_ambiguity() -> None:
    pga = _files("case_01")["hazard_curve-PGA.csv"]
    rlz = pga.replace("kind='mean'", "kind='rlz-000'")
    assert (
        rp.build_curve_set(
            {"a.csv": pga, "b.csv": rlz},
            set_id="x",
            source_model_id="s",
            gsim_logic_tree_id=None,
            job_hash="h",
            computed_at=NOW,
            provenance=PROV,
            engine_version_fallback="v",
        ).realisation
        == "mean"
    )
    only_rlz = rp.build_curve_set(
        {"b.csv": rlz},
        set_id="x",
        source_model_id="s",
        gsim_logic_tree_id=None,
        job_hash="h",
        computed_at=NOW,
        provenance=PROV,
        engine_version_fallback="v",
    )
    assert only_rlz.realisation == "rlz-000"
    other = pga.replace("kind='mean'", "kind='quantile-0.5'")
    with pytest.raises(rp.ResultParseError, match="several curve kinds"):
        rp.build_curve_set(
            {"b.csv": rlz, "c.csv": other},
            set_id="x",
            source_model_id="s",
            gsim_logic_tree_id=None,
            job_hash="h",
            computed_at=NOW,
            provenance=PROV,
            engine_version_fallback="v",
        )


def test_inconsistent_investigation_time_is_an_error() -> None:
    files = _files("case_01")
    files["hazard_curve-SA(0.1).csv"] = files["hazard_curve-SA(0.1).csv"].replace(
        "investigation_time=1.0", "investigation_time=50.0"
    )
    with pytest.raises(rp.ResultParseError, match="disagree on investigation_time"):
        rp.build_curve_set(
            files,
            set_id="x",
            source_model_id="s",
            gsim_logic_tree_id=None,
            job_hash="h",
            computed_at=NOW,
            provenance=PROV,
            engine_version_fallback="v",
        )


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("lon,lat\n0,0\n", "must start with a '#'"),
        ("#,\"kind='mean', imt='PGA'\"\nlon,lat,poe-0.1\n", "lacks 'investigation_time'"),
        ("#,\"kind='mean', imt='PGA', investigation_time=1.0\"\nlon,lat,depth\n0,0,0\n", "no poe-"),
        ("#,\"kind='mean', imt='PGA', investigation_time=1.0\"\nlon,lat,poe-0.1\n", "no site rows"),
        (
            "#,\"kind='mean', imt='PGA', investigation_time=1.0\"\nlon,lat,poe-0.1\n0,0,1.5\n",
            "probabilities",
        ),
    ],
)
def test_malformed_csv_is_rejected(text: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        rp.parse_hazard_curve_csv(text)


def test_check_curve_set_flags_non_monotone_curves() -> None:
    curve_set = rp.build_curve_set(
        _files("case_01"),
        set_id="x",
        source_model_id="s",
        gsim_logic_tree_id=None,
        job_hash="h",
        computed_at=NOW,
        provenance=PROV,
        engine_version_fallback="v",
    )
    bad_curve = curve_set.curves[0].model_copy(update={"poes": (0.1, 0.4, 0.2)})
    bad = curve_set.model_copy(update={"curves": (bad_curve, *curve_set.curves[1:])})
    problems = rp.check_curve_set(bad, expected_investigation_time=50.0)
    assert any("PoE increases with IML" in p for p in problems)
    assert any("investigation_time 1.0 != job 50.0" in p for p in problems)


def test_parse_job_ini_flattens_sections_and_multiline_values() -> None:
    params = rp.parse_job_ini((DEMO / "job.ini").read_text())
    assert params["calculation_mode"] == "classical"
    assert params["investigation_time"] == "50.0"
    assert params["source_model_logic_tree_file"] == "source_model_logic_tree.xml"
    assert params["gsim_logic_tree_file"] == "gmpe_logic_tree.xml"
    assert params["intensity_measure_types_and_levels"].startswith(
        '{ "PGA": logscale(0.005, 2.13, 45)'
    )
    assert params["region"] == "-1.0 -1.5, -1.0 0.7, 1.0 0.7, 1.0 -1.5"
    qa = rp.parse_job_ini((QA_CASE_01 / "job.ini").read_text())
    assert qa["area_source_discretization"] == ""
    assert qa["sites"].startswith("0.0 0.0 -0.1")
