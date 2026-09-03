"""Port: a time-dependent seismicity forecasting model."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

from rupture.domain import Catalog, FitResult, ForecastGrid, Region


@runtime_checkable
class ForecastModel(Protocol):
    """Fit on a catalogue up to a hard cutoff; then issue gridded, magnitude-binned rate forecasts.

    Leakage rule: ``fit`` must use only events with ``origin_time < cutoff``; ``forecast`` must use
    only events with ``origin_time < issue_time`` as its history. Both are asserted by the harness.
    """

    model_id: str
    model_version: str

    def fit(self, catalog: Catalog, region: Region, cutoff: datetime) -> FitResult: ...

    def forecast(
        self,
        history: Catalog,
        issue_time: datetime,
        horizon: timedelta,
    ) -> ForecastGrid: ...

    def parameter_snapshot(self) -> dict[str, Any]:
        """The parameters the next ``forecast`` call would use; hashed into every grid."""
        ...
