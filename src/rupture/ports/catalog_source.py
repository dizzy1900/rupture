"""Port: a source of catalogued events."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from rupture.domain import Catalog, Region


@runtime_checkable
class CatalogSource(Protocol):
    """Fetch events for a region and half-open time window ``[start, end)``.

    Implementations fetch or raise; they never synthesise records. Every returned event carries
    ``Provenance``. ``min_magnitude`` filters on the source's reported magnitude, not on Mw.
    """

    source_id: str
    adapter_version: str

    def fetch(
        self,
        region: Region,
        start: datetime,
        end: datetime,
        *,
        min_magnitude: float | None = None,
    ) -> Catalog: ...
