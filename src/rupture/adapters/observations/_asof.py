"""Half-open as-of filtering for catalogue-shaped observation sources."""

from __future__ import annotations

from datetime import datetime

from rupture.domain import Catalog, Event, VintagePolicy
from rupture.domain.observation import readable_as_of


def events_available_as_of(
    events: tuple[Event, ...], instant: datetime, policy: VintagePolicy
) -> tuple[Event, ...]:
    """Keep events whose record is provably readable strictly before ``instant``.

    ``INCLUDE_UNKNOWN`` keeps rows with ``available_time is None``; ``EXCLUDE_UNKNOWN``
    drops them. Known vintages use ``available_time < instant`` (not ``<=``).
    """
    keep_unknown = policy is VintagePolicy.INCLUDE_UNKNOWN
    kept: list[Event] = []
    for event in events:
        if event.available_time is None:
            if keep_unknown:
                kept.append(event)
            continue
        if readable_as_of(event.available_time, instant):
            kept.append(event)
    return tuple(kept)


def catalog_available_as_of(
    catalog: Catalog, instant: datetime, policy: VintagePolicy
) -> Catalog:
    """Return a new catalogue containing only rows readable as of ``instant``."""
    kept = events_available_as_of(catalog.events, instant, policy)
    return catalog.model_copy(
        update={
            "events": kept,
            "id": f"{catalog.id}/asof-{instant.isoformat()}-{policy.value}",
        }
    )
