"""``CascadeExposure`` <-> GeoParquet, the layer's published output format.

The brief asks the exposure product to be a **GeoParquet with provenance**, because that is what a
GIS or a serac consumer can overlay; a JSON list of ids with a sampled PGA is not. This module is
the cascade layer's counterpart to :mod:`rupture.adapters.storage.geoparquet` (which does the
same for catalogues) and follows its conventions deliberately: one row per record, EPSG:4326,
tuple fields as JSON strings, and the record-level fields — including the susceptibility label and
every caveat — in the Parquet file's own key-value metadata under the ``rupture:`` prefix.

Layout of ``write_cascade_exposure(exposure, path)``: a single ``.parquet`` file, one row per
:class:`~rupture.domain.cascade.ExposedSlopeUnit`.

* ``geometry`` — the unit's footprint polygon where the slope-unit source carries one, otherwise
  the representative point the PGA was sampled at, otherwise null. A unit with no geometry at all
  is written with a null geometry rather than a made-up one.
* scalar unit fields become columns of the same name; ``settlements_below``, ``assets_below`` and
  ``source_refs`` become ``*_json`` strings.
* the exposure's own fields (scenario, AOI, threshold, slope-unit source, shaking source,
  provenance tier, confidence tier, computed_at, label, notes) are key-value metadata, so a reader
  that only opens the schema still sees the caveat.

``read_cascade_exposure`` reverses the mapping exactly; ``test_cascade_geoparquet_round_trip``
asserts the reconstructed record equals the original.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq
from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry

from rupture.domain.cascade import CascadeExposure, CascadeKind, ExposedSlopeUnit
from rupture.domain.money import ConfidenceTier, ModelProvenance

FORMAT_VERSION = "1"
CONTRACT = "cascade-exposure.v0.json"
METADATA_PREFIX = "rupture:"

STATEMENT = (
    b"susceptibility and exposure, not a forecast of individual slope failure; "
    b"Rupture research output, not an operational alert."
)

_SCALAR_COLUMNS: tuple[str, ...] = (
    "id",
    "aoi_id",
    "mean_slope_deg",
    "glacier_cover",
    "permafrost_index",
    "elevation_band_m",
    "area_m2",
    "representative_longitude",
    "representative_latitude",
    "pga_g",
    "exceeds_threshold",
)
_JSON_COLUMNS: tuple[str, ...] = ("settlements_below", "assets_below", "source_refs")

MIN_RING_POINTS = 4
"""A closed polygon ring needs four positions (three distinct plus the repeat of the first)."""


def _unit_geometry(unit: ExposedSlopeUnit) -> BaseGeometry | None:
    if len(unit.polygon) >= MIN_RING_POINTS:
        return Polygon([(float(lon), float(lat)) for lon, lat in unit.polygon])
    if unit.representative_longitude is not None and unit.representative_latitude is not None:
        return Point(unit.representative_longitude, unit.representative_latitude)
    return None


def _unit_row(unit: ExposedSlopeUnit) -> dict[str, Any]:
    row: dict[str, Any] = {name: getattr(unit, name) for name in _SCALAR_COLUMNS}
    for name in _JSON_COLUMNS:
        row[f"{name}_json"] = json.dumps(list(getattr(unit, name)), separators=(",", ":"))
    return row


def units_frame(units: tuple[ExposedSlopeUnit, ...]) -> gpd.GeoDataFrame:
    """The units as a GeoDataFrame — useful on its own, without touching Parquet."""
    columns = (*_SCALAR_COLUMNS, *(f"{n}_json" for n in _JSON_COLUMNS))
    if not units:
        empty = pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
        return gpd.GeoDataFrame(empty, geometry=[], crs="EPSG:4326")
    frame = pd.DataFrame([_unit_row(u) for u in units])
    frame["exceeds_threshold"] = frame["exceeds_threshold"].astype(bool)
    return gpd.GeoDataFrame(frame, geometry=[_unit_geometry(u) for u in units], crs="EPSG:4326")


def _metadata(exposure: CascadeExposure) -> dict[bytes, bytes]:
    values = {
        "format_version": FORMAT_VERSION,
        "contract": CONTRACT,
        "exposure_id": exposure.id,
        "scenario_id": exposure.scenario_id,
        "aoi_id": exposure.aoi_id,
        "kind": exposure.kind.value,
        "pga_threshold_g": repr(exposure.pga_threshold_g),
        "slope_unit_source": exposure.slope_unit_source,
        "shaking_source": exposure.shaking_source or "",
        "model_provenance": exposure.provenance.value,
        "confidence": exposure.confidence.value,
        "computed_at": exposure.computed_at.isoformat(),
        "label": exposure.label,
        "notes": exposure.notes or "",
        "n_units": str(len(exposure.units)),
        "n_exceeding": str(exposure.n_exceeding),
    }
    encoded = {f"{METADATA_PREFIX}{k}".encode(): v.encode("utf-8") for k, v in values.items()}
    encoded[b"rupture:statement"] = STATEMENT
    return encoded


def write_cascade_exposure(exposure: CascadeExposure, path: Path) -> Path:
    """Write one :class:`CascadeExposure` as GeoParquet, provenance and caveat included."""
    path.parent.mkdir(parents=True, exist_ok=True)
    units_frame(exposure.units).to_parquet(path, index=False, compression="zstd")
    table = pq.read_table(path)
    merged = {**(table.schema.metadata or {}), **_metadata(exposure)}
    pq.write_table(table.replace_schema_metadata(merged), path, compression="zstd")
    return path


def exposure_metadata(path: Path) -> dict[str, str]:
    """The ``rupture:*`` key-value metadata, without reading a single row."""
    raw = pq.read_schema(path).metadata or {}
    return {
        key.decode(): value.decode("utf-8")
        for key, value in raw.items()
        if key.startswith(METADATA_PREFIX.encode())
    }


def _none_if_nan(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _ring(geometry: BaseGeometry | None) -> tuple[tuple[float, float], ...]:
    if geometry is None or geometry.is_empty or not isinstance(geometry, Polygon):
        return ()
    return tuple((float(x), float(y)) for x, y in geometry.exterior.coords)


def _row_unit(row: pd.Series, geometry: BaseGeometry | None) -> ExposedSlopeUnit:
    payload: dict[str, Any] = {
        name: _none_if_nan(row[name]) for name in _SCALAR_COLUMNS if name != "exceeds_threshold"
    }
    payload["exceeds_threshold"] = bool(row["exceeds_threshold"])
    for name in _JSON_COLUMNS:
        payload[name] = tuple(json.loads(row[f"{name}_json"]))
    payload["polygon"] = _ring(geometry)
    payload["pga_g"] = float(row["pga_g"])
    return ExposedSlopeUnit.model_validate(payload)


def read_cascade_exposure(path: Path) -> CascadeExposure:
    """Rebuild the :class:`CascadeExposure` written by :func:`write_cascade_exposure`."""
    meta = exposure_metadata(path)
    frame = gpd.read_parquet(path)
    units = tuple(_row_unit(row, row.get("geometry")) for _, row in frame.iterrows())
    return CascadeExposure(
        id=meta[f"{METADATA_PREFIX}exposure_id"],
        scenario_id=meta[f"{METADATA_PREFIX}scenario_id"],
        aoi_id=meta[f"{METADATA_PREFIX}aoi_id"],
        kind=CascadeKind(meta[f"{METADATA_PREFIX}kind"]),
        pga_threshold_g=float(meta[f"{METADATA_PREFIX}pga_threshold_g"]),
        units=units,
        slope_unit_source=meta[f"{METADATA_PREFIX}slope_unit_source"],
        shaking_source=meta[f"{METADATA_PREFIX}shaking_source"] or None,
        provenance=ModelProvenance(meta[f"{METADATA_PREFIX}model_provenance"]),
        confidence=ConfidenceTier(meta[f"{METADATA_PREFIX}confidence"]),
        computed_at=meta[f"{METADATA_PREFIX}computed_at"],
        label=meta[f"{METADATA_PREFIX}label"],
        notes=meta[f"{METADATA_PREFIX}notes"] or None,
    )


__all__ = [
    "CONTRACT",
    "FORMAT_VERSION",
    "exposure_metadata",
    "read_cascade_exposure",
    "units_frame",
    "write_cascade_exposure",
]
