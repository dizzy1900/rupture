"""Port: where an exposure portfolio comes from."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from rupture.domain.loss import ExposurePortfolio


@runtime_checkable
class ExposureSource(Protocol):
    """Build a portfolio from an external source; fetch or fail, never synthesise silently."""

    source_id: str
    adapter_version: str

    def load(self, path: Path | None = None, *, portfolio_id: str) -> ExposurePortfolio: ...
