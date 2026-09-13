"""IRIS FDSN event web service as a thin catalogue ``ObservationSource``.

Documented URL: ``https://service.iris.edu/fdsnws/event/1/query`` (no API key). Adapters
fetch or fail: HTTP errors raise, and an empty successful body is an empty catalogue, never
invented events.

On 2026-09-13 that event path returned HTTP 410 Gone (IRIS still serves ``station`` and
``dataselect``). The adapter keeps the documented URL and fails loudly rather than silently
rerouting. The parser speaks FDSN text, the same column layout ISC already uses.

This is not a prediction source. It is a catalogue port with ``available_as_of``. FDSN text
does not carry a publication stamp, so ``available_time`` is unknown unless a later vintage
store supplies one.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from rupture.adapters.catalogs._common import identity_mw, normalise_magnitude_type
from rupture.adapters.catalogs._http import FetchError, fetch_bytes
from rupture.adapters.observations._asof import catalog_available_as_of
from rupture.domain import (
    Catalog,
    Event,
    EventType,
    MagnitudeRecord,
    Provenance,
    Region,
    VintagePolicy,
    VintageSummary,
    utc_now,
)
from rupture.domain.observation import ObservableKind

log = logging.getLogger(__name__)

SOURCE_ID = "iris-fdsn"
ADAPTER_VERSION = "0.1.0"
# Recorded 2026-09-13: no SPDX on the service index; event query returned 410 Gone.
LICENCE = "no SPDX; IRIS FDSN web services, no API key"
BASE_URL = "https://service.iris.edu/fdsnws/event/1/query"


def map_event_type(raw: str | None) -> EventType:
    """FDSN ``EventType`` words -> :class:`EventType`. Empty means earthquake."""
    if raw is None or not raw.strip():
        return EventType.EARTHQUAKE
    key = raw.strip().lower()
    if "earthquake" in key:
        return EventType.EARTHQUAKE
    if "explosion" in key or "blast" in key:
        return EventType.EXPLOSION
    if any(word in key for word in ("landslide", "rockslide", "avalanche", "slide")):
        return EventType.LANDSLIDE
    return EventType.OTHER


def _parse_time(text: str) -> datetime:
    parsed = datetime.fromisoformat(text.strip())
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _opt_float(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def parse_fdsn_text(
    payload: bytes | str,
    *,
    provenance: Provenance,
    source_id: str = SOURCE_ID,
) -> list[Event]:
    """Pure parser for FDSN event text (``#EventID|Time|...``).

    Rows without a magnitude are skipped and logged. Nothing is synthesised. FDSN text has no
    publication stamp, so ``available_time`` is left ``None``.
    """
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    lines = text.splitlines()
    header: list[str] | None = None
    events: list[Event] = []
    for raw in lines:
        line = raw.rstrip("\r")
        if not line.strip():
            continue
        if line.startswith("#"):
            if line.startswith("#EventID|") or line.startswith("# EventID|"):
                header = [h.strip().lstrip("#").strip() for h in line.split("|")]
            continue
        if header is None:
            msg = "FDSN text payload has data rows before its #EventID header"
            raise ValueError(msg)
        if "|" not in line:
            log.warning("iris-fdsn: skipped non-data line %r", line[:80])
            continue
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 12:
            msg = f"FDSN row has {len(cols)} columns, expected >= 12: {line[:120]}"
            raise ValueError(msg)
        row = dict(zip(header, cols, strict=False))
        eid = row["EventID"]
        mag_text = row.get("Magnitude", "")
        if not mag_text:
            log.warning("iris-fdsn: skipped event %s: no magnitude", eid)
            continue
        mag_value = float(mag_text)
        raw_type = row.get("MagType") or None
        mag_type = normalise_magnitude_type(raw_type)
        mw, conv = identity_mw(mag_type, mag_value)
        events.append(
            Event(
                id=f"{source_id}:{eid}",
                origin_time=_parse_time(row["Time"]),
                latitude=float(row["Latitude"]),
                longitude=float(row["Longitude"]),
                depth_km=_opt_float(row.get("Depth/km", "")),
                magnitude=MagnitudeRecord(
                    value=mag_value,
                    type=mag_type,
                    agency=row.get("MagAuthor") or None,
                    raw_type=raw_type,
                ),
                mw=mw,
                mw_conversion=conv,
                event_type=map_event_type(row.get("EventType")),
                source_catalog=source_id,
                source_event_id=eid,
                contributing_ids=(f"{source_id}:{eid}",),
                provenance=provenance,
            )
        )
    if header is None and any(ln.strip() for ln in lines):
        msg = "FDSN text payload has no #EventID header"
        raise ValueError(msg)
    events.sort(key=lambda e: (e.origin_time, e.source_event_id))
    return events


def query_url(
    region: Region, start: datetime, end: datetime, *, min_magnitude: float | None
) -> str:
    """Exact IRIS FDSN event URL (recorded in provenance)."""
    min_lon, min_lat, max_lon, max_lat = region.bbox()
    params: dict[str, str] = {
        "format": "text",
        "starttime": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "minlongitude": f"{min_lon:.4f}",
        "maxlongitude": f"{max_lon:.4f}",
        "minlatitude": f"{min_lat:.4f}",
        "maxlatitude": f"{max_lat:.4f}",
    }
    if min_magnitude is not None:
        params["minmagnitude"] = f"{min_magnitude:g}"
    return f"{BASE_URL}?{urlencode(params)}"


class FdsnEventSource:
    """Thin IRIS FDSN event adapter. Fetch or fail; do not invent events.

    Implements :class:`~rupture.ports.observation_source.ObservationSource` once a catalogue
    has been fetched or supplied. ``available_time`` is unknown on FDSN text, so
    ``EXCLUDE_UNKNOWN`` empties the as-of view.
    """

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION
    kind = ObservableKind.CATALOGUE_EVENT

    def __init__(
        self,
        *,
        offline_fixtures: Path | None = None,
        cache_dir: Path | None = None,
        catalog: Catalog | None = None,
    ) -> None:
        self.offline_fixtures = offline_fixtures
        self.cache_dir = cache_dir
        self._catalog = catalog

    def fetch(
        self,
        region: Region,
        start: datetime,
        end: datetime,
        *,
        min_magnitude: float | None = None,
    ) -> Catalog:
        if end <= start:
            msg = "end must be after start"
            raise ValueError(msg)
        url = query_url(region, start, end, min_magnitude=min_magnitude)
        payload = fetch_bytes(
            url, cache_dir=self.cache_dir, ok_statuses=frozenset({200, 204})
        )
        if payload.status_code not in {200, 204}:
            msg = f"IRIS FDSN event query returned HTTP {payload.status_code} for {url}"
            raise FetchError(msg)
        if payload.status_code == 204 or not payload.content.strip():
            events: list[Event] = []
        else:
            prov = Provenance(
                source=SOURCE_ID,
                source_url=payload.url,
                retrieved_at=payload.retrieved_at,
                sha256=payload.sha256,
                licence=LICENCE,
                adapter_version=ADAPTER_VERSION,
            )
            events = parse_fdsn_text(payload.content, provenance=prov)
        catalog = Catalog(
            id=f"{SOURCE_ID}/{region.id}/{start.isoformat()}/{end.isoformat()}",
            region_id=region.id,
            events=tuple(events),
            sources=(SOURCE_ID,),
            built_at=utc_now(),
            builder_version=ADAPTER_VERSION,
            notes=f"IRIS FDSN event query {url}",
        )
        self._catalog = catalog
        return catalog

    def _load(self) -> Catalog:
        if self._catalog is None:
            msg = (
                "no FDSN catalogue loaded; call fetch(...) or pass catalog= "
                "(the IRIS event path returned HTTP 410 Gone on 2026-09-13)"
            )
            raise RuntimeError(msg)
        return self._catalog

    def available_as_of(self, instant: datetime, *, policy: VintagePolicy) -> Catalog:
        return catalog_available_as_of(self._load(), instant, policy)

    def vintage(self, reference_time: datetime | None = None) -> VintageSummary:
        return self._load().vintage_summary(reference_time)
