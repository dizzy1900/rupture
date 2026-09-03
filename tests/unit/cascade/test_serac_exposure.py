"""serac slope units and the co-seismic exposure overlay, on the committed serac fixtures."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import numpy as np
import pytest

from rupture.adapters.cascade import gorkha
from rupture.adapters.cascade.serac import (
    DEFAULT_PGA_THRESHOLD_G,
    SeracExportMissingError,
    SeracSlopeUnitSource,
    _representative_point,
)
from rupture.domain import contracts
from rupture.domain.cascade import CascadeKind
from rupture.domain.common import Provenance
from rupture.domain.groundmotion import GroundMotionEngineId, GroundMotionField, Site
from rupture.domain.money import ConfidenceTier, ModelProvenance

AOI = "lhende-khola-trishuli"


@pytest.fixture
def source(repo_root: Path) -> SeracSlopeUnitSource:
    return SeracSlopeUnitSource(repo_root=repo_root)


def pga_field(lons: list[float], lats: list[float], values: list[float]) -> GroundMotionField:
    sites = tuple(
        Site(id=str(i), longitude=lon, latitude=lat, vs30=400.0)
        for i, (lon, lat) in enumerate(zip(lons, lats, strict=True))
    )
    return GroundMotionField(
        id="test-pga",
        scenario_id="test",
        imt="PGA",
        sites=sites,
        values=(tuple(values),),
        engine=GroundMotionEngineId.NATIVE_GSIM,
        engine_version="test",
        gsim="test",
        computed_at=datetime(2026, 9, 3, tzinfo=UTC),
        provenance=Provenance(
            source="test", retrieved_at=datetime(2026, 9, 3, tzinfo=UTC), adapter_version="0.0.0"
        ),
    )


def test_the_fallback_is_labelled_as_a_fallback(source: SeracSlopeUnitSource) -> None:
    inventory = source.inventory(AOI)
    assert inventory.is_fallback
    assert "fallback" in inventory.source_id
    assert "FALLBACK" in inventory.notes
    assert inventory.licence == "Apache-2.0"


def test_the_fallback_leaves_every_unsourced_terrain_attribute_null(
    source: SeracSlopeUnitSource,
) -> None:
    """serac's AOI build carries no DEM. Nothing may be guessed in its place."""
    for unit in source.units_for(AOI):
        assert unit["mean_slope_deg"] is None
        assert unit["aspect_deg"] is None
        assert unit["glacier_cover"] is None
        assert unit["permafrost_index"] is None
        assert unit["elevation_band_m"] is None
        assert unit["source_refs"], "serac's own source refs must be carried through"


def test_the_fallback_geometry_is_seracs_own_polygon(
    source: SeracSlopeUnitSource, repo_root: Path
) -> None:
    original = json.loads(
        (repo_root / "tests/fixtures/cascade/serac" / AOI / "source_zone.geojson").read_text()
    )
    units = source.units_for(AOI)
    assert len(units) == len(original["features"])
    assert units[0]["geometry"] == original["features"][0]["geometry"]


def test_an_unknown_aoi_fails_loudly(source: SeracSlopeUnitSource) -> None:
    with pytest.raises(SeracExportMissingError, match="no slope units"):
        source.inventory("no-such-aoi")


def test_a_real_serac_export_takes_precedence_over_the_fallback(
    tmp_path: Path, repo_root: Path
) -> None:
    export = tmp_path / "slope-units"
    export.mkdir()
    (export / f"{AOI}.geojson").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [[85.51, 28.27], [85.53, 28.27], [85.53, 28.29], [85.51, 28.27]]
                            ],
                        },
                        "properties": {
                            "id": "su-1",
                            "aoi_id": AOI,
                            "mean_slope_deg": 41.0,
                            "aspect_deg": 180.0,
                            "elevation_band_m": [4200, 5600],
                            "glacier_cover": True,
                            "permafrost_index": 0.8,
                            "geometry_quality": "surveyed",
                            "source_refs": ["test-dem"],
                        },
                    }
                ],
            }
        )
    )
    source = SeracSlopeUnitSource(export_dir=tmp_path, repo_root=repo_root)
    inventory = source.inventory(AOI)
    assert not inventory.is_fallback
    assert inventory.units[0]["mean_slope_deg"] == 41.0


