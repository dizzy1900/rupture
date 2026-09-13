"""USGS real-time GeoJSON earthquake feeds as an ``ObservationSource``.

US Government work, public domain. The live feeds are moving windows
(``all_hour``, ``all_day``, ``significant_month`` and siblings under
``https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/``). They are the same GeoJSON
shape ComCat already parses, and they carry the same vintage clock: ``properties.time`` is
origin / valid time, ``properties.updated`` is ``available_time``.

This is a catalogue-shaped observation source: it returns :class:`~rupture.domain.Event`
records, not GNSS. It is not a prediction.

Committed fixtures are **cuts of the ComCat Ridgecrest payload**, not live ``all_day``
snapshots — that feed is not reproducible. See ``data/fixtures/usgs_feed/provenance.json``.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rupture.adapters.catalogs._common import identity_mw, normalise_magnitude_type
from rupture.adapters.catalogs._http import FetchError, fetch_bytes
from rupture.adapters.catalogs.comcat import map_event_type
from rupture.adapters.catalogs.fixtures import load_fixture_dir
from rupture.adapters.observations._asof import catalog_available_as_of
from rupture.domain import (
    Catalog,
    Event,
    MagnitudeRecord,
    Provenance,
    VintagePolicy,
    VintageSummary,
    utc_now,
)
from rupture.domain.observation import ObservableKind

log = logging.getLogger(__name__)

SOURCE_ID = "usgs-realtime-feed"
ADAPTER_VERSION = "0.1.0"
LICENCE = "public-domain (USGS)"

FEED_BASE = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary"
FEEDS: dict[str, str] = {
    "all_hour": f"{FEED_BASE}/all_hour.geojson",
    "all_day": f"{FEED_BASE}/all_day.geojson",
    "significant_month": f"{FEED_BASE}/significant_month.geojson",
}
DEFAULT_FEED = "all_day"


def _opt_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_usgs_feed_geojson(payload: bytes | str, *, provenance: Provenance) -> list[Event]:
    """Parse a USGS GeoJSON FeatureCollection into :class:`Event` records.

    ``properties.time`` -> ``origin_time`` / valid time; ``properties.updated`` ->
    ``available_time``. Features without magnitude or time are skipped and logged, never
    filled in.
    """
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    doc = json.loads(text)
    if doc.get("type") != "FeatureCollection":
        msg = f"not a GeoJSON FeatureCollection (type={doc.get('type')!r})"
        raise ValueError(msg)
    events: list[Event] = []
    for feat in doc.get("features", []):
        fid = str(feat.get("id"))
        props = feat.get("properties") or {}
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if props.get("mag") is None:
            log.warning("usgs-feed: skipped feature %s: no magnitude", fid)
            continue
        if props.get("time") is None or len(coords) < 2:
            log.warning("usgs-feed: skipped feature %s: no time or coordinates", fid)
            continue
        origin = datetime.fromtimestamp(props["time"] / 1000.0, tz=UTC)
        available = (
            datetime.fromtimestamp(props["updated"] / 1000.0, tz=UTC)
            if props.get("updated") is not None
            else None
        )
        mag_type = normalise_magnitude_type(props.get("magType"))
        mag_value = float(props["mag"])
        mw, conv = identity_mw(mag_type, mag_value)
        depth = _opt_float(coords[2]) if len(coords) > 2 else None
        events.append(
            Event(
                id=f"{SOURCE_ID}:{fid}",
                origin_time=origin,
                origin_time_uncertainty_s=_opt_float(props.get("timeError")),
                available_time=available,
                latitude=float(coords[1]),
                longitude=float(coords[0]),
                horizontal_uncertainty_km=_opt_float(props.get("horizontalError")),
                depth_km=depth,
                depth_uncertainty_km=_opt_float(props.get("depthError")),
                magnitude=MagnitudeRecord(
                    value=mag_value,
                    type=mag_type,
                    agency=props.get("net"),
                    uncertainty=_opt_float(props.get("magError")),
                    raw_type=props.get("magType"),
                ),
                mw=mw,
                mw_conversion=conv,
                event_type=map_event_type(props.get("type")),
                source_catalog=SOURCE_ID,
                source_event_id=fid,
                contributing_ids=(f"{SOURCE_ID}:{fid}",),
                provenance=provenance,
            )
        )
    events.sort(key=lambda e: (e.origin_time, e.source_event_id))
    return events


class UsgsRealtimeFeed:
    """USGS real-time GeoJSON feed. Online by default; ``offline_fixtures`` reads committed files.

    Implements :class:`~rupture.ports.observation_source.ObservationSource` (catalogue-shaped).
    """

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION
    kind = ObservableKind.CATALOGUE_EVENT

    def __init__(
        self,
        *,
        feed: str = DEFAULT_FEED,
        offline_fixtures: Path | None = None,
        cache_dir: Path | None = None,
        catalog: Catalog | None = None,
    ) -> None:
        if feed not in FEEDS:
            msg = f"unknown USGS feed {feed!r}; known: {', '.join(FEEDS)}"
            raise ValueError(msg)
        self.feed = feed
        self.offline_fixtures = offline_fixtures
        self.cache_dir = cache_dir
        self._catalog = catalog

    def catalog(self) -> Catalog:
        """The loaded (or fetched) events. Fetch or fail; never synthesise."""
        return self._load()

    def _load(self) -> Catalog:
        if self._catalog is not None:
            return self._catalog
        if self.offline_fixtures is not None:
            self._catalog = self._from_fixtures()
            return self._catalog
        self._catalog = self._fetch_feed()
        return self._catalog

    def _from_fixtures(self) -> Catalog:
        assert self.offline_fixtures is not None
        files = load_fixture_dir(
            self.offline_fixtures / "usgs_feed", adapter_version=ADAPTER_VERSION
        )
        events: list[Event] = []
        seen: set[str] = set()
        for f in files:
            for event in parse_usgs_feed_geojson(f.content, provenance=f.provenance):
                if event.id in seen:
                    continue
                seen.add(event.id)
                events.append(event)
        events.sort(key=lambda e: (e.origin_time, e.source_event_id))
        return _catalog_of(tuple(events), note=f"offline fixtures from {self.offline_fixtures}")

    def _fetch_feed(self) -> Catalog:
        url = FEEDS[self.feed]
        payload = fetch_bytes(url, cache_dir=self.cache_dir, ok_statuses=frozenset({200}))
        if payload.status_code != 200:
            msg = f"USGS feed {self.feed} returned HTTP {payload.status_code} for {url}"
            raise FetchError(msg)
        if not payload.content.strip():
            msg = f"USGS feed {self.feed} was empty at {url}"
            raise FetchError(msg)
        prov = Provenance(
            source=SOURCE_ID,
            source_url=payload.url,
            retrieved_at=payload.retrieved_at,
            sha256=payload.sha256,
            licence=LICENCE,
            adapter_version=ADAPTER_VERSION,
        )
        events = parse_usgs_feed_geojson(payload.content, provenance=prov)
        return _catalog_of(tuple(events), note=f"online USGS feed {self.feed}")

    def available_as_of(self, instant: datetime, *, policy: VintagePolicy) -> Catalog:
        return catalog_available_as_of(self._load(), instant, policy)

    def vintage(self, reference_time: datetime | None = None) -> VintageSummary:
        return self._load().vintage_summary(reference_time)


def _catalog_of(events: tuple[Event, ...], *, note: str) -> Catalog:
    return Catalog(
        id=f"{SOURCE_ID}/{DEFAULT_FEED}",
        events=events,
        sources=(SOURCE_ID,),
        built_at=utc_now(),
        builder_version=ADAPTER_VERSION,
        notes=note,
    )
