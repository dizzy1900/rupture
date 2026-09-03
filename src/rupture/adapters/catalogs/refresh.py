"""Regenerate the committed catalogue fixtures from the live services (network; ``rupture catalog
refresh-fixtures``).

The fixture files are byte-exact service responses (ComCat GeoJSON pages, ISC FDSN text, GCMT
monthly NDK files); ``provenance.json`` in each directory records the exact URL, query
parameters, ``retrieved_at``, ``sha256`` and licence. Nothing is edited by hand. This module is
the single place the fixture queries are defined, so a refresh is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from rupture.adapters.catalogs import comcat, gcmt, isc
from rupture.adapters.catalogs._http import FetchError, fetch_bytes
from rupture.adapters.catalogs.fixtures import write_fixture_provenance

BBox = tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat

NEPAL_BBOX: BBox = (80.0, 26.0, 89.0, 31.0)
TURKIYE_BBOX: BBox = (35.0, 35.5, 42.0, 40.0)
CALIFORNIA_BBOX: BBox = (-122.0, 32.0, -114.0, 37.5)


@dataclass(frozen=True, slots=True)
class ServiceSlice:
    """A bbox/time/magnitude query to one FDSN service, saved under ``filename``."""

    filename: str
    start: datetime
    end: datetime
    min_magnitude: float
    bbox: BBox
    notes: str | None = None


COMCAT_SLICES: tuple[ServiceSlice, ...] = (
    ServiceSlice(
        "gorkha-2015-30d-m4.geojson",
        datetime(2015, 4, 25, tzinfo=UTC),
        datetime(2015, 5, 25, tzinfo=UTC),
        4.0,
        NEPAL_BBOX,
        "2015 Gorkha sequence, 30 days",
    ),
    ServiceSlice(
        "kahramanmaras-2023-30d-m4.geojson",
        datetime(2023, 2, 6, tzinfo=UTC),
        datetime(2023, 3, 8, tzinfo=UTC),
        4.0,
        TURKIYE_BBOX,
        "2023 Kahramanmaras doublet, 30 days",
    ),
    ServiceSlice(
        "ridgecrest-2019-30d-m3.5.geojson",
        datetime(2019, 7, 4, tzinfo=UTC),
        datetime(2019, 8, 3, tzinfo=UTC),
        3.5,
        CALIFORNIA_BBOX,
        "2019 Ridgecrest sequence, 30 days",
    ),
    ServiceSlice(
        "nepal-2026-landslide-us7000tbwb.geojson",
        datetime(2026, 8, 20, tzinfo=UTC),
        datetime(2026, 9, 1, tzinfo=UTC),
        4.0,
        NEPAL_BBOX,
        "window containing the landslide-type entry us7000tbwb (2026-08-26); "
        "eventtype unrestricted",
    ),
)

ISC_SLICES: tuple[ServiceSlice, ...] = (
    ServiceSlice(
        "gorkha-2015-7d-m4.txt",
        datetime(2015, 4, 25, tzinfo=UTC),
        datetime(2015, 5, 2, tzinfo=UTC),
        4.0,
        NEPAL_BBOX,
        "2015 Gorkha sequence, first 7 days",
    ),
    ServiceSlice(
        "kahramanmaras-2023-7d-m4.txt",
        datetime(2023, 2, 6, tzinfo=UTC),
        datetime(2023, 2, 13, tzinfo=UTC),
        4.0,
        TURKIYE_BBOX,
        "2023 Kahramanmaras doublet, first 7 days",
    ),
    ServiceSlice(
        "ridgecrest-2019-7d-m3.5.txt",
        datetime(2019, 7, 4, tzinfo=UTC),
        datetime(2019, 7, 11, tzinfo=UTC),
        3.5,
        CALIFORNIA_BBOX,
        "2019 Ridgecrest sequence, first 7 days",
    ),
)

# whole monthly GCMT files covering the three fixture windows (final, not quick, solutions)
GCMT_MONTHS: tuple[tuple[int, int], ...] = (
    (2015, 4),
    (2015, 5),
    (2019, 7),
    (2019, 8),
    (2023, 2),
    (2023, 3),
)

REQUIRED_COMCAT_IDS: dict[str, tuple[str, ...]] = {
    "nepal-2026-landslide-us7000tbwb.geojson": ("us7000tbwb",),
    "gorkha-2015-30d-m4.geojson": ("us20002926", "us20002ejl"),
}


def _fmt(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def comcat_slice_url(s: ServiceSlice) -> str:
    params = {
        "format": "geojson",
        "starttime": _fmt(s.start),
        "endtime": _fmt(s.end),
        "minmagnitude": f"{s.min_magnitude:g}",
        "minlongitude": f"{s.bbox[0]:g}",
        "maxlongitude": f"{s.bbox[2]:g}",
        "minlatitude": f"{s.bbox[1]:g}",
        "maxlatitude": f"{s.bbox[3]:g}",
        "orderby": "time-asc",
    }
    return f"{comcat.BASE_URL}/query?{urlencode(params)}"


def isc_slice_url(s: ServiceSlice) -> str:
    params = {
        "format": "text",
        "starttime": _fmt(s.start),
        "endtime": _fmt(s.end),
        "minmagnitude": f"{s.min_magnitude:g}",
        "minlongitude": f"{s.bbox[0]:g}",
        "maxlongitude": f"{s.bbox[2]:g}",
        "minlatitude": f"{s.bbox[1]:g}",
        "maxlatitude": f"{s.bbox[3]:g}",
    }
    return f"{isc.BASE_URL}/query?{urlencode(params)}"


def _query_dict(s: ServiceSlice) -> dict[str, Any]:
    return {
        "starttime": _fmt(s.start),
        "endtime": _fmt(s.end),
        "minmagnitude": s.min_magnitude,
        "bbox": {
            "min_longitude": s.bbox[0],
            "min_latitude": s.bbox[1],
            "max_longitude": s.bbox[2],
            "max_latitude": s.bbox[3],
        },
    }


def refresh_comcat(fixtures_root: Path) -> list[str]:
    directory = fixtures_root / "comcat"
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}
    report: list[str] = []
    for s in COMCAT_SLICES:
        url = comcat_slice_url(s)
        payload = fetch_bytes(url)
        if payload.status_code != 200:
            msg = f"ComCat returned HTTP {payload.status_code} for {url}"
            raise FetchError(msg)
        events = comcat.parse_comcat_geojson(
            payload.content, provenance=_prov(comcat.SOURCE_ID, url, payload)
        )
        ids = {e.source_event_id for e in events}
        for required in REQUIRED_COMCAT_IDS.get(s.filename, ()):
            if required not in ids:
                msg = f"{s.filename}: expected event {required} is not in the response"
                raise FetchError(msg)
        (directory / s.filename).write_bytes(payload.content)
        files[s.filename] = {
            "source_url": url,
            "retrieved_at": payload.retrieved_at.isoformat(),
            "sha256": payload.sha256,
            "size": len(payload.content),
            "n_events": len(events),
            "query": _query_dict(s),
            "notes": s.notes,
        }
        report.append(f"comcat/{s.filename}: {len(events)} events, {len(payload.content)} bytes")
    write_fixture_provenance(
        directory,
        source=comcat.SOURCE_ID,
        licence=comcat.LICENCE,
        adapter_version=comcat.ADAPTER_VERSION,
        files=files,
        notes=(
            "byte-exact ComCat FDSN GeoJSON responses; eventtype unrestricted so landslide-type "
            "entries are present"
        ),
    )
    return report


def refresh_isc(fixtures_root: Path) -> list[str]:
    directory = fixtures_root / "isc"
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}
    report: list[str] = []
    for s in ISC_SLICES:
        url = isc_slice_url(s)
        payload = fetch_bytes(url, timeout_s=600.0)
        if payload.status_code != 200:
            msg = f"ISC returned HTTP {payload.status_code} for {url}"
            raise FetchError(msg)
        events = isc.parse_isc_text(payload.content, provenance=_prov(isc.SOURCE_ID, url, payload))
        (directory / s.filename).write_bytes(payload.content)
        files[s.filename] = {
            "source_url": url,
            "retrieved_at": payload.retrieved_at.isoformat(),
            "sha256": payload.sha256,
            "size": len(payload.content),
            "n_events": len(events),
            "query": _query_dict(s),
            "notes": s.notes,
        }
        report.append(f"isc/{s.filename}: {len(events)} events, {len(payload.content)} bytes")
    write_fixture_provenance(
        directory,
        source=isc.SOURCE_ID,
        licence=isc.LICENCE,
        adapter_version=isc.ADAPTER_VERSION,
        files=files,
        notes="byte-exact ISC FDSN text responses (reviewed bulletin)",
    )
    return report


def refresh_gcmt(fixtures_root: Path) -> list[str]:
    directory = fixtures_root / "gcmt"
    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, Any]] = {}
    report: list[str] = []
    for year, month in GCMT_MONTHS:
        rel = gcmt.monthly_file_path(year, month)
        url = f"{gcmt.BASE_URL}/{rel}"
        payload = fetch_bytes(url)
        if payload.status_code != 200:
            msg = f"GCMT returned HTTP {payload.status_code} for {url}"
            raise FetchError(msg)
        events = gcmt.parse_ndk(payload.content, provenance=_prov(gcmt.SOURCE_ID, url, payload))
        name = Path(rel).name
        (directory / name).write_bytes(payload.content)
        files[name] = {
            "source_url": url,
            "retrieved_at": payload.retrieved_at.isoformat(),
            "sha256": payload.sha256,
            "size": len(payload.content),
            "n_events": len(events),
            "query": {"year": year, "month": month, "file": rel},
            "notes": f"whole GCMT monthly (final) NDK file for {year}-{month:02d}",
        }
        report.append(f"gcmt/{name}: {len(events)} events, {len(payload.content)} bytes")
    write_fixture_provenance(
        directory,
        source=gcmt.SOURCE_ID,
        licence=gcmt.LICENCE,
        adapter_version=gcmt.ADAPTER_VERSION,
        files=files,
        notes="whole monthly NDK files as published under NEW_MONTHLY/<yyyy>/",
    )
    return report


def _prov(source: str, url: str, payload: Any) -> Any:
    from rupture.domain import Provenance  # noqa: PLC0415

    return Provenance(
        source=source,
        source_url=url,
        retrieved_at=payload.retrieved_at,
        sha256=payload.sha256,
        adapter_version="refresh",
    )


def refresh_all(fixtures_root: Path) -> list[str]:
    report: list[str] = []
    report += refresh_comcat(fixtures_root)
    report += refresh_isc(fixtures_root)
    report += refresh_gcmt(fixtures_root)
    return report
