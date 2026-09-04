"""Where an issued :class:`~rupture.domain.ForecastGrid` is kept so a client can fetch it.

An :class:`~rupture.domain.AftershockForecast` carries the zone-wide magnitude ladder and a
``forecast_grid_id``. The ladder is a statement about a circle 218 km across for an M7.8; anything
that depends on *where* the rate is concentrated needs the grid itself (``docs/AFTERSHOCK.md``
§ 6). Before this module the grid was computed inside the request and dropped, so the id in the
response referred to nothing an HTTP client could ask for.

Two stores, because the right one depends on how the service is run:

:class:`InMemoryGridStore`
    Default. A bounded most-recently-issued cache inside the process. Simple, no disk, and
    **not shared between uvicorn workers**: with ``--workers N`` a grid issued by one worker is
    invisible to the other ``N-1``, so a fetch can answer 404 for an id that was just returned.
    Run one worker, or use the directory store.

:class:`DirectoryGridStore`
    Writes each grid as JSON under a directory (``RUPTURE_AFTERSHOCK_GRID_DIR``). Shared across
    workers and across restarts when the directory is a mounted volume. Nothing prunes it; a grid
    is roughly a megabyte, and expiry is the deployer's (a cron ``find -mtime``).

Neither store recomputes: a grid is only ever put there by the issuance that produced it. A fetch
for an unknown id is an honest 404, not a fresh forecast under an old id.
"""

from __future__ import annotations

import os
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from rupture.domain import ForecastGrid

GRID_DIR_ENV = "RUPTURE_AFTERSHOCK_GRID_DIR"
DEFAULT_CAPACITY = 16
SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z")
"""A grid id is a path segment in the directory store, so it is validated, never trusted."""


def is_safe_grid_id(grid_id: str) -> bool:
    """True for ids that can be a filename. ``..`` and separators are rejected, not sanitised."""
    return bool(SAFE_ID.fullmatch(grid_id)) and grid_id not in {".", ".."}


@runtime_checkable
class GridStore(Protocol):
    """Somewhere an issued grid can be put and later fetched by its id."""

    def put(self, grid: ForecastGrid) -> None: ...

    def get(self, grid_id: str) -> ForecastGrid | None: ...

    def describe(self) -> str:
        """One line for ``/health``: what kind of store this is and what it holds."""


@dataclass(eq=False)
class InMemoryGridStore:
    """The last ``capacity`` grids this process issued. Not shared between workers."""

    capacity: int = DEFAULT_CAPACITY
    _grids: OrderedDict[str, ForecastGrid] = field(default_factory=OrderedDict, repr=False)

    def put(self, grid: ForecastGrid) -> None:
        self._grids[grid.id] = grid
        self._grids.move_to_end(grid.id)
        while len(self._grids) > self.capacity:
            self._grids.popitem(last=False)

    def get(self, grid_id: str) -> ForecastGrid | None:
        grid = self._grids.get(grid_id)
        if grid is not None:
            self._grids.move_to_end(grid_id)
        return grid

    def describe(self) -> str:
        return (
            f"in-process cache of the last {self.capacity} grids "
            f"({len(self._grids)} held; not shared between workers)"
        )


@dataclass(eq=False)
class DirectoryGridStore:
    """Grids as ``<root>/<grid_id>.json``. Shared across workers; nothing prunes it."""

    root: Path

    def put(self, grid: ForecastGrid) -> None:
        if not is_safe_grid_id(grid.id):  # pragma: no cover - ids are model-generated slugs
            msg = f"refusing to write a grid whose id is not a safe path segment: {grid.id!r}"
            raise ValueError(msg)
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{grid.id}.json"
        tmp = path.with_suffix(".json.partial")
        tmp.write_text(grid.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)  # atomic: a reader never sees a half-written grid

    def get(self, grid_id: str) -> ForecastGrid | None:
        if not is_safe_grid_id(grid_id):
            return None
        path = self.root / f"{grid_id}.json"
        if not path.is_file():
            return None
        return ForecastGrid.model_validate_json(path.read_text(encoding="utf-8"))

    def describe(self) -> str:
        held = len(list(self.root.glob("*.json"))) if self.root.is_dir() else 0
        return f"directory {self.root} ({held} grids; shared between workers, never pruned)"


def grid_store_from_env(env: dict[str, str] | None = None) -> GridStore:
    """A directory store when ``RUPTURE_AFTERSHOCK_GRID_DIR`` is set, else the in-process cache."""
    source = os.environ if env is None else env
    raw = source.get(GRID_DIR_ENV, "").strip()
    if raw:
        return DirectoryGridStore(Path(raw).expanduser())
    return InMemoryGridStore()
