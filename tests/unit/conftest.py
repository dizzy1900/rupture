"""Shared builders for domain tests. Values are synthetic *inputs to validators*, not data."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rupture.domain import Catalog, Event, EventType, MagnitudeRecord, MagnitudeType, Provenance


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        source="test",
        retrieved_at=datetime(2026, 9, 3, tzinfo=UTC),
        adapter_version="0.0.0",
        licence="none",
    )


def make_event(
    provenance: Provenance,
    *,
    eid: str,
    when: datetime,
    mw: float | None = 5.0,
    event_type: EventType = EventType.EARTHQUAKE,
) -> Event:
    return Event(
        id=eid,
        origin_time=when,
        latitude=28.0,
        longitude=85.0,
        depth_km=10.0,
        magnitude=MagnitudeRecord(
            value=mw if mw is not None else 4.0, type=MagnitudeType.MWW, agency="t"
        ),
        mw=mw,
        mw_conversion="identity:mww" if mw is not None else None,
        event_type=event_type,
        source_catalog="test",
        source_event_id=eid,
        provenance=provenance,
    )


@pytest.fixture
def catalog(provenance: Provenance) -> Catalog:
    times = [
        datetime(2021, 12, 31, 23, 59, 59, tzinfo=UTC),
        datetime(2022, 1, 1, tzinfo=UTC),
        datetime(2022, 1, 15, tzinfo=UTC),
    ]
    events = [make_event(provenance, eid=f"e{i}", when=t) for i, t in enumerate(times)]
    events.append(
        make_event(provenance, eid="ls", when=times[2], mw=None, event_type=EventType.LANDSLIDE)
    )
    return Catalog(id="t", events=tuple(events), built_at=times[-1], builder_version="0.0.0")
