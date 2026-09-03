"""ISC-GEM Global Instrumental Earthquake Catalogue from a locally downloaded CSV (ADR-0005).

The catalogue is form-gated (``https://www.isc.ac.uk/iscgem/request_catalogue.php`` is an HTTP
POST form asking for name, institution and terms acknowledgement), so rupture never downloads it
itself. The user downloads the CSV and sets ``RUPTURE_ISC_GEM_CSV``; :meth:`IscGemSource.fetch`
raises a clear error naming the variable when it is unset or the file is missing.

CSV layout (documented for v9 onwards; the header comment lines start with ``#`` and the last of
them names the columns)::

    date, lat, lon, smajax, sminax, strike, q, depth, unc, q, mw, unc, q, s, mo, fac, mo_auth,
    mpp, mpr, mrr, mrt, mtp, mtt, str1, dip1, rake1, str2, dip2, rake2, type, eventid

The parser reads the column names from that header line when present and falls back to the
documented list otherwise. No fixture is committed: the CSV could not be obtained without the
form on 2026-09-03, and rupture does not invent rows (see docs/CATALOG_BUILD.md).
Licence as stated on the download page: CC-BY-SA 3.0 (unported), (C) ISC and GEM Foundation.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from rupture.adapters.catalogs._common import filter_events
from rupture.adapters.catalogs.fixtures import load_fixture_dir
from rupture.domain import (
    Catalog,
    Event,
    EventType,
    MagnitudeRecord,
    MagnitudeType,
    Provenance,
    Region,
    sha256_hex,
    utc_now,
)

log = logging.getLogger(__name__)

SOURCE_ID = "isc-gem"
ADAPTER_VERSION = "0.1.0"
ENV_VAR = "RUPTURE_ISC_GEM_CSV"
DOWNLOAD_PAGE = "https://www.isc.ac.uk/iscgem/download.php"
LICENCE = "CC-BY-SA-3.0 (ISC-GEM terms; (C) International Seismological Centre and GEM Foundation)"

DOCUMENTED_COLUMNS: tuple[str, ...] = (
    "date",
    "lat",
    "lon",
    "smajax",
    "sminax",
    "strike",
    "q_loc",
    "depth",
    "depth_unc",
    "q_depth",
    "mw",
    "mw_unc",
    "q_mw",
    "s",
    "mo",
    "fac",
    "mo_auth",
    "mpp",
    "mpr",
    "mrr",
    "mrt",
    "mtp",
    "mtt",
    "str1",
    "dip1",
    "rake1",
    "str2",
    "dip2",
    "rake2",
    "type",
    "eventid",
)


class IscGemUnavailableError(RuntimeError):
    """The ISC-GEM CSV is not configured; the message says how to configure it."""


def _dedupe_header(names: list[str]) -> list[str]:
    """ISC-GEM repeats ``q`` and ``unc``; qualify them by the column they follow."""
    out: list[str] = []
    prev = ""
    for n in names:
        key = n.strip().lower()
        if key in {"q", "unc"}:
            key = f"{prev}_{key}" if key == "unc" else f"q_{prev.removesuffix('_unc')}"
        out.append(key)
        prev = key
    return out


def _header_from_comments(lines: list[str]) -> list[str] | None:
    for ln in lines:
        if ln.startswith("#") and "eventid" in ln.lower():
            names = ln.lstrip("#").split(",")
            return _dedupe_header(names)
    return None


def _parse_date(text: str) -> datetime:
    text = text.strip()
    # ISC-GEM writes 'YYYY-MM-DD HH:MM:SS.ff'
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def _opt(text: str | None) -> float | None:
    if text is None:
        return None
    t = text.strip()
    if not t or t.lower() in {"nan", "na", "-"}:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def parse_isc_gem_csv(payload: bytes | str, *, provenance: Provenance) -> list[Event]:
    """Pure parser for the ISC-GEM main catalogue CSV -> events (Mw is native: identity)."""
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    lines = text.splitlines()
    header = _header_from_comments(lines) or list(DOCUMENTED_COLUMNS)
    if "date" not in header:
        header = _dedupe_header(header)
    data_lines = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
    reader = csv.reader(io.StringIO("\n".join(data_lines)))
    events: list[Event] = []
    for cols in reader:
        if len(cols) < len(header):
            msg = f"ISC-GEM row has {len(cols)} columns, header has {len(header)}"
            raise ValueError(msg)
        row = {k: v.strip() for k, v in zip(header, cols, strict=False)}
        eid = row["eventid"]
        mw = _opt(row.get("mw"))
        if mw is None:
            log.warning("isc-gem: skipped event %s: no Mw", eid)
            continue
        smaj = _opt(row.get("smajax"))
        events.append(
            Event(
                id=f"{SOURCE_ID}:{eid}",
                origin_time=_parse_date(row["date"]),
                latitude=float(row["lat"]),
                longitude=float(row["lon"]),
                horizontal_uncertainty_km=smaj,
                depth_km=_opt(row.get("depth")),
                depth_uncertainty_km=_opt(row.get("depth_unc")),
                magnitude=MagnitudeRecord(
                    value=mw,
                    type=MagnitudeType.MW,
                    agency="ISC-GEM",
                    uncertainty=_opt(row.get("mw_unc")),
                    raw_type="mw",
                ),
                mw=mw,
                mw_conversion="identity:mw",
                event_type=EventType.EARTHQUAKE,
                source_catalog=SOURCE_ID,
                source_event_id=eid,
                contributing_ids=(f"{SOURCE_ID}:{eid}",),
                provenance=provenance,
            )
        )
    return events


def configured_path() -> Path:
    """Path from ``RUPTURE_ISC_GEM_CSV`` or raise :class:`IscGemUnavailableError`."""
    value = os.environ.get(ENV_VAR, "").strip()
    if not value:
        msg = (
            f"ISC-GEM is not configured: set {ENV_VAR} to the CSV downloaded from "
            f"{DOWNLOAD_PAGE} (form-gated; ADR-0005). Builds proceed without ISC-GEM."
        )
        raise IscGemUnavailableError(msg)
    path = Path(value).expanduser()
    if not path.exists():
        msg = f"{ENV_VAR}={value} does not exist"
        raise IscGemUnavailableError(msg)
    return path


class IscGemSource:
    """``CatalogSource`` for ISC-GEM. Reads a local CSV; never downloads."""

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION

    def __init__(
        self, *, offline_fixtures: Path | None = None, csv_path: Path | None = None
    ) -> None:
        self.offline_fixtures = offline_fixtures
        self.csv_path = csv_path

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
            fixture_dir = self.offline_fixtures / "isc_gem"
            if not (fixture_dir / "provenance.json").exists():
                msg = (
                    "no ISC-GEM fixture is committed: the catalogue is form-gated and was not "
                    "obtainable without the form (ADR-0005)"
                )
                raise IscGemUnavailableError(msg)
            files = load_fixture_dir(fixture_dir, adapter_version=ADAPTER_VERSION)
            events: list[Event] = []
            for f in files:
                events.extend(parse_isc_gem_csv(f.content, provenance=f.provenance))
            note = f"offline fixtures from {fixture_dir}"
        else:
            path = self.csv_path or configured_path()
            content = path.read_bytes()
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            prov = Provenance(
                source=SOURCE_ID,
                source_url=f"{DOWNLOAD_PAGE} (local file {path})",
                retrieved_at=mtime,
                sha256=sha256_hex(content),
                licence=LICENCE,
                adapter_version=ADAPTER_VERSION,
                notes="retrieved_at is the local file mtime (manual download, ADR-0005)",
            )
            events = parse_isc_gem_csv(content, provenance=prov)
            note = f"local ISC-GEM CSV {path}"
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
