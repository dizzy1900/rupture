"""Regions, fixture integrity, GEM faults and ESHM20 excerpts, and the CLI (offline)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from shapely.geometry import Point
from typer.testing import CliRunner

from rupture.adapters.catalogs.fixtures import FixtureError, load_fixture_dir
from rupture.adapters.sources import gem_faults, openquake_sources, regions
from rupture.cli import app
from rupture.domain import MagnitudePolicy, Region, TectonicSetting, sha256_hex
from rupture.validation.catalog import run as run_catalog_gate

runner = CliRunner()

# --------------------------------------------------------------------------- regions


def test_three_regions_load_and_match_geojson(repo_root: Path) -> None:
    root = regions.default_regions_root(repo_root)
    assert regions.list_region_ids(root) == ["california", "nepal-himalaya", "turkiye-eaf"]
    for rid in regions.list_region_ids(root):
        r = regions.load_region(root, rid)
        assert r.mc is None or r.mc.mc > 0
        assert regions.region_polygon(r).is_valid


def test_region_parameters_match_protocol(
    nepal: Region, turkiye: Region, california: Region
) -> None:
    assert (california.depth_max_km, california.target_min_magnitude) == (30.0, 3.95)
    assert california.tectonic_setting is TectonicSetting.TRANSFORM
    assert california.magnitude_policy is MagnitudePolicy.NETWORK_PREFERRED_AS_MW  # ADR-0019
    assert (nepal.depth_max_km, nepal.target_min_magnitude) == (70.0, 4.7)  # ADR-0019
    assert nepal.tectonic_setting is TectonicSetting.CONTINENTAL_COLLISION
    assert nepal.magnitude_policy is MagnitudePolicy.STRICT
    assert (turkiye.depth_max_km, turkiye.target_min_magnitude) == (50.0, 4.6)  # ADR-0019
    assert turkiye.tectonic_setting is TectonicSetting.TRANSFORM
    assert turkiye.magnitude_policy is MagnitudePolicy.STRICT
    assert len(california.polygon) <= 200


def test_california_polygon_covers_every_relm_cell(california: Region) -> None:
    csep_regions = pytest.importorskip("csep.core.regions")
    relm = csep_regions.california_relm_region()
    poly = regions.region_polygon(california)
    dh = relm.dh
    misses = [(x, y) for x, y in relm.origins() if not poly.covers(Point(x + dh / 2, y + dh / 2))]
    assert misses == []
    assert poly.area == pytest.approx(relm.num_nodes * dh * dh, rel=1e-3)


def test_corridors_contain_their_mainshocks(nepal: Region, turkiye: Region) -> None:
    assert regions.contains(regions.region_polygon(nepal), 84.7314, 28.2305)  # Gorkha
    assert regions.contains(regions.region_polygon(nepal), 85.515, 28.271)  # us7000tbwb
    assert regions.contains(regions.region_polygon(turkiye), 37.0143, 37.2256)  # Pazarcik
    assert regions.contains(regions.region_polygon(turkiye), 37.196, 38.011)  # Elbistan


def test_disagreeing_geojson_is_rejected(tmp_path: Path, nepal: Region) -> None:
    regions.write_region(tmp_path, nepal)
    geo = tmp_path / nepal.id / "region.geojson"
    doc = json.loads(geo.read_text())
    doc["geometry"]["coordinates"][0][0] = [0.0, 0.0]
    geo.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="disagrees"):
        regions.load_region(tmp_path, nepal.id)


# -------------------------------------------------------------------------- fixtures


def test_every_fixture_dir_has_provenance_and_matching_digests(fixtures_root: Path) -> None:
    for d in sorted(p for p in fixtures_root.iterdir() if p.is_dir()):
        files = load_fixture_dir(d, adapter_version="test")
        assert files, d
        for f in files:
            assert f.provenance.sha256 == sha256_hex(f.content)
            assert f.provenance.source_url
            assert f.provenance.retrieved_at.tzinfo is not None
            assert f.path.stat().st_size <= 1_100_000


def test_edited_fixture_is_refused(tmp_path: Path, fixtures_root: Path) -> None:
    src = fixtures_root / "isc"
    for p in src.iterdir():
        (tmp_path / p.name).write_bytes(p.read_bytes())
    target = next(p for p in tmp_path.iterdir() if p.suffix == ".txt")
    target.write_bytes(target.read_bytes() + b"\n# edited\n")
    with pytest.raises(FixtureError, match="sha256"):
        load_fixture_dir(tmp_path, adapter_version="test")


# ------------------------------------------------------------------------ GEM faults


def test_gaf_nepal_subset_parses_and_clips(fixtures_root: Path, nepal: Region) -> None:
    files = load_fixture_dir(fixtures_root / "gem_faults", adapter_version="test")
    assert len(files) == 1
    gdf = gem_faults.parse_gaf_geojson(files[0].content)
    meta = json.loads((fixtures_root / "gem_faults" / "provenance.json").read_text())
    info = meta["files"][files[0].path.name]
    assert len(gdf) == info["n_features"] > 20
    assert meta["licence"] == "CC-BY-SA-4.0"
    assert "Styron" in meta["attribution"]
    assert {"slip_type", "catalog_name", "geometry"} <= set(gdf.columns)
    clipped = gem_faults.clip_to_region(gdf, nepal)
    assert 0 < len(clipped) <= len(gdf)
    assert clipped.attrs["licence"] == "CC-BY-SA-4.0"
    assert clipped.total_bounds[0] >= nepal.bbox()[0] - 1e-6
    assert clipped.total_bounds[2] <= nepal.bbox()[2] + 1e-6


# ------------------------------------------------------------------------- OpenQuake


def test_available_models_turkiye_only() -> None:
    models, gap = openquake_sources.available_models("turkiye-eaf")
    assert gap is None
    assert len(models) == 1
    assert models[0].licence == "CC-BY-4.0"
    assert "ESHM20-OQ-INPUT" in models[0].citation
    for rid in ("california", "nepal-himalaya"):
        models, gap = openquake_sources.available_models(rid)
        assert models == []
        assert gap is not None
        assert "ADR-0008" in gap


def test_eshm20_header_excerpt_is_nrml_logic_tree(fixtures_root: Path) -> None:
    files = load_fixture_dir(fixtures_root / "eshm20", adapter_version="test")
    header = openquake_sources.parse_nrml_header(files[0].content)
    assert header.root_tag == "nrml"
    assert header.namespace == openquake_sources.NRML_NS_04
    assert header.child_tag == "logicTree"
    assert header.child_id == "lt1"
    with pytest.raises(ValueError, match="NRML"):
        openquake_sources.parse_nrml_header(b"<root><a/></root>")


# ------------------------------------------------------------------------------- CLI


def test_region_cli_list_and_show() -> None:
    result = runner.invoke(app, ["region", "list"])
    assert result.exit_code == 0, result.output
    assert "nepal-himalaya" in result.output
    result = runner.invoke(app, ["region", "show", "turkiye-eaf"])
    assert result.exit_code == 0
    assert json.loads(result.output)["id"] == "turkiye-eaf"
    result = runner.invoke(app, ["region", "show", "atlantis"])
    assert result.exit_code != 0


def test_catalog_cli_build_offline_and_inspect(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "catalog",
            "build",
            "--region",
            "nepal-himalaya",
            "--from",
            "2015-04-25T00:00:00Z",
            "--to",
            "2015-05-25T00:00:00Z",
            "--offline-fixtures",
            "--no-etas-cross-check",
            "--out",
            str(tmp_path / "nepal"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Mc[maximum_curvature]" in result.output
    assert (tmp_path / "nepal" / "events.parquet").exists()
    meta = json.loads((tmp_path / "nepal" / "catalog.meta.json").read_text())
    assert meta["region_id"] == "nepal-himalaya"
    assert meta["n_events"] > 100
    result = runner.invoke(app, ["catalog", "inspect", str(tmp_path / "nepal")])
    assert result.exit_code == 0, result.output
    assert "homogenisation log entries" in result.output
    result = runner.invoke(app, ["catalog", "inspect", str(tmp_path / "nepal"), "--json"])
    assert json.loads(result.output)["n_events"] == meta["n_events"]


def test_catalog_gate_passes_offline(repo_root: Path) -> None:
    result = run_catalog_gate(repo_root)
    assert result.status.value == "passed", result.render()
