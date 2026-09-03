"""Catalogue build: fetch from every source, associate duplicates, homogenise, filter, estimate Mc.

Rules (ADR-0017, docs/CATALOG_BUILD.md):

* **Duplicate association** across sources: two records are the same event when
  ``|dt| <= time_window_s`` (16 s) and the great-circle distance is ``<= distance_km`` (100 km),
  the windows used by Weatherill, Pagani & Garcia (2016) for global catalogue merging. Records
  from the same *lane* are never merged with each other (a source has already de-duplicated its
  own bulletin); the lane is the source id, except ComCat where it is ``usgs-comcat/<net>`` so
  that ComCat's own copies of ISC-GEM origins (``net=iscgem``) can be associated with the ``us``
  origin. Matching is single-linkage in time order, choosing the cluster with the nearest member.
* **Preferred solution** for location/time/depth/preferred-as-reported magnitude:
  ISC-GEM > ISC > ComCat > GCMT (GCMT is a centroid; it wins only when nothing else has the event).
* **Homogenised Mw**: :func:`rupture.pipelines.magnitudes.preferred_mw`.
* **Event type**: any non-earthquake tag from any contributing record is kept (ComCat is the only
  source that classifies routinely); landslide-type entries are retained and tagged, never dropped.
* **Filters** run *after* association so that a GCMT centroid just outside the polygon still
  contributes its Mw: epicentre must be covered by the region polygon
  (``OUTSIDE_REGION_DROPPED``), depth must be within ``[depth_min_km, depth_max_km]``
  (``DEPTH_FILTERED``; unknown depth is kept and noted).
* **Ids** are ``rup-<sha1('<source>:<id>')[:12]>`` of the preferred solution: stable across
  rebuilds as long as the preferred source and its id do not change.

Every decision is a ``HomogenisationLogEntry``. No record is invented; a source that cannot be
reached raises, except ISC-GEM which is optional by design (ADR-0005) and is *recorded* as absent.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from rupture.adapters.catalogs import IscGemUnavailableError, gcmt, make_sources
from rupture.adapters.sources.regions import contains, region_polygon
from rupture.domain import (
    Bounds,
    Catalog,
    CompletenessEstimate,
    Event,
    EventType,
    HomogenisationLogEntry,
    HomogenisationStep,
    MagnitudeRecord,
    Region,
    utc_now,
)
from rupture.pipelines.completeness import InsufficientDataError, estimate_completeness
from rupture.pipelines.magnitudes import SourcedMagnitude, preferred_mw
from rupture.ports.catalog_source import CatalogSource

log = logging.getLogger(__name__)

BUILDER_VERSION = "0.1.0"
LOCATION_PRECEDENCE: tuple[str, ...] = ("isc-gem", "isc", "usgs-comcat", "gcmt")
EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True, slots=True)
class MergeConfig:
    """Association windows (Weatherill, Pagani & Garcia 2016 defaults)."""

    time_window_s: float = 16.0
    distance_km: float = 100.0


@dataclass(slots=True)
class _Cluster:
    members: list[_Member] = field(default_factory=list)
    lanes: set[str] = field(default_factory=set)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


_NET_RX = re.compile(r"^[a-z]+")


def lane_for(source_catalog: str, source_event_id: str) -> str:
    """The lane of one source record: the source id, or ``usgs-comcat/<net>`` for ComCat.

    ComCat event ids are ``<net><code>`` (``us7000tbwb``, ``ci38457511``, ``iscgem607260025``),
    so the network is the leading alphabetic run of the id.
    """
    if source_catalog == "usgs-comcat":
        m = _NET_RX.match(source_event_id)
        return f"usgs-comcat/{m.group(0) if m else 'unknown'}"
    return source_catalog


def lane_of(event: Event) -> str:
    return lane_for(event.source_catalog, event.source_event_id)


def contributing_lanes(event: Event) -> set[str]:
    """Lanes of every source record merged into ``event`` (from ``contributing_ids``)."""
    lanes: set[str] = set()
    for cid in event.contributing_ids:
        source, _, sid = cid.partition(":")
        lanes.add(lane_for(source, sid))
    return lanes


def location_rank(event: Event) -> tuple[int, str, str]:
    try:
        rank = LOCATION_PRECEDENCE.index(event.source_catalog)
    except ValueError:
        rank = len(LOCATION_PRECEDENCE)
    # within ComCat, prefer the network's own origin over its copy of another catalogue
    sub = "1" if lane_of(event).endswith("/iscgem") else "0"
    return (rank, sub, event.source_event_id)


def rupture_event_id(source_catalog: str, source_event_id: str) -> str:
    digest = hashlib.sha1(  # identifier, not security
        f"{source_catalog}:{source_event_id}".encode(), usedforsecurity=False
    ).hexdigest()
    return f"rup-{digest[:12]}"


AssocKey = tuple[datetime, float, float]


def association_keys(event: Event) -> tuple[AssocKey, ...]:
    """``(time, lat, lon)`` keys a record can be matched on: its own origin, plus for GCMT the
    reference hypocentre (the centroid time lags the origin by the half-duration)."""
    keys: list[AssocKey] = [(event.origin_time, event.latitude, event.longitude)]
    ref = gcmt.reference_hypocentre(event)
    if ref is not None:
        keys.insert(0, ref)
    return tuple(keys)


def _keys_match(a: tuple[AssocKey, ...], b: tuple[AssocKey, ...], config: MergeConfig) -> float:
    """Smallest |dt| over key pairs inside both windows, or ``inf`` when none match."""
    best = float("inf")
    for ta, la, lo_a in a:
        for tb, lb, lo_b in b:
            dt = abs((ta - tb).total_seconds())
            if dt > config.time_window_s or dt >= best:
                continue
            if haversine_km(la, lo_a, lb, lo_b) > config.distance_km:
                continue
            best = dt
    return best


@dataclass(slots=True)
class _Member:
    event: Event
    keys: tuple[AssocKey, ...]


def associate(records: Sequence[Event], config: MergeConfig) -> list[list[Event]]:
    """Group source records into clusters using the time/distance windows and the lane rule."""
    members = [_Member(e, association_keys(e)) for e in records]
    members.sort(key=lambda m: (min(k[0] for k in m.keys), m.event.source_catalog, m.event.id))
    clusters: list[_Cluster] = []
    # clusters are appended in order of their first member's earliest key; kept for bisect
    first_times: list[datetime] = []
    window = timedelta(seconds=config.time_window_s)
    for rec in members:
        lane = lane_of(rec.event)
        t_min = min(k[0] for k in rec.keys)
        lo = bisect_left(first_times, t_min - window)
        best: _Cluster | None = None
        best_dt = float("inf")
        for cl in clusters[lo:]:
            if lane in cl.lanes:
                continue
            for m in cl.members:
                dt = _keys_match(rec.keys, m.keys, config)
                if dt < best_dt:
                    best, best_dt = cl, dt
        if best is None:
            best = _Cluster()
            clusters.append(best)
            first_times.append(t_min)
        best.members.append(rec)
        best.lanes.add(lane)
    return [[m.event for m in cl.members] for cl in clusters]


def _merge_cluster(
    members: list[Event], log_entries: list[HomogenisationLogEntry], now: datetime
) -> Event:
    members = sorted(members, key=location_rank)
    loc = members[0]
    eid = rupture_event_id(loc.source_catalog, loc.source_event_id)
    contributing = tuple(dict.fromkeys(cid for m in members for cid in m.contributing_ids))
    src_ids = tuple(m.id for m in members)

    if len(members) > 1:
        log_entries.append(
            HomogenisationLogEntry(
                event_id=eid,
                step=HomogenisationStep.DUPLICATE_MERGED,
                detail=f"{len(members)} records associated within the windows",
                source_ids=src_ids,
                at=now,
            )
        )
    log_entries.append(
        HomogenisationLogEntry(
            event_id=eid,
            step=HomogenisationStep.PREFERRED_SOLUTION,
            detail=f"location/time from {loc.source_catalog}:{loc.source_event_id}",
            source_ids=src_ids,
            at=now,
        )
    )

    # magnitudes ----------------------------------------------------------
    sourced: list[SourcedMagnitude] = []
    for m in members:
        sourced.append(SourcedMagnitude(m.source_catalog, m.magnitude))
        sourced.extend(SourcedMagnitude(m.source_catalog, om) for om in m.other_magnitudes)
    result = preferred_mw(sourced)
    others: list[MagnitudeRecord] = []
    seen: set[str] = set()
    for sm in sourced:
        key = sm.record.canonical_json()
        if sm.record == loc.magnitude or key in seen:
            continue
        seen.add(key)
        others.append(sm.record)
    step = (
        HomogenisationStep.MAGNITUDE_CONVERTED
        if result.mw is not None
        else HomogenisationStep.MAGNITUDE_UNCONVERTIBLE
    )
    log_entries.append(
        HomogenisationLogEntry(
            event_id=eid, step=step, detail=result.detail, source_ids=src_ids, at=now
        )
    )

    # event type ----------------------------------------------------------
    types = [m.event_type for m in members]
    event_type = loc.event_type
    if event_type == EventType.EARTHQUAKE:
        non_eq = [t for t in types if t != EventType.EARTHQUAKE]
        if non_eq:
            event_type = non_eq[0]
    if event_type != EventType.EARTHQUAKE or len(set(types)) > 1:
        log_entries.append(
            HomogenisationLogEntry(
                event_id=eid,
                step=HomogenisationStep.EVENT_TYPE_TAGGED,
                detail=f"tagged {event_type.value}; sources said {[t.value for t in types]}",
                source_ids=src_ids,
                at=now,
            )
        )

    return Event(
        id=eid,
        origin_time=loc.origin_time,
        origin_time_uncertainty_s=loc.origin_time_uncertainty_s,
        latitude=loc.latitude,
        longitude=loc.longitude,
        horizontal_uncertainty_km=loc.horizontal_uncertainty_km,
        depth_km=loc.depth_km,
        depth_uncertainty_km=loc.depth_uncertainty_km,
        magnitude=loc.magnitude,
        other_magnitudes=tuple(others),
        mw=result.mw,
        mw_conversion=result.conversion,
        event_type=event_type,
        source_catalog=loc.source_catalog,
        source_event_id=loc.source_event_id,
        contributing_ids=contributing,
        provenance=loc.provenance,
    )


def _bounds(events: Sequence[Event], start: datetime, end: datetime) -> Bounds | None:
    if not events:
        return None
    depths = [e.depth_km for e in events if e.depth_km is not None]
    return Bounds(
        min_longitude=min(e.longitude for e in events),
        max_longitude=max(e.longitude for e in events),
        min_latitude=min(e.latitude for e in events),
        max_latitude=max(e.latitude for e in events),
        min_depth_km=min(depths) if depths else None,
        max_depth_km=max(depths) if depths else None,
        start_time=start,
        end_time=end,
    )


def resolve_sources(
    sources: Sequence[CatalogSource | str] | None,
    *,
    offline_fixtures: Path | None,
    raw_dir: Path | None,
) -> list[CatalogSource]:
    if sources is None:
        sources = ["comcat", "isc", "gcmt"]
    names = [s for s in sources if isinstance(s, str)]
    made = make_sources(names, offline_fixtures=offline_fixtures, raw_dir=raw_dir) if names else []
    out: list[CatalogSource] = []
    it = iter(made)
    for s in sources:
        out.append(next(it) if isinstance(s, str) else s)
    return out


def build_catalog(
    region: Region,
    start: datetime,
    end: datetime,
    sources: Sequence[CatalogSource | str] | None = None,
    *,
    offline_fixtures: Path | None = None,
    raw_dir: Path | None = None,
    min_magnitude: float | None = None,
    merge: MergeConfig | None = None,
    estimate_mc: bool = True,
    etas_cross_check: bool = True,
) -> Catalog:
    """Build the homogenised catalogue for ``region`` over ``[start, end)``.

    ``sources`` may mix adapter instances and CLI names (``comcat``, ``isc``, ``gcmt``,
    ``isc-gem``); names are instantiated with ``offline_fixtures``/``raw_dir``. ``min_magnitude``
    is the source-reported magnitude floor passed to every adapter (``None`` = whatever the
    source has). Mc is estimated on homogenised Mw of earthquakes only.
    """
    if end <= start:
        msg = "end must be after start"
        raise ValueError(msg)
    cfg = merge or MergeConfig()
    now = utc_now()
    entries: list[HomogenisationLogEntry] = []
    notes: list[str] = [
        f"windows: |dt|<={cfg.time_window_s:g}s, d<={cfg.distance_km:g}km",
        f"min_magnitude={min_magnitude}",
        "offline fixtures" if offline_fixtures else "online",
    ]

    records: list[Event] = []
    used: list[str] = []
    for src in resolve_sources(sources, offline_fixtures=offline_fixtures, raw_dir=raw_dir):
        try:
            cat = src.fetch(region, start, end, min_magnitude=min_magnitude)
        except IscGemUnavailableError as exc:
            log.warning("%s", exc)
            notes.append(f"source {src.source_id} not included: {exc}")
            continue
        used.append(src.source_id)
        for e in cat.events:
            records.append(e)
            entries.append(
                HomogenisationLogEntry(
                    event_id=e.id,
                    step=HomogenisationStep.INGESTED,
                    detail=(
                        f"{e.magnitude.raw_type or e.magnitude.type.value} {e.magnitude.value:.2f} "
                        f"type={e.event_type.value}"
                    ),
                    source_ids=(e.id,),
                    at=now,
                )
            )
        log.info("%s: %d records", src.source_id, len(cat.events))

    merged = [_merge_cluster(cl, entries, now) for cl in associate(records, cfg)]

    polygon = region_polygon(region)
    kept: list[Event] = []
    for e in merged:
        if not contains(polygon, e.longitude, e.latitude):
            entries.append(
                HomogenisationLogEntry(
                    event_id=e.id,
                    step=HomogenisationStep.OUTSIDE_REGION_DROPPED,
                    detail=f"epicentre ({e.longitude:.4f}, {e.latitude:.4f}) outside {region.id}",
                    source_ids=e.contributing_ids,
                    at=now,
                )
            )
            continue
        if e.depth_km is not None and not (
            region.depth_min_km <= e.depth_km <= region.depth_max_km
        ):
            entries.append(
                HomogenisationLogEntry(
                    event_id=e.id,
                    step=HomogenisationStep.DEPTH_FILTERED,
                    detail=(
                        f"depth {e.depth_km:.1f} km outside "
                        f"[{region.depth_min_km:g}, {region.depth_max_km:g}]"
                    ),
                    source_ids=e.contributing_ids,
                    at=now,
                )
            )
            continue
        kept.append(e)
    kept.sort(key=lambda e: (e.origin_time, e.id))

    completeness: tuple[CompletenessEstimate, ...] = ()
    if estimate_mc:
        mws = [e.mw for e in kept if e.event_type == EventType.EARTHQUAKE and e.mw is not None]
        try:
            completeness = tuple(
                estimate_completeness(
                    mws,
                    window_start=start,
                    window_end=end,
                    with_etas_cross_check=etas_cross_check,
                )
            )
        except InsufficientDataError as exc:
            notes.append(f"no completeness estimate: {exc}")

    ordered_used = sorted(
        used, key=lambda s: LOCATION_PRECEDENCE.index(s) if s in LOCATION_PRECEDENCE else 99
    )
    return Catalog(
        id=f"{region.id}/{start.isoformat()}/{end.isoformat()}",
        region_id=region.id,
        events=tuple(kept),
        completeness=completeness,
        bounds=_bounds(kept, start, end),
        homogenisation_log=tuple(entries),
        sources=tuple(ordered_used),
        built_at=now,
        builder_version=BUILDER_VERSION,
        notes="; ".join(notes),
    )
