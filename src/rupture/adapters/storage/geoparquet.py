"""``Catalog`` <-> GeoParquet directory (ADR-0012).

Layout of ``write_catalog(catalog, directory)``::

    <directory>/events.parquet            one row per event, GeoParquet (EPSG:4326 points)
    <directory>/catalog.meta.json         the Catalog minus events (model_dump, JSON)
    <directory>/homogenisation_log.jsonl  one HomogenisationLogEntry per line

Column mapping for ``events.parquet``: every scalar ``Event`` field is a flat column with the
same name; the preferred magnitude is flattened to ``magnitude_value``, ``magnitude_type``,
``magnitude_agency``, ``magnitude_uncertainty``, ``magnitude_raw_type``; ``other_magnitudes``,
``contributing_ids`` and ``provenance`` are JSON strings (``*_json``); ``geometry`` is the
epicentre. Timestamps are stored as UTC ``timestamp[us]``. Parquet key-value metadata carries the
catalogue id, builder version, sources and the licences of every source seen.

``read_catalog`` reverses the mapping exactly; ``test_geoparquet_round_trip`` asserts equality.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyarrow.parquet as pq
from shapely.geometry import Point

from rupture.domain import (
    Catalog,
    Event,
    EventType,
    HomogenisationLogEntry,
    MagnitudeRecord,
    MagnitudeType,
    Provenance,
)

EVENTS_FILE = "events.parquet"
META_FILE = "catalog.meta.json"
LOG_FILE = "homogenisation_log.jsonl"
FORMAT_VERSION = "1"

_SCALAR_COLUMNS: tuple[str, ...] = (
    "id",
    "origin_time",
    "origin_time_uncertainty_s",
    "latitude",
    "longitude",
    "horizontal_uncertainty_km",
    "depth_km",
    "depth_uncertainty_km",
    "mw",
    "mw_conversion",
    "event_type",
    "source_catalog",
    "source_event_id",
)


def _event_row(e: Event) -> dict[str, Any]:
    row: dict[str, Any] = {c: getattr(e, c) for c in _SCALAR_COLUMNS}
    row["event_type"] = e.event_type.value
    row["magnitude_value"] = e.magnitude.value
    row["magnitude_type"] = e.magnitude.type.value
    row["magnitude_agency"] = e.magnitude.agency
    row["magnitude_uncertainty"] = e.magnitude.uncertainty
    row["magnitude_raw_type"] = e.magnitude.raw_type
    row["other_magnitudes_json"] = json.dumps(
        [m.model_dump(mode="json") for m in e.other_magnitudes], separators=(",", ":")
    )
    row["contributing_ids_json"] = json.dumps(list(e.contributing_ids), separators=(",", ":"))
    row["provenance_json"] = e.provenance.canonical_json()
    return row


def events_frame(events: tuple[Event, ...]) -> gpd.GeoDataFrame:
    """Events as a GeoDataFrame (also handy for analysis without touching Parquet)."""
    rows = [_event_row(e) for e in events]
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            {
                c: pd.Series(dtype="object")
                for c in (
                    *_SCALAR_COLUMNS,
                    "magnitude_value",
                    "magnitude_type",
                    "magnitude_agency",
                    "magnitude_uncertainty",
                    "magnitude_raw_type",
                    "other_magnitudes_json",
                    "contributing_ids_json",
                    "provenance_json",
                )
            }
        )
        geometry: list[Point] = []
    else:
        df["origin_time"] = pd.to_datetime(df["origin_time"], utc=True).astype(
            "datetime64[us, UTC]"
        )
        geometry = [
            Point(lon, lat) for lon, lat in zip(df["longitude"], df["latitude"], strict=True)
        ]
    return gpd.GeoDataFrame(df, geometry=geometry, crs="EPSG:4326")


def write_catalog(catalog: Catalog, directory: Path) -> dict[str, Path]:
    """Write the three files; returns their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    gdf = events_frame(catalog.events)
    events_path = directory / EVENTS_FILE
    gdf.to_parquet(events_path, index=False, compression="zstd")
    # add catalogue-level key/value metadata without disturbing the geo metadata
    table = pq.read_table(events_path)
    licences = sorted({e.provenance.licence for e in catalog.events if e.provenance.licence})
    extra = {
        b"rupture:format_version": FORMAT_VERSION.encode(),
        b"rupture:catalog_id": catalog.id.encode(),
        b"rupture:region_id": (catalog.region_id or "").encode(),
        b"rupture:builder_version": catalog.builder_version.encode(),
        b"rupture:sources": json.dumps(list(catalog.sources)).encode(),
        b"rupture:licences": json.dumps(licences).encode(),
        b"rupture:built_at": catalog.built_at.isoformat().encode(),
        b"rupture:statement": b"Rupture research output, not an operational alert.",
    }
    merged = {**(table.schema.metadata or {}), **extra}
    pq.write_table(table.replace_schema_metadata(merged), events_path, compression="zstd")

    meta_path = directory / META_FILE
    meta = catalog.model_dump(mode="json", exclude={"events", "homogenisation_log"})
    meta["n_events"] = len(catalog.events)
    meta["n_log_entries"] = len(catalog.homogenisation_log)
    meta["event_hash"] = catalog.event_hash()
    meta["files"] = {"events": EVENTS_FILE, "homogenisation_log": LOG_FILE}
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    log_path = directory / LOG_FILE
    with log_path.open("w", encoding="utf-8") as fh:
        for entry in catalog.homogenisation_log:
            fh.write(entry.canonical_json() + "\n")
    return {"events": events_path, "meta": meta_path, "log": log_path}


