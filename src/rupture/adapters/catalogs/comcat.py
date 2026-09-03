"""USGS ComCat (ANSS Comprehensive Earthquake Catalog) via the FDSN event service, GeoJSON.

GeoJSON is used rather than QuakeML because it carries ``properties.type`` (``earthquake``,
``landslide``, ``explosion``, ``quarry blast``, ...), ``magType``, ``net`` and ``status``
(ADR-0004). Landslide-type entries such as ``us7000tbwb`` are retained and tagged
:attr:`EventType.LANDSLIDE`; nothing is dropped for its type.

Two layers:

* :func:`parse_comcat_geojson` — pure: raw payload bytes -> ``list[Event]``. Unit tests run this
  on committed fixtures.
* :class:`ComCatSource` — thin fetch layer implementing the ``CatalogSource`` port. It pages by
  time to respect the service's 20 000-event limit (``count`` first, then bisect the window).

The summary GeoJSON feed has no uncertainty fields; ``horizontalError``, ``depthError``,
``magError`` and ``timeError`` are read when present (detail/extended feeds) and are ``None``
otherwise. Depth is km in ``geometry.coordinates[2]``.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from rupture.adapters.catalogs._common import (
    filter_events,
    identity_mw,
    normalise_magnitude_type,
)
from rupture.adapters.catalogs._http import FetchError, fetch_bytes
from rupture.adapters.catalogs.fixtures import load_fixture_dir
from rupture.domain import (
    Catalog,
    Event,
    EventType,
    MagnitudeRecord,
    Provenance,
    Region,
    utc_now,
)

log = logging.getLogger(__name__)

SOURCE_ID = "usgs-comcat"
ADAPTER_VERSION = "0.1.0"
LICENCE = "public-domain (USGS)"
BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1"
PAGE_LIMIT = 20_000

# ComCat ``type`` -> rupture EventType. Mass movements are LANDSLIDE; anthropogenic blasts are
# EXPLOSION; everything else that is not an earthquake (rock bursts, mine collapses, ice quakes,
# volcanic eruptions, sonic booms, "not reported", ...) is OTHER. Unknown strings are OTHER and the
# raw string is kept in the homogenisation log by the pipeline. See docs/CATALOG_BUILD.md.
EVENT_TYPE_MAP: dict[str, EventType] = {
    "earthquake": EventType.EARTHQUAKE,
    "landslide": EventType.LANDSLIDE,
    "rockslide": EventType.LANDSLIDE,
    "avalanche": EventType.LANDSLIDE,
    "snow avalanche": EventType.LANDSLIDE,
    "debris flow": EventType.LANDSLIDE,
    "explosion": EventType.EXPLOSION,
    "quarry blast": EventType.EXPLOSION,
    "quarry": EventType.EXPLOSION,
    "mining explosion": EventType.EXPLOSION,
    "mine explosion": EventType.EXPLOSION,
    "nuclear explosion": EventType.EXPLOSION,
    "chemical explosion": EventType.EXPLOSION,
    "experimental explosion": EventType.EXPLOSION,
    "rock burst": EventType.OTHER,
    "mine collapse": EventType.OTHER,
    "collapse": EventType.OTHER,
    "ice quake": EventType.OTHER,
    "volcanic eruption": EventType.OTHER,
    "sonic boom": EventType.OTHER,
    "induced or triggered event": EventType.OTHER,
    "not reported": EventType.OTHER,
    "other event": EventType.OTHER,
}


def map_event_type(raw: str | None) -> EventType:
    """ComCat ``properties.type`` -> :class:`EventType` (unknown -> OTHER, never dropped)."""
    if raw is None:
        return EventType.EARTHQUAKE
    return EVENT_TYPE_MAP.get(raw.strip().lower().replace("_", " "), EventType.OTHER)


@dataclass(frozen=True, slots=True)
class ParseReport:
    """Events parsed from one payload plus the feature ids skipped and why."""

    events: list[Event]
    skipped: list[tuple[str, str]]


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_comcat_geojson_report(payload: bytes | str, *, provenance: Provenance) -> ParseReport:
    """Parse a ComCat GeoJSON FeatureCollection; skip only features without a magnitude or time.

    Skips are reported, never silent: a feature with ``mag == null`` cannot become an ``Event``
    (the domain requires a preferred magnitude) and is listed in ``skipped`` with the reason.
    """
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    doc = json.loads(text)
    if doc.get("type") != "FeatureCollection":
        msg = f"not a GeoJSON FeatureCollection (type={doc.get('type')!r})"
        raise ValueError(msg)
    events: list[Event] = []
    skipped: list[tuple[str, str]] = []
    for feat in doc.get("features", []):
        fid = str(feat.get("id"))
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if props.get("mag") is None:
            skipped.append((fid, "no magnitude"))
            continue
        if props.get("time") is None or len(coords) < 2:
            skipped.append((fid, "no time or coordinates"))
            continue
        origin = datetime.fromtimestamp(props["time"] / 1000.0, tz=UTC)
        mag_type = normalise_magnitude_type(props.get("magType"))
        mag_value = float(props["mag"])
        mw, conv = identity_mw(mag_type, mag_value)
        record = MagnitudeRecord(
            value=mag_value,
            type=mag_type,
            agency=props.get("net"),
            uncertainty=_opt_float(props.get("magError")),
            raw_type=props.get("magType"),
        )
        depth = _opt_float(coords[2]) if len(coords) > 2 else None
        events.append(
            Event(
                id=f"{SOURCE_ID}:{fid}",
                origin_time=origin,
                origin_time_uncertainty_s=_opt_float(props.get("timeError")),
                latitude=float(coords[1]),
                longitude=float(coords[0]),
                horizontal_uncertainty_km=_opt_float(props.get("horizontalError")),
                depth_km=depth,
                depth_uncertainty_km=_opt_float(props.get("depthError")),
                magnitude=record,
                mw=mw,
                mw_conversion=conv,
                event_type=map_event_type(props.get("type")),
                source_catalog=SOURCE_ID,
                source_event_id=fid,
                contributing_ids=(f"{SOURCE_ID}:{fid}",),
                provenance=provenance,
            )
        )
    return ParseReport(events=events, skipped=skipped)


def parse_comcat_geojson(payload: bytes | str, *, provenance: Provenance) -> list[Event]:
    """Pure parser: ComCat GeoJSON bytes -> events (see :func:`parse_comcat_geojson_report`)."""
    report = parse_comcat_geojson_report(payload, provenance=provenance)
    for fid, why in report.skipped:
        log.warning("comcat: skipped feature %s: %s", fid, why)
    return report.events


def query_url(
    region: Region,
    start: datetime,
    end: datetime,
    *,
    min_magnitude: float | None,
    endpoint: str = "query",
) -> str:
    """The exact ComCat URL for a bbox/time/magnitude query (recorded in provenance)."""
    min_lon, min_lat, max_lon, max_lat = region.bbox()
    params: dict[str, str] = {
        "format": "geojson",
        "starttime": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "endtime": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "minlongitude": f"{min_lon:.4f}",
        "maxlongitude": f"{max_lon:.4f}",
        "minlatitude": f"{min_lat:.4f}",
        "maxlatitude": f"{max_lat:.4f}",
        "orderby": "time-asc",
    }
    if min_magnitude is not None:
        params["minmagnitude"] = f"{min_magnitude:g}"
    if endpoint == "query":
        params["limit"] = str(PAGE_LIMIT)
    return f"{BASE_URL}/{endpoint}?{urlencode(params)}"


class ComCatSource:
    """``CatalogSource`` for ComCat. Online by default; ``offline_fixtures`` reads committed
    files."""

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        *,
        offline_fixtures: Path | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.offline_fixtures = offline_fixtures
        self.cache_dir = cache_dir

    # ------------------------------------------------------------------ port
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
        if self.offline_fixtures is not None:
            events = self._from_fixtures(region, start, end, min_magnitude=min_magnitude)
            note = f"offline fixtures from {self.offline_fixtures}"
        else:
            events = self._fetch_window(region, start, end, min_magnitude=min_magnitude)
            note = "online ComCat FDSN GeoJSON"
        events.sort(key=lambda e: (e.origin_time, e.source_event_id))
        return Catalog(
            id=f"{SOURCE_ID}/{region.id}/{start.isoformat()}/{end.isoformat()}",
            region_id=region.id,
            events=tuple(events),
            sources=(SOURCE_ID,),
            built_at=utc_now(),
            builder_version=ADAPTER_VERSION,
            notes=note,
        )

    # ------------------------------------------------------------------ online
    def _count(
        self, region: Region, start: datetime, end: datetime, min_magnitude: float | None
    ) -> int:
        url = query_url(region, start, end, min_magnitude=min_magnitude, endpoint="count")
        payload = fetch_bytes(url, cache_dir=None)
        if payload.status_code != 200:
            msg = f"ComCat count returned HTTP {payload.status_code} for {url}"
            raise FetchError(msg)
        doc = json.loads(payload.content)
        return int(doc["count"])

    def _fetch_window(
        self,
        region: Region,
        start: datetime,
        end: datetime,
        *,
        min_magnitude: float | None,
    ) -> list[Event]:
        """Fetch ``[start, end)``; bisect when the service reports more than the page limit."""
        n = self._count(region, start, end, min_magnitude)
        if n == 0:
            return []
        if n >= PAGE_LIMIT:
            if end - start <= timedelta(minutes=1):
                msg = f"more than {PAGE_LIMIT} ComCat events in one minute at {start}: give up"
                raise FetchError(msg)
            mid = start + (end - start) / 2
            return self._fetch_window(
                region, start, mid, min_magnitude=min_magnitude
            ) + self._fetch_window(region, mid, end, min_magnitude=min_magnitude)
        url = query_url(region, start, end, min_magnitude=min_magnitude)
        payload = fetch_bytes(url, cache_dir=self.cache_dir)
        if payload.status_code != 200:
            msg = f"ComCat query returned HTTP {payload.status_code} for {url}"
            raise FetchError(msg)
        prov = Provenance(
            source=SOURCE_ID,
            source_url=url,
            retrieved_at=payload.retrieved_at,
            sha256=payload.sha256,
            licence=LICENCE,
            adapter_version=ADAPTER_VERSION,
        )
        events = parse_comcat_geojson(payload.content, provenance=prov)
        if len(events) != n:
            log.info(
                "comcat: count said %d, page had %d events (revisions in flight)", n, len(events)
            )
        # the service filters on the summary magnitude; re-apply the half-open window exactly
        return filter_events(events, region, start, end, min_magnitude=min_magnitude)

    # ------------------------------------------------------------------ offline
    def _from_fixtures(
        self,
        region: Region,
        start: datetime,
        end: datetime,
        *,
        min_magnitude: float | None,
    ) -> list[Event]:
        assert self.offline_fixtures is not None
        files = load_fixture_dir(self.offline_fixtures / "comcat", adapter_version=ADAPTER_VERSION)
        events: list[Event] = []
        seen: set[str] = set()
        for f in files:
            for e in parse_comcat_geojson(f.content, provenance=f.provenance):
                if e.id in seen:
                    continue
                seen.add(e.id)
                events.append(e)
        return filter_events(events, region, start, end, min_magnitude=min_magnitude)
