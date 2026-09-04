"""``CascadeExposure`` as GeoParquet: the layer's published output format.

The brief specifies a GeoParquet with provenance, so these tests hold the writer to that: the
round trip is exact, the geometry is real and in EPSG:4326, and the caveat and the provenance sit
in the file's own key-value metadata where a reader who never opens a row still sees them.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import pytest

from rupture.adapters.cascade import chamoli
from rupture.adapters.cascade.geoparquet import (
    exposure_metadata,
    read_cascade_exposure,
    units_frame,
    write_cascade_exposure,
)
from rupture.domain.cascade import CascadeExposure, CascadeKind, ExposedSlopeUnit
from rupture.domain.money import ConfidenceTier, ModelProvenance

RING = ((79.68, 30.33), (79.80, 30.33), (79.80, 30.42), (79.68, 30.42), (79.68, 30.33))


def record(**overrides: object) -> CascadeExposure:
    unit = ExposedSlopeUnit(
        id="unit-0",
        aoi_id="chamoli-rishiganga",
        mean_slope_deg=None,
        glacier_cover=None,
        permafrost_index=None,
        elevation_band_m=None,
        area_m2=None,
        polygon=RING,
        representative_longitude=79.74,
        representative_latitude=30.375,
        pga_g=0.4274,
        exceeds_threshold=True,
        settlements_below=(),
        assets_below=("rishiganga-hep (hydropower_plant)",),
        source_refs=("osm-overpass-chamoli-rishiganga",),
    )
    payload: dict[str, object] = {
        "id": "cascade-exposure-test",
        "scenario_id": "scenario-x",
        "aoi_id": "chamoli-rishiganga",
        "kind": CascadeKind.ICE_ROCK_AVALANCHE,
        "pga_threshold_g": 0.02,
        "units": (unit,),
        "slope_unit_source": "serac-aoi-fallback:chamoli-rishiganga",
        "shaking_source": "field-1",
        "provenance": ModelProvenance.ASSUMED,
        "confidence": ConfidenceTier.UNQUALIFIED,
        "computed_at": datetime(2026, 9, 3, 12, tzinfo=UTC),
        "notes": "screening threshold 0.02 g; a threshold is a screening device",
    }
    payload.update(overrides)
    return CascadeExposure.model_validate(payload)


def test_the_round_trip_is_exact(tmp_path: Path) -> None:
    original = record()
    path = write_cascade_exposure(original, tmp_path / "exposure.parquet")
    assert read_cascade_exposure(path) == original


def test_the_geometry_is_the_units_footprint_in_wgs84(tmp_path: Path) -> None:
    path = write_cascade_exposure(record(), tmp_path / "exposure.parquet")
    frame = gpd.read_parquet(path)
    assert frame.crs is not None
    assert frame.crs.to_string() == "EPSG:4326"
    geometry = frame.geometry.iloc[0]
    assert geometry.geom_type == "Polygon"
    assert geometry.bounds == pytest.approx((79.68, 30.33, 79.80, 30.42))


def test_a_unit_without_a_polygon_falls_back_to_its_representative_point(tmp_path: Path) -> None:
    original = record()
    pointish = original.model_copy(
        update={"units": (original.units[0].model_copy(update={"polygon": ()}),)}
    )
    path = write_cascade_exposure(pointish, tmp_path / "point.parquet")
    assert gpd.read_parquet(path).geometry.iloc[0].geom_type == "Point"
    assert read_cascade_exposure(path) == pointish


def test_a_unit_with_no_geometry_at_all_is_written_null_not_invented(tmp_path: Path) -> None:
    original = record()
    bare = original.model_copy(
        update={
            "units": (
                original.units[0].model_copy(
                    update={
                        "polygon": (),
                        "representative_longitude": None,
                        "representative_latitude": None,
                    }
                ),
            )
        }
    )
    path = write_cascade_exposure(bare, tmp_path / "bare.parquet")
    assert gpd.read_parquet(path).geometry.iloc[0] is None
    assert read_cascade_exposure(path) == bare


def test_the_metadata_carries_the_caveat_and_the_provenance(tmp_path: Path) -> None:
    path = write_cascade_exposure(record(), tmp_path / "exposure.parquet")
    metadata = exposure_metadata(path)
    assert "susceptibility" in metadata["rupture:label"]
    assert "not a forecast of individual slope failure" in metadata["rupture:label"]
    assert metadata["rupture:scenario_id"] == "scenario-x"
    assert metadata["rupture:aoi_id"] == "chamoli-rishiganga"
    assert metadata["rupture:slope_unit_source"] == "serac-aoi-fallback:chamoli-rishiganga"
    assert metadata["rupture:model_provenance"] == ModelProvenance.ASSUMED.value
    assert metadata["rupture:confidence"] == ConfidenceTier.UNQUALIFIED.value
    assert metadata["rupture:shaking_source"] == "field-1"
    assert metadata["rupture:n_units"] == "1"
    assert metadata["rupture:contract"] == "cascade-exposure.v0.json"
    assert "does not predict" in metadata["rupture:statement"]  # lang-gate: allow


def test_the_threshold_survives_as_a_float_not_a_rounded_string(tmp_path: Path) -> None:
    original = record(pga_threshold_g=0.017_357_913)
    path = write_cascade_exposure(original, tmp_path / "exposure.parquet")
    assert read_cascade_exposure(path).pga_threshold_g == original.pga_threshold_g


def test_an_exposure_with_no_units_still_writes_and_reads(tmp_path: Path) -> None:
    empty = record(units=())
    path = write_cascade_exposure(empty, tmp_path / "empty.parquet")
    assert read_cascade_exposure(path) == empty
    assert exposure_metadata(path)["rupture:n_units"] == "0"


def test_the_frame_is_usable_on_its_own() -> None:
    frame = units_frame(record().units)
    assert list(frame.columns)[-1] == "geometry"
    assert frame.loc[0, "pga_g"] == pytest.approx(0.4274)
    assert frame.loc[0, "assets_below_json"] == '["rishiganga-hep (hydropower_plant)"]'


def test_the_real_chamoli_exposure_round_trips(repo_root: Path, tmp_path: Path) -> None:
    original = chamoli.run_exposure(repo_root)
    path = write_cascade_exposure(original, tmp_path / "chamoli.parquet")
    restored = read_cascade_exposure(path)
    assert restored == original
    assert restored.units[0].assets_below
    assert gpd.read_parquet(path).geometry.iloc[0].geom_type == "Polygon"
