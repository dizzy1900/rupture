"""Helpers shared by the catalogue adapters: magnitude-type normalisation, identity Mw, bbox.

Nothing here fetches or invents data. ``identity_mw`` only passes a moment magnitude through
unchanged and records that fact in ``mw_conversion``; every other conversion lives in
:mod:`rupture.pipelines.magnitudes` and is applied at merge time.
"""

from __future__ import annotations

from datetime import datetime

from rupture.domain import Event, MagnitudeType, Region

# Moment-magnitude scales accepted as Mw without conversion (identity).
MOMENT_MAGNITUDE_TYPES: frozenset[MagnitudeType] = frozenset(
    {
        MagnitudeType.MW,
        MagnitudeType.MWW,
        MagnitudeType.MWC,
        MagnitudeType.MWB,
        MagnitudeType.MWR,
    }
)

# Source magnitude-type strings (lower-cased) -> rupture scale. Anything else is OTHER and the
# raw string is kept on the record.
_TYPE_MAP: dict[str, MagnitudeType] = {
    "mw": MagnitudeType.MW,
    "mww": MagnitudeType.MWW,
    "mwc": MagnitudeType.MWC,
    "mwb": MagnitudeType.MWB,
    "mwr": MagnitudeType.MWR,
    "mwp": MagnitudeType.MW,  # ComCat P-wave moment magnitude: a moment magnitude
    "mb": MagnitudeType.MB,
    "mb_lg": MagnitudeType.MB,
    "mblg": MagnitudeType.MB,
    "ms": MagnitudeType.MS,
    "ms_20": MagnitudeType.MS,
    "ms20": MagnitudeType.MS,
    "msz": MagnitudeType.MS,
    "ml": MagnitudeType.ML,
    "mlr": MagnitudeType.ML,  # ComCat/CI "Ml revised"
    "mlg": MagnitudeType.ML,
    "md": MagnitudeType.MD,
    "mc": MagnitudeType.MD,  # coda-duration magnitude
    "mlv": MagnitudeType.MLV,
}


def normalise_magnitude_type(raw: str | None) -> MagnitudeType:
    """Map an agency magnitude-type string to :class:`MagnitudeType`.

    ``mb1`` (IDC), ``ms_vx`` (ComCat ``ms_vx`` for surface-wave amplitude of non-tectonic
    sources), ``mh``, ``mi``, ``mun`` and every unknown code become ``OTHER``; the raw string is
    kept alongside on the :class:`MagnitudeRecord`.
    """
    if raw is None:
        return MagnitudeType.OTHER
    key = raw.strip().lower()
    return _TYPE_MAP.get(key, MagnitudeType.OTHER)


def identity_mw(mag_type: MagnitudeType, value: float) -> tuple[float | None, str | None]:
    """``(mw, mw_conversion)`` for a source magnitude: identity for moment magnitudes, else None."""
    if mag_type in MOMENT_MAGNITUDE_TYPES:
        return value, f"identity:{mag_type.value}"
    return None, None


def in_bbox(region: Region, lon: float, lat: float) -> bool:
    """True when the point lies in the region's bounding box (the source-level pre-filter)."""
    min_lon, min_lat, max_lon, max_lat = region.bbox()
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def in_window(t: datetime, start: datetime, end: datetime) -> bool:
    """Half-open ``[start, end)`` on origin time."""
    return start <= t < end


def filter_events(
    events: list[Event],
    region: Region,
    start: datetime,
    end: datetime,
    *,
    min_magnitude: float | None,
) -> list[Event]:
    """Bounding-box, time-window and reported-magnitude filter applied by every source adapter.

    The polygon filter and depth filter are the pipeline's job (they are logged per event);
    this pre-filter only reproduces what the online query would have asked the service for.
    """
    out: list[Event] = []
    for e in events:
        if not in_bbox(region, e.longitude, e.latitude):
            continue
        if not in_window(e.origin_time, start, end):
            continue
        if min_magnitude is not None and e.magnitude.value < min_magnitude:
            continue
        out.append(e)
    return out
