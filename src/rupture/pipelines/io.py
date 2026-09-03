"""File I/O for pipelines: catalogues, regions, evaluation results, UTC parsing.

Catalogue directories are read and written by the GeoParquet writer in
``rupture.adapters.storage.geoparquet`` (``events.parquet`` + ``catalog.meta.json`` +
``homogenisation_log.jsonl``); that module's column layout is authoritative and this one only
re-exports it so pipelines and commands have a single import point. ``target.parquet`` archives
use the same events layout.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from rupture.adapters.storage import geoparquet
from rupture.domain import Catalog, EvaluationResult, Event, Region

EVENTS_FILE = geoparquet.EVENTS_FILE
META_FILE = geoparquet.META_FILE
LOG_FILE = geoparquet.LOG_FILE
REGION_FILE = "region.json"


def parse_utc(text: str) -> datetime:
    """ISO 8601 -> aware UTC datetime; a trailing ``Z`` is accepted, a naive value is UTC."""
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# ---------------------------------------------------------------------- events
def write_events_parquet(events: Iterable[Event], path: Path) -> Path:
    """Events in the GeoParquet writer's layout (used for ``target.parquet`` archives)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    geoparquet.events_frame(tuple(events)).to_parquet(path, index=False, compression="zstd")
    return path


def read_events_parquet(path: Path) -> list[Event]:
    return list(geoparquet.read_events(Path(path)))


# ---------------------------------------------------------------------- catalogues
def save_catalog(catalog: Catalog, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    geoparquet.write_catalog(catalog, out_dir)
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
    return geoparquet.read_catalog(directory)


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
