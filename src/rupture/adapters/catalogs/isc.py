"""ISC Bulletin via the ISC FDSN event web service, text output, parsed in-house.

``https://www.isc.ac.uk/fdsnws/event/1/query?format=text`` returns one pipe-separated row per
event with the prime hypocentre and one (preferred) magnitude::

    #EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|ContributorID|MagType|Magnitude|MagAuthor|EventLocationName|EventType

followed by ``#``-prefixed agency-acknowledgement lines. The reviewed ISC Bulletin lags real time
by roughly two years; recent windows come back empty (HTTP 204/404 "no data"), which is a
legitimate result, not an error.

The text format gives a single magnitude per event (ISC's preferred one, often GCMT ``MW`` for
large events and ISC ``mb`` otherwise). Other agencies' magnitudes are not in this format; the
merge step gathers Mw from GCMT directly instead.

Layers: :func:`parse_isc_text` (pure) and :class:`IscSource` (fetch, paged by calendar year).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
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

SOURCE_ID = "isc"
ADAPTER_VERSION = "0.1.0"
LICENCE = "ISC data policy: free for research with attribution to the ISC (www.isc.ac.uk)"
BASE_URL = "https://www.isc.ac.uk/fdsnws/event/1"
# ISC returns 413 when a request matches too many events; the adapter then halves the window.
MIN_WINDOW_DAYS = 1

EXPECTED_HEADER = (
    "#EventID|Time|Latitude|Longitude|Depth/km|Author|Catalog|Contributor|ContributorID|"
    "MagType|Magnitude|MagAuthor|EventLocationName"
)


def map_event_type(raw: str | None) -> EventType:
    """ISC ``EventType`` words -> :class:`EventType`. Empty means earthquake in the ISC output."""
    if raw is None or not raw.strip():
        return EventType.EARTHQUAKE
    key = raw.strip().lower()
    if "earthquake" in key:
        return EventType.EARTHQUAKE
    if "explosion" in key or "blast" in key:
        return EventType.EXPLOSION
    if any(w in key for w in ("landslide", "rockslide", "avalanche", "slide")):
        return EventType.LANDSLIDE
    return EventType.OTHER


def _parse_time(text: str) -> datetime:
    return datetime.fromisoformat(text.strip()).replace(tzinfo=UTC)


def _opt_float(text: str) -> float | None:
    text = text.strip()
    return float(text) if text else None


def parse_isc_text(
    payload: bytes | str,
    *,
    provenance: Provenance,
    skipped: list[tuple[str, str]] | None = None,
) -> list[Event]:
    """Pure parser for the ISC FDSN text format.

    Rows without a magnitude and stray non-data lines are skipped, logged and, when ``skipped``
    is given, appended to it as ``(row id or text, reason)`` so the caller can record a count.
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
            msg = "ISC text payload has data rows before its #EventID header"
            raise ValueError(msg)
        if "|" not in line:
            # the service occasionally emits a stray non-data line (seen: a lone "?"); it is
            # not an event row, so it is reported and skipped rather than treated as data
            log.warning("isc: skipped non-data line %r", line[:80])
            if skipped is not None:
                skipped.append((line[:40], "non-data line"))
            continue
        cols = [c.strip() for c in line.split("|")]
        if len(cols) < 12:
            msg = f"ISC row has {len(cols)} columns, expected >= 12: {line[:120]}"
            raise ValueError(msg)
        row = dict(zip(header, cols, strict=False))
        eid = row["EventID"]
        mag_text = row.get("Magnitude", "")
        if not mag_text:
            log.warning("isc: skipped event %s: no magnitude", eid)
            if skipped is not None:
                skipped.append((eid, "no magnitude"))
            continue
        mag_value = float(mag_text)
        raw_type = row.get("MagType") or None
        mag_type = normalise_magnitude_type(raw_type)
        mw, conv = identity_mw(mag_type, mag_value)
        events.append(
            Event(
                id=f"{SOURCE_ID}:{eid}",
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
                source_catalog=SOURCE_ID,
                source_event_id=eid,
                contributing_ids=(f"{SOURCE_ID}:{eid}",),
                provenance=provenance,
            )
        )
    if header is None and any(ln.strip() for ln in lines):
        msg = "ISC text payload has no #EventID header"
        raise ValueError(msg)
    return events


