"""Re-export the real-data fixtures shared with the forecasting tests."""

from __future__ import annotations

from tests.unit.forecasting.conftest import (  # noqa: F401 - pytest collects imported fixtures
    committed_fit,
    fixture_catalog,
    region,
    ridgecrest_grid,
)