def _none_if_nan(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def _row_event(row: pd.Series) -> Event:
    other = tuple(
        MagnitudeRecord.model_validate(m) for m in json.loads(row["other_magnitudes_json"])
    )
    ts = row["origin_time"]
    origin = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
    if origin.tzinfo is None:
        origin = origin.replace(tzinfo=UTC)
    return Event(
        id=row["id"],
        origin_time=origin,
        origin_time_uncertainty_s=_none_if_nan(row["origin_time_uncertainty_s"]),
        latitude=float(row["latitude"]),
        longitude=float(row["longitude"]),
        horizontal_uncertainty_km=_none_if_nan(row["horizontal_uncertainty_km"]),
        depth_km=_none_if_nan(row["depth_km"]),
        depth_uncertainty_km=_none_if_nan(row["depth_uncertainty_km"]),
        magnitude=MagnitudeRecord(
            value=float(row["magnitude_value"]),
            type=MagnitudeType(row["magnitude_type"]),
            agency=_none_if_nan(row["magnitude_agency"]),
            uncertainty=_none_if_nan(row["magnitude_uncertainty"]),
            raw_type=_none_if_nan(row["magnitude_raw_type"]),
        ),
        other_magnitudes=other,
        mw=_none_if_nan(row["mw"]),
        mw_conversion=_none_if_nan(row["mw_conversion"]),
        event_type=EventType(row["event_type"]),
        source_catalog=row["source_catalog"],
        source_event_id=row["source_event_id"],
        contributing_ids=tuple(json.loads(row["contributing_ids_json"])),
        provenance=Provenance.model_validate_json(row["provenance_json"]),
    )


def read_events(events_path: Path) -> tuple[Event, ...]:
    gdf = gpd.read_parquet(events_path)
    if gdf.empty:
        return ()
    return tuple(_row_event(row) for _, row in gdf.iterrows())


def read_log(log_path: Path) -> tuple[HomogenisationLogEntry, ...]:
    if not log_path.exists():
        return ()
    with log_path.open(encoding="utf-8") as fh:
        return tuple(HomogenisationLogEntry.model_validate_json(ln) for ln in fh if ln.strip())


def read_catalog(directory: Path) -> Catalog:
    """Rebuild the ``Catalog`` from a directory written by :func:`write_catalog`."""
    meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
    for k in ("n_events", "n_log_entries", "event_hash", "files"):
        meta.pop(k, None)
    events = read_events(directory / EVENTS_FILE)
    log = read_log(directory / LOG_FILE)
    return Catalog.model_validate({**meta, "events": events, "homogenisation_log": log})


def parquet_metadata(events_path: Path) -> dict[str, str]:
    """The ``rupture:*`` key-value metadata written alongside the geo metadata."""
    md = pq.read_schema(events_path).metadata or {}
    return {k.decode(): v.decode() for k, v in md.items() if k.startswith(b"rupture:")}


def utc(ts: datetime) -> datetime:
    return ts.astimezone(UTC)


__all__ = [
    "EVENTS_FILE",
    "LOG_FILE",
    "META_FILE",
    "events_frame",
    "parquet_metadata",
    "read_catalog",
    "read_events",
    "read_log",
    "write_catalog",
]
