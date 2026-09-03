"""File I/O for pipelines: catalogues (Parquet + JSON), regions, fit results, evaluation results.

Catalogue directory layout (the names the catalogue writer must converge on):

- ``events.parquet`` — one row per event, flat columns (see :data:`EVENT_COLUMNS`); nested
  fields (``other_magnitudes``, ``contributing_ids``) are JSON strings; ``provenance.*`` is
  flattened to ``provenance_<field>``. A ``geometry`` column, if present (GeoParquet), is ignored.
- ``catalog.meta.json`` — the ``Catalog`` record without ``events`` and ``homogenisation_log``.
- ``homogenisation_log.jsonl`` — one ``HomogenisationLogEntry`` per line.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from rupture.domain import Catalog, EvaluationResult, Event, HomogenisationLogEntry, Region

EVENTS_FILE = "events.parquet"
META_FILE = "catalog.meta.json"
LOG_FILE = "homogenisation_log.jsonl"
REGION_FILE = "region.json"

_MAGNITUDE_FIELDS = ("value", "type", "agency", "uncertainty", "raw_type")
_PROVENANCE_FIELDS = (
    "source",
    "source_url",
    "retrieved_at",
    "sha256",
    "licence",
    "adapter_version",
    "notes",
)
_JSON_FIELDS = ("other_magnitudes", "contributing_ids")
EVENT_COLUMNS: tuple[str, ...] = (
    "id",
    "origin_time",
    "origin_time_uncertainty_s",
    "latitude",
    "longitude",
    "horizontal_uncertainty_km",
    "depth_km",
    "depth_uncertainty_km",
    *(f"magnitude_{f}" for f in _MAGNITUDE_FIELDS),
    "other_magnitudes",
    "mw",
    "mw_conversion",
    "event_type",
    "source_catalog",
    "source_event_id",
    "contributing_ids",
    *(f"provenance_{f}" for f in _PROVENANCE_FIELDS),
)


def parse_utc(text: str) -> datetime:
    """ISO 8601 -> aware UTC datetime; a trailing ``Z`` is accepted, a naive value is UTC."""
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ---------------------------------------------------------------------- events
def events_to_frame(events: Iterable[Event]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for e in events:
        d = e.model_dump(mode="json")
        row: dict[str, Any] = {}
        for col in EVENT_COLUMNS:
            if col.startswith("magnitude_"):
                row[col] = d["magnitude"][col[len("magnitude_") :]]
            elif col.startswith("provenance_"):
                row[col] = d["provenance"][col[len("provenance_") :]]
            elif col in _JSON_FIELDS:
                row[col] = json.dumps(d[col], sort_keys=True, separators=(",", ":"))
            else:
                row[col] = d[col]
        rows.append(row)
    df = pd.DataFrame(rows, columns=list(EVENT_COLUMNS))
    if len(df):
        # ISO strings mix fractional and whole seconds; tell pandas not to infer one format.
        df["origin_time"] = pd.to_datetime(df["origin_time"], utc=True, format="ISO8601")
        df["provenance_retrieved_at"] = pd.to_datetime(
            df["provenance_retrieved_at"], utc=True, format="ISO8601"
        )
    return df


def _clean(value: Any) -> Any:
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, pd.Timestamp):
        ts = value.tz_convert("UTC") if value.tzinfo else value.tz_localize("UTC")
        return ts.isoformat()
    if hasattr(value, "item") and not isinstance(value, (bytes, str)):
        return value.item()
    return value


def frame_to_events(df: pd.DataFrame) -> list[Event]:
    missing = [c for c in EVENT_COLUMNS if c not in df.columns]
    if missing:
        msg = f"events table lacks columns {missing}"
        raise ValueError(msg)
    out: list[Event] = []
    for rec in df[list(EVENT_COLUMNS)].to_dict(orient="records"):
        payload: dict[str, Any] = {"magnitude": {}, "provenance": {}}
        for col in EVENT_COLUMNS:
            value = _clean(rec[col])
            if col.startswith("magnitude_"):
                payload["magnitude"][col[len("magnitude_") :]] = value
            elif col.startswith("provenance_"):
                payload["provenance"][col[len("provenance_") :]] = value
            elif col in _JSON_FIELDS:
                payload[col] = json.loads(value) if value else []
            else:
                payload[col] = value
        out.append(Event.model_validate(payload))
    return out


def write_events_parquet(events: Iterable[Event], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    events_to_frame(events).to_parquet(path, index=False)
    return path


def read_events_parquet(path: Path) -> list[Event]:
    df = pd.read_parquet(path)
    if "geometry" in df.columns:
        df = df.drop(columns=["geometry"])
    return frame_to_events(df)


# ---------------------------------------------------------------------- catalogues
def save_catalog(catalog: Catalog, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_events_parquet(catalog.events, out_dir / EVENTS_FILE)
    meta = catalog.model_dump(mode="json", exclude={"events", "homogenisation_log"})
    (out_dir / META_FILE).write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (out_dir / LOG_FILE).open("w", encoding="utf-8") as fh:
        for entry in catalog.homogenisation_log:
            fh.write(entry.canonical_json())
            fh.write("\n")
    return out_dir


def load_catalog(path: Path) -> Catalog:
    """Load a catalogue directory (or the path of its ``events.parquet``)."""
    path = Path(path)
    directory = path.parent if path.is_file() else path
    events_path = directory / EVENTS_FILE
    meta_path = directory / META_FILE
    if not events_path.exists() or not meta_path.exists():
        msg = f"catalogue directory {directory} needs {EVENTS_FILE} and {META_FILE}"
        raise FileNotFoundError(msg)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["events"] = [e.model_dump(mode="json") for e in read_events_parquet(events_path)]
    log_path = directory / LOG_FILE
    if log_path.exists():
        meta["homogenisation_log"] = [
            HomogenisationLogEntry.model_validate_json(ln).model_dump(mode="json")
            for ln in log_path.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
    return Catalog.model_validate(meta)


# ---------------------------------------------------------------------- regions
def load_region(path: Path) -> Region:
    """Read ``region.json`` (a ``Region`` record or the GeoJSON Feature ``to_geojson`` writes)."""
    path = Path(path)
    if path.is_dir():
        path = path / REGION_FILE
    if not path.exists():
        msg = f"no region file at {path}"
        raise FileNotFoundError(msg)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("type") == "Feature":
        props = dict(raw["properties"])
        ring = [tuple(p) for p in raw["geometry"]["coordinates"][0]]
        if len(ring) > 3 and ring[0] == ring[-1]:
            ring = ring[:-1]  # GeoJSON rings are closed; Region stores the open ring
        props["polygon"] = ring
        return Region.model_validate(props)
    return Region.model_validate(raw)


# ---------------------------------------------------------------------- evaluation results
def save_results(results: Iterable[EvaluationResult], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [r.model_dump(mode="json") for r in results]
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_results(path: Path) -> list[EvaluationResult]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [EvaluationResult.model_validate(r) for r in raw]
