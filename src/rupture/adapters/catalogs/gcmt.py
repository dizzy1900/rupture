"""Global CMT catalogue from NDK files (ADR-0006).

NDK is a fixed-format text file with five 80-column lines per event, documented at
``https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog/allorder.ndk_explained``:

1. hypocentre reference: catalogue (cols 1-4), date (6-15), time (17-26), lat (28-33),
   lon (35-41), depth (43-47), mb and MS (49-55), location name (57-80);
2. CMT event name (1-16), inversion data, source type, moment-rate function;
3. ``CENTROID:`` time shift +/- err, lat +/- err, lon +/- err, depth +/- err, depth type
   (FREE/FIX/BDY), timestamp (``Q-`` quick or ``S-`` standard);
4. exponent (1-2) then Mrr Mtt Mpp Mrt Mrp Mtp each with its error;
5. version, three eigenvalues (value, plunge, azimuth), scalar moment, two nodal planes.

Mw is derived from the scalar moment (dyne-cm): ``Mw = (2/3) (log10 M0 - 16.1)`` (Hanks &
Kanamori 1979), rounded to two decimals. Location and time are the **centroid** values; the
reference hypocentre (line 1) is encoded in ``provenance.notes`` and exposed through
:func:`reference_hypocentre` so the merge can associate the record with hypocentral catalogues;
the merge uses GCMT for Mw and prefers hypocentral sources for location (docs/CATALOG_BUILD.md).

Files: ``jan76_dec20.ndk`` (1976-2020) plus ``NEW_MONTHLY/<yyyy>/<mon><yy>.ndk`` for later
months; months that have no monthly file yet are covered by the quick-CMT file
``NEW_QUICK/qcmt.ndk``. The fetcher probes the monthly file first and falls back to the quick file.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rupture.adapters.catalogs._common import filter_events
from rupture.adapters.catalogs._http import fetch_bytes
from rupture.adapters.catalogs.fixtures import load_fixture_dir
from rupture.domain import (
    Catalog,
    Event,
    EventType,
    MagnitudeRecord,
    MagnitudeType,
    Provenance,
    Region,
    utc_now,
)

log = logging.getLogger(__name__)

SOURCE_ID = "gcmt"
ADAPTER_VERSION = "0.1.0"
LICENCE = (
    "free for research with citation of Ekström, Nettles & Dziewoński (2012); see globalcmt.org"
)
BASE_URL = "https://www.ldeo.columbia.edu/~gcmt/projects/CMT/catalog"
FULL_FILE = "jan76_dec20.ndk"
FULL_FILE_END = datetime(2021, 1, 1, tzinfo=UTC)
QUICK_FILE = "NEW_QUICK/qcmt.ndk"
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
LINES_PER_RECORD = 5


class NdkFormatError(ValueError):
    """A record does not follow the five-line NDK layout."""


def mw_from_moment(m0_dyne_cm: float) -> float:
    """Hanks & Kanamori (1979): Mw = (2/3)(log10 M0[dyne-cm] - 16.1), rounded to 2 decimals."""
    if m0_dyne_cm <= 0:
        msg = "scalar moment must be positive"
        raise ValueError(msg)
    return round((2.0 / 3.0) * (math.log10(m0_dyne_cm) - 16.1), 2)


def _parse_ref_time(date_s: str, time_s: str) -> datetime:
    y, mo, d = (int(x) for x in date_s.split("/"))
    hh, mm, ss = time_s.split(":")
    sec = float(ss)
    # GCMT occasionally writes 60.0 s; carry it.
    base = datetime(y, mo, d, int(hh), int(mm), tzinfo=UTC)
    return base + timedelta(seconds=sec)


def parse_ndk_record(lines: list[str], *, provenance: Provenance) -> Event:
    """Parse one five-line NDK record into an :class:`Event` (centroid location and time)."""
    if len(lines) != LINES_PER_RECORD:
        msg = f"NDK record needs {LINES_PER_RECORD} lines, got {len(lines)}"
        raise NdkFormatError(msg)
    l1, l2, l3, l4, l5 = lines
    # line 1 -------------------------------------------------------------
    ref_catalog = l1[0:4].strip()
    ref_time = _parse_ref_time(l1[5:15].strip(), l1[16:26].strip())
    ref_lat = float(l1[27:33])
    ref_lon = float(l1[34:41])
    ref_depth = float(l1[42:47])
    mags = l1[48:55].split()
    ref_mb = float(mags[0]) if mags else 0.0
    ref_ms = float(mags[1]) if len(mags) > 1 else 0.0
    location_name = l1[56:80].strip()
    # line 2 -------------------------------------------------------------
    event_name = l2[0:16].strip()
    if not event_name:
        msg = f"NDK line 2 has no event name: {l2!r}"
        raise NdkFormatError(msg)
    # line 3 -------------------------------------------------------------
    if not l3.startswith("CENTROID:"):
        msg = f"NDK line 3 must start with CENTROID: {l3!r}"
        raise NdkFormatError(msg)
    # fixed columns (1-based in the spec: 10-18, 19-22, 23-29, 30-34, 35-42, 43-47, 48-53,
    # 54-58, 60-63, 65-80); old records run fields together, so no whitespace split here
    try:
        t_shift, t_err = float(l3[9:18]), float(l3[18:22])
        c_lat, c_lat_err = float(l3[22:29]), float(l3[29:34])
        c_lon, c_lon_err = float(l3[34:42]), float(l3[42:47])
        c_depth, c_depth_err = float(l3[47:53]), float(l3[53:58])
    except ValueError as exc:
        msg = f"NDK centroid line does not parse: {l3!r} ({exc})"
        raise NdkFormatError(msg) from exc
    depth_type = l3[59:63].strip()
    stamp = l3[64:80].strip()
    # line 4 -------------------------------------------------------------
    exponent = int(l4[0:2])
    # line 5 -------------------------------------------------------------
    l5_parts = l5.split()
    # version, then 9 numbers (3 eigen triples), scalar moment, 6 nodal-plane ints
    if len(l5_parts) < 17:
        msg = f"NDK line 5 too short: {l5!r}"
        raise NdkFormatError(msg)
    scalar_moment = float(l5_parts[10]) * 10.0**exponent
    mw = mw_from_moment(scalar_moment)

    centroid_time = ref_time + timedelta(seconds=t_shift)
    # horizontal uncertainty from the centroid lat/lon standard errors (degrees -> km, coarse)
    h_unc_km: float | None = None
    if c_lat_err > 0 or c_lon_err > 0:
        dlat_km = c_lat_err * 111.19
        dlon_km = c_lon_err * 111.19 * math.cos(math.radians(c_lat))
        h_unc_km = round(math.hypot(dlat_km, dlon_km), 2)

    others: list[MagnitudeRecord] = []
    if ref_mb > 0:
        others.append(
            MagnitudeRecord(value=ref_mb, type=MagnitudeType.MB, agency=ref_catalog, raw_type="mb")
        )
    if ref_ms > 0:
        others.append(
            MagnitudeRecord(value=ref_ms, type=MagnitudeType.MS, agency=ref_catalog, raw_type="MS")
        )
    quick = stamp.startswith("Q-")
    return Event(
        id=f"{SOURCE_ID}:{event_name}",
        origin_time=centroid_time,
        origin_time_uncertainty_s=t_err if t_err > 0 else None,
        latitude=c_lat,
        longitude=c_lon,
        horizontal_uncertainty_km=h_unc_km,
        depth_km=c_depth,
        depth_uncertainty_km=c_depth_err if c_depth_err > 0 else None,
        magnitude=MagnitudeRecord(
            value=mw,
            type=MagnitudeType.MWC,
            agency="GCMT",
            raw_type=f"Mw from M0={scalar_moment:.3e} dyne-cm ({'quick' if quick else 'standard'})",
        ),
        other_magnitudes=tuple(others),
        mw=mw,
        mw_conversion="identity:mwc",
        event_type=EventType.EARTHQUAKE,
        source_catalog=SOURCE_ID,
        source_event_id=event_name,
        contributing_ids=(f"{SOURCE_ID}:{event_name}",),
        provenance=provenance.model_copy(
            update={
                "notes": (
                    f"ref={ref_catalog}|{ref_time.isoformat()}|{ref_lat:.2f}|{ref_lon:.2f}|"
                    f"{ref_depth:.1f}; centroid_depth={depth_type}; name={location_name}"
                )
            }
        ),
    )


_REF_RX = re.compile(r"ref=(?P<cat>[^|;]+)\|(?P<t>[^|;]+)\|(?P<lat>[-\d.]+)\|(?P<lon>[-\d.]+)\|")


def reference_hypocentre(event: Event) -> tuple[datetime, float, float] | None:
    """``(time, lat, lon)`` of the reference hypocentre a GCMT record was built from.

    The NDK line-1 hypocentre (PDE/ISC) is what other catalogues report; the centroid time lags
    it by the half-duration (30 s for Gorkha 2015), so duplicate association uses this key. It is
    encoded by :func:`parse_ndk_record` in ``provenance.notes`` and decoded here only.
    """
    if event.source_catalog != SOURCE_ID or not event.provenance.notes:
        return None
    m = _REF_RX.search(event.provenance.notes)
    if m is None:
        return None
    return datetime.fromisoformat(m.group("t")), float(m.group("lat")), float(m.group("lon"))


def parse_ndk(payload: bytes | str, *, provenance: Provenance) -> list[Event]:
    """Pure parser: an NDK file (whole or sliced in whole 5-line records) -> events."""
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    lines = [ln.rstrip("\r\n") for ln in text.splitlines() if ln.strip()]
    if len(lines) % LINES_PER_RECORD != 0:
        msg = f"NDK payload has {len(lines)} non-blank lines, not a multiple of {LINES_PER_RECORD}"
        raise NdkFormatError(msg)
    return [
        parse_ndk_record(lines[i : i + LINES_PER_RECORD], provenance=provenance)
        for i in range(0, len(lines), LINES_PER_RECORD)
    ]


def monthly_file_path(year: int, month: int) -> str:
    """``NEW_MONTHLY/<yyyy>/<mon><yy>.ndk`` relative to :data:`BASE_URL`."""
    return f"NEW_MONTHLY/{year}/{MONTHS[month - 1]}{year % 100:02d}.ndk"


def months_between(start: datetime, end: datetime) -> list[tuple[int, int]]:
    """Calendar months touched by ``[start, end)``."""
    out: list[tuple[int, int]] = []
    y, m = start.year, start.month
    last = end - timedelta(microseconds=1)
    while (y, m) <= (last.year, last.month):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


class GcmtSource:
    """``CatalogSource`` for Global CMT. Downloads NDK files into ``cache_dir``
    (``data/raw/gcmt``)."""

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION

    def __init__(
        self, *, offline_fixtures: Path | None = None, cache_dir: Path | None = None
    ) -> None:
        self.offline_fixtures = offline_fixtures
        self.cache_dir = cache_dir

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
            files = load_fixture_dir(
                self.offline_fixtures / "gcmt", adapter_version=ADAPTER_VERSION
            )
            payloads = [(f.content, f.provenance) for f in files]
            note = f"offline fixtures from {self.offline_fixtures}"
        else:
            payloads = self._download(start, end)
            note = "online GCMT NDK files"
        events: list[Event] = []
        seen: set[str] = set()
        for content, prov in payloads:
            for e in parse_ndk(content, provenance=prov):
                if e.id in seen:
                    continue  # the quick file and a monthly file can overlap
                seen.add(e.id)
                events.append(e)
        events = filter_events(events, region, start, end, min_magnitude=min_magnitude)
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

    def _get(self, rel: str) -> tuple[bytes, Provenance] | None:
        url = f"{BASE_URL}/{rel}"
        payload = fetch_bytes(url, cache_dir=self.cache_dir)
        if payload.status_code != 200:
            return None
        prov = Provenance(
            source=SOURCE_ID,
            source_url=url,
            retrieved_at=payload.retrieved_at,
            sha256=payload.sha256,
            licence=LICENCE,
            adapter_version=ADAPTER_VERSION,
        )
        return payload.content, prov

    def _download(self, start: datetime, end: datetime) -> list[tuple[bytes, Provenance]]:
        out: list[tuple[bytes, Provenance]] = []
        if start < FULL_FILE_END:
            got = self._get(FULL_FILE)
            if got is None:
                msg = f"GCMT {FULL_FILE} not available"
                raise RuntimeError(msg)
            out.append(got)
        need_quick = False
        for y, m in months_between(max(start, FULL_FILE_END), end):
            if (y, m) < (FULL_FILE_END.year, FULL_FILE_END.month):
                continue
            got = self._get(monthly_file_path(y, m))
            if got is None:
                need_quick = True
                log.info("gcmt: no monthly file for %04d-%02d yet; using quick CMTs", y, m)
                break
            out.append(got)
        if need_quick:
            got = self._get(QUICK_FILE)
            if got is None:
                msg = f"GCMT quick file {QUICK_FILE} not available"
                raise RuntimeError(msg)
            out.append(got)
        return out
