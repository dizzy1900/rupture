"""Port: an observation stream that can be asked what it knew at a past instant.

ADR-0054's central idea in one method. A source that can only hand back its current state forces
every consumer to assume that state was always true, and that assumption is invisible until
somebody measures it. ``available_as_of`` makes the assumption a parameter.

Two adapters implement it (ADR-0067): ``catalogs.usgs_feed.UsgsRealtimeFeed`` and
``catalogs.fdsn_events.FdsnEventSource``. Both filter the *current* payload by the vintage each
record reports (``Catalog.as_of``), which is enough to *measure* exposure and not enough to
*reconstruct* a past state: a record revised after the instant is dropped, not restored to what it
said then. A real reconstruction needs archived vintages — periodic snapshots, or a provider that
serves them — and ADR-0064 records that as the next step. The NGL GNSS adapter has an
``available_as_of`` of the same shape that returns positions rather than a ``Catalog``, so it does
not satisfy this ``Catalog``-typed port.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from rupture.domain import Catalog, VintagePolicy, VintageSummary


@runtime_checkable
class ObservationSource(Protocol):
    """A source of catalogue observations with a queryable vintage."""

    source_id: str

    def available_as_of(self, instant: datetime, *, policy: VintagePolicy) -> Catalog:
        """The observations this source can prove it held at ``instant``."""
        ...

    def vintage(self, reference_time: datetime | None = None) -> VintageSummary:
        """How much of what this source holds carries a vintage, and how late it arrived."""
        ...
