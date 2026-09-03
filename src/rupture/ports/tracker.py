"""Port: run and lineage logging (refits, issuances, evaluations)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

from pydantic import Field

from rupture.domain import RuptureModel, UTCDatetime


class RunRecord(RuptureModel):
    """One logged action. ``kind`` is e.g. 'fit', 'refit', 'issue', 'evaluate', 'build_catalog'."""

    run_id: str
    kind: str
    at: UTCDatetime
    region_id: str | None = None
    model_id: str | None = None
    parameter_snapshot_hash: str | None = None
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None


@runtime_checkable
class Tracker(Protocol):
    def log(self, record: RunRecord) -> None: ...

    def records(
        self, *, kind: str | None = None, region_id: str | None = None
    ) -> Iterable[RunRecord]: ...