def query_url(
    region: Region, start: datetime, end: datetime, *, min_magnitude: float | None
) -> str:
    """Exact ISC FDSN URL (recorded in provenance)."""
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
    return f"{BASE_URL}/query?{urlencode(params)}"


def year_windows(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
    """Split ``[start, end)`` at 1 January boundaries (ISC is queried a calendar year at a time)."""
    out: list[tuple[datetime, datetime]] = []
    cur = start
    while cur < end:
        nxt = min(datetime(cur.year + 1, 1, 1, tzinfo=UTC), end)
        out.append((cur, nxt))
        cur = nxt
    return out


class IscSource:
    """``CatalogSource`` for the ISC Bulletin (reviewed). Pages by calendar year."""

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION

    def __init__(
        self, *, offline_fixtures: Path | None = None, cache_dir: Path | None = None
    ) -> None:
        self.offline_fixtures = offline_fixtures
        self.cache_dir = cache_dir
        self.last_skipped: list[tuple[str, str]] = []

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
        self.last_skipped = []
        if self.offline_fixtures is not None:
            events = self._from_fixtures(region, start, end, min_magnitude=min_magnitude)
            note = f"offline fixtures from {self.offline_fixtures}"
        else:
            events = []
            for ws, we in year_windows(start, end):
                events.extend(self._fetch_window(region, ws, we, min_magnitude=min_magnitude))
            note = "online ISC FDSN text, paged by calendar year"
        if self.last_skipped:
            note += f"; skipped {len(self.last_skipped)} source rows"
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

    def _fetch_window(
        self, region: Region, start: datetime, end: datetime, *, min_magnitude: float | None
    ) -> list[Event]:
        url = query_url(region, start, end, min_magnitude=min_magnitude)
        payload = fetch_bytes(
            url, cache_dir=self.cache_dir, ok_statuses=frozenset({200, 204, 404, 413})
        )
        if payload.status_code == 413:
            if (end - start).days <= MIN_WINDOW_DAYS:
                msg = f"ISC returned 413 for a {MIN_WINDOW_DAYS}-day window at {start}"
                raise FetchError(msg)
            mid = start + (end - start) / 2
            log.info("isc: 413 for %s..%s, bisecting", start, end)
            return self._fetch_window(
                region, start, mid, min_magnitude=min_magnitude
            ) + self._fetch_window(region, mid, end, min_magnitude=min_magnitude)
        if payload.status_code in (204, 404) or not payload.content.strip():
            log.info("isc: no data for %s..%s", start, end)
            return []
        prov = Provenance(
            source=SOURCE_ID,
            source_url=url,
            retrieved_at=payload.retrieved_at,
            sha256=payload.sha256,
            licence=LICENCE,
            adapter_version=ADAPTER_VERSION,
        )
        events = parse_isc_text(payload.content, provenance=prov, skipped=self.last_skipped)
        return filter_events(events, region, start, end, min_magnitude=min_magnitude)

    def _from_fixtures(
        self, region: Region, start: datetime, end: datetime, *, min_magnitude: float | None
    ) -> list[Event]:
        assert self.offline_fixtures is not None
        files = load_fixture_dir(self.offline_fixtures / "isc", adapter_version=ADAPTER_VERSION)
        events: list[Event] = []
        seen: set[str] = set()
        for f in files:
            for e in parse_isc_text(f.content, provenance=f.provenance, skipped=self.last_skipped):
                if e.id not in seen:
                    seen.add(e.id)
                    events.append(e)
        return filter_events(events, region, start, end, min_magnitude=min_magnitude)
