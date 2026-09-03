"""Catalogues: events plus completeness metadata, bounds and the homogenisation log."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from rupture.domain.common import RuptureModel, UTCDatetime, sha256_hex
from rupture.domain.event import Event, EventType


class McMethod(StrEnum):
    """Completeness-magnitude estimators rupture reports."""

    MAXIMUM_CURVATURE = "maximum_curvature"  # Wiemer & Wyss 2000; +0.2 per Woessner & Wiemer 2005
    B_VALUE_STABILITY = "b_value_stability"  # Cao & Gao 2002
    MC_KS = "mc_ks"  # Mizrahi et al. 2021 (etas package cross-check)


class CompletenessEstimate(RuptureModel):
    """One Mc estimate for a catalogue slice. Report every method run; do not pick silently."""

    mc: float = Field(ge=0.0, le=9.0)
    method: McMethod
    b_value: float | None = Field(default=None, gt=0.0)
    b_value_uncertainty: float | None = Field(default=None, ge=0.0)
    n_events: int = Field(ge=0, description="Events at or above mc used in the estimate.")
    window_start: UTCDatetime
    window_end: UTCDatetime
    computed_at: UTCDatetime
    correction: float = Field(default=0.0, description="Additive correction applied (e.g. +0.2).")
    notes: str | None = None


class Bounds(RuptureModel):
    """Spatial and temporal extent actually covered by the events."""

    min_longitude: float = Field(ge=-180.0, le=180.0)
    max_longitude: float = Field(ge=-180.0, le=180.0)
    min_latitude: float = Field(ge=-90.0, le=90.0)
    max_latitude: float = Field(ge=-90.0, le=90.0)
    min_depth_km: float | None = None
    max_depth_km: float | None = None
    start_time: UTCDatetime
    end_time: UTCDatetime

    @model_validator(mode="after")
    def _ordered(self) -> Bounds:
        if self.min_latitude > self.max_latitude or self.start_time > self.end_time:
            msg = "bounds must be ordered"
            raise ValueError(msg)
        return self


class HomogenisationStep(StrEnum):
    """Steps logged per event while merging sources."""

    INGESTED = "ingested"
    DUPLICATE_MERGED = "duplicate_merged"
    PREFERRED_SOLUTION = "preferred_solution"
    MAGNITUDE_CONVERTED = "magnitude_converted"
    MAGNITUDE_UNCONVERTIBLE = "magnitude_unconvertible"
    EVENT_TYPE_TAGGED = "event_type_tagged"
    OUTSIDE_REGION_DROPPED = "outside_region_dropped"
    DEPTH_FILTERED = "depth_filtered"


class HomogenisationLogEntry(RuptureModel):
    """One logged decision about one event."""

    event_id: str
    step: HomogenisationStep
    detail: str
    source_ids: tuple[str, ...] = ()
    at: UTCDatetime


class Catalog(RuptureModel):
    """An immutable, provenance-complete set of events for one region and time span.

    Helper methods return new catalogues; nothing mutates. Time filters are half-open
    ``[start, end)`` and compare ``origin_time`` only — this is the single place the
    leakage assertions rely on.
    """

    id: str
    region_id: str | None = None
    events: tuple[Event, ...]
    completeness: tuple[CompletenessEstimate, ...] = ()
    bounds: Bounds | None = None
    homogenisation_log: tuple[HomogenisationLogEntry, ...] = ()
    sources: tuple[str, ...] = Field(
        default=(), description="Source catalogues merged, in precedence order."
    )
    built_at: UTCDatetime
    builder_version: str
    notes: str | None = None

    # ------------------------------------------------------------------ derived
    def __len__(self) -> int:
        return len(self.events)

    def event_hash(self) -> str:
        """sha256 over sorted event ids + origin times: identifies the *slice*, not the metadata."""
        keys = sorted(f"{e.id}|{e.origin_time.isoformat()}" for e in self.events)
        return sha256_hex("\n".join(keys))

    def max_origin_time(self) -> datetime | None:
        return max((e.origin_time for e in self.events), default=None)

    def min_origin_time(self) -> datetime | None:
        return min((e.origin_time for e in self.events), default=None)

    def preferred_mc(self, method: McMethod | None = None) -> CompletenessEstimate | None:
        """The Mc estimate to use: the requested method, else maximum curvature, else the first."""
        if method is not None:
            return next((c for c in self.completeness if c.method == method), None)
        for m in (McMethod.MAXIMUM_CURVATURE, McMethod.B_VALUE_STABILITY, McMethod.MC_KS):
            hit = next((c for c in self.completeness if c.method == m), None)
            if hit is not None:
                return hit
        return None

    # ------------------------------------------------------------------ filters
    def _with_events(self, events: Iterable[Event], suffix: str) -> Catalog:
        return self.model_copy(update={"events": tuple(events), "id": f"{self.id}/{suffix}"})

    def before(self, cutoff: datetime) -> Catalog:
        """Events with ``origin_time < cutoff`` — everything a model may see when fitting."""
        return self._with_events(
            (e for e in self.events if e.origin_time < cutoff), f"lt-{cutoff.isoformat()}"
        )

    def between(self, start: datetime, end: datetime) -> Catalog:
        """Events with ``start <= origin_time < end`` — a forecast's target slice."""
        if end <= start:
            msg = "end must be after start"
            raise ValueError(msg)
        return self._with_events(
            (e for e in self.events if start <= e.origin_time < end),
            f"{start.isoformat()}-{end.isoformat()}",
        )

    def of_type(self, *types: EventType) -> Catalog:
        """Keep only the given event types (e.g. earthquakes only for ETAS fits and targets)."""
        return self._with_events((e for e in self.events if e.event_type in types), "-".join(types))

    def earthquakes(self) -> Catalog:
        return self.of_type(EventType.EARTHQUAKE)

    def at_least(self, mw: float) -> Catalog:
        """Events with homogenised ``mw >= threshold``; events without Mw are excluded."""
        return self._with_events(
            (e for e in self.events if e.mw is not None and e.mw >= mw), f"mw{mw}"
        )

    def count_by_type(self) -> dict[EventType, int]:
        out: dict[EventType, int] = dict.fromkeys(EventType, 0)
        for e in self.events:
            out[e.event_type] += 1
        return out
