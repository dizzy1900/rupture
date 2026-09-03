"""Port: persistence for forecast grids."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from rupture.domain import ForecastGrid


@runtime_checkable
class GridStore(Protocol):
    def save(self, grid: ForecastGrid) -> str:
        """Persist; returns a locator (path or URI)."""
        ...

    def load(self, forecast_id: str) -> ForecastGrid: ...

    def list_ids(
        self, *, region_id: str | None = None, model_id: str | None = None
    ) -> Iterable[str]: ...