def test_the_contract_mismatch_is_mapped_not_dropped(tmp_path: Path, repo_root: Path) -> None:
    """serac's boolean glacier_cover and [low, high] elevation band map into rupture's fields."""
    export = tmp_path / "slope-units"
    export.mkdir()
    (export / f"{AOI}.geojson").write_text(
        json.dumps(
            {
                "features": [
                    {
                        "geometry": {"type": "Point", "coordinates": [85.52, 28.28]},
                        "properties": {
                            "id": "su-1",
                            "mean_slope_deg": 45.0,
                            "elevation_band_m": [4200, 5600],
                            "glacier_cover": True,
                            "source_refs": ["test-dem"],
                        },
                    }
                ]
            }
        )
    )
    source = SeracSlopeUnitSource(export_dir=tmp_path, repo_root=repo_root)
    record = source.exposure(pga_field([85.52], [28.28], [0.3]), aoi_id=AOI, pga_threshold_g=0.02)
    unit = record.units[0]
    assert unit.glacier_cover == 1.0
    assert unit.elevation_band_m == "4200-5600 m"
    assert unit.exceeds_threshold


def test_the_threshold_screens_and_the_record_says_it_is_only_a_screen(
    source: SeracSlopeUnitSource,
) -> None:
    units = source.units_for(AOI)
    points = [_representative_point(u["geometry"]) for u in units]
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    below = source.exposure(
        pga_field(lons, lats, [0.001] * len(units)), aoi_id=AOI, pga_threshold_g=0.02
    )
    above = source.exposure(
        pga_field(lons, lats, [0.5] * len(units)), aoi_id=AOI, pga_threshold_g=0.02
    )
    assert below.n_exceeding == 0
    assert above.n_exceeding == len(units)
    assert above.kind is CascadeKind.ICE_ROCK_AVALANCHE
    assert "not a failure criterion" in (above.notes or "")
    assert "not a forecast of individual slope failure" in above.label


def test_a_screen_whose_attribute_is_unknown_is_reported_not_applied(
    source: SeracSlopeUnitSource,
) -> None:
    units = source.units_for(AOI)
    points = [_representative_point(u["geometry"]) for u in units]
    record = source.exposure(
        pga_field([p[0] for p in points], [p[1] for p in points], [0.5] * len(units)),
        aoi_id=AOI,
        pga_threshold_g=0.02,
    )
    assert "steepness screen NOT applied" in (record.notes or "")
    assert "glacier screen NOT applied" in (record.notes or "")


def test_a_fallback_exposure_never_claims_published_provenance(
    source: SeracSlopeUnitSource,
) -> None:
    units = source.units_for(AOI)
    points = [_representative_point(u["geometry"]) for u in units]
    record = source.exposure(
        pga_field([p[0] for p in points], [p[1] for p in points], [0.5] * len(units)),
        aoi_id=AOI,
    )
    assert record.provenance is ModelProvenance.ASSUMED
    assert record.confidence is ConfidenceTier.UNQUALIFIED


def test_settlements_below_carries_its_own_caveat(source: SeracSlopeUnitSource) -> None:
    settlements = source.settlements(AOI)
    assert {s[0] for s in settlements} >= {"timure", "syabrubesi", "betrawati"}
    units = source.units_for(AOI)
    points = [_representative_point(u["geometry"]) for u in units]
    record = source.exposure(
        pga_field([p[0] for p in points], [p[1] for p in points], [0.5] * len(units)),
        aoi_id=AOI,
    )
    assert set(record.units[0].settlements_below) == {s[0] for s in settlements}
    assert "not a verified elevation relation" in (record.notes or "")


def test_the_gorkha_scenario_overlay_validates_against_the_contract(repo_root: Path) -> None:
    source = SeracSlopeUnitSource(repo_root=repo_root)
    shakemap = gorkha.load_shakemap(repo_root)
    units = source.units_for(AOI)
    points = [_representative_point(u["geometry"]) for u in units]
    record = source.exposure(
        shakemap.ground_motion_field(
            imt="PGA",
            lons=np.array([p[0] for p in points]),
            lats=np.array([p[1] for p in points]),
            scenario_id=gorkha.EVENT_ID,
        ),
        aoi_id=AOI,
        pga_threshold_g=DEFAULT_PGA_THRESHOLD_G,
    )
    jsonschema.validate(
        record.model_dump(mode="json"), contracts.schema_for("cascade-exposure.v0.json")
    )
    assert record.units[0].pga_g > 0.0
    assert record.pga_threshold_g == DEFAULT_PGA_THRESHOLD_G


def test_exposure_refuses_a_pgv_field(source: SeracSlopeUnitSource) -> None:
    field = pga_field([85.52], [28.28], [0.3])
    pgv = field.model_copy(update={"imt": "PGV"})
    with pytest.raises(ValueError, match="PGA field"):
        source.exposure(pgv, aoi_id=AOI)
