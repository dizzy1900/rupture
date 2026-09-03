"""zarr persistence for :class:`~rupture.domain.ForecastGrid` (``GridStore`` port; ADR-0012).

Layout: ``<root>/<region_id>/<model_id>/<forecast_id>.zarr`` holding an xarray Dataset with dims
``cell`` and ``magnitude_bin``; every non-array field of the grid is kept verbatim as the JSON
attribute ``rupture_forecast_grid`` so the round trip is exact. A STAC item is written alongside
(``<forecast_id>.stac.json``) and the per-directory ``collection.json`` is refreshed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
import xarray as xr

from rupture.adapters.storage import stac
from rupture.domain import ForecastGrid

GRID_ATTR = "rupture_forecast_grid"
_ARRAY_FIELDS = {"expected_counts", "cell_origins", "magnitude_bin_edges"}


class ZarrGridStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def path_for(self, grid: ForecastGrid) -> Path:
        return self.root / grid.region_id / grid.model_id / f"{grid.id}.zarr"

    def save(self, grid: ForecastGrid) -> str:
        path = self.path_for(grid)
        path.parent.mkdir(parents=True, exist_ok=True)
        origins = np.asarray(grid.cell_origins, dtype=np.float64)
        ds = xr.Dataset(
            {"expected_counts": (("cell", "magnitude_bin"), grid.counts())},
            coords={
                "cell_lon": ("cell", origins[:, 0]),
                "cell_lat": ("cell", origins[:, 1]),
                "magnitude_bin_edge": (
                    "magnitude_bin",
                    np.asarray(grid.magnitude_bin_edges, dtype=np.float64),
                ),
            },
            attrs={
                GRID_ATTR: grid.model_dump_json(exclude=_ARRAY_FIELDS),
                "forecast_id": grid.id,
                "region_id": grid.region_id,
                "model_id": grid.model_id,
                "issue_time": grid.issue_time.isoformat(),
                "window_end": grid.window_end.isoformat(),
                "description": (
                    "Expected event counts per cell and magnitude bin over the horizon. "
                    "rupture does not predict earthquakes."
                ),
            },
        )
        ds.to_zarr(path, mode="w", zarr_format=3, consolidated=False)
        stac.write_item(grid, path)
        stac.refresh_collection(path.parent)
        return str(path)

    def load(self, forecast_id: str) -> ForecastGrid:
        path = self._find(forecast_id)
        ds = xr.open_zarr(path, zarr_format=3, consolidated=False)
        try:
            meta = json.loads(str(ds.attrs[GRID_ATTR]))
            counts = np.asarray(ds["expected_counts"].values, dtype=np.float64)
            lons = np.asarray(ds["cell_lon"].values, dtype=np.float64)
            lats = np.asarray(ds["cell_lat"].values, dtype=np.float64)
            edges = np.asarray(ds["magnitude_bin_edge"].values, dtype=np.float64)
        finally:
            ds.close()
        meta["cell_origins"] = [[float(a), float(b)] for a, b in zip(lons, lats, strict=True)]
        meta["magnitude_bin_edges"] = [float(e) for e in edges]
        meta["expected_counts"] = counts.tolist()
        return ForecastGrid.model_validate(meta)

    def list_ids(
        self, *, region_id: str | None = None, model_id: str | None = None
    ) -> Iterable[str]:
        pattern = f"{region_id or '*'}/{model_id or '*'}/*.zarr"
        return sorted(p.name[: -len(".zarr")] for p in self.root.glob(pattern) if p.is_dir())

    def _find(self, forecast_id: str) -> Path:
        hits = [p for p in self.root.glob(f"*/*/{forecast_id}.zarr") if p.is_dir()]
        if not hits:
            msg = f"forecast {forecast_id!r} not found under {self.root}"
            raise FileNotFoundError(msg)
        if len(hits) > 1:
            msg = f"forecast {forecast_id!r} is ambiguous: {hits}"
            raise FileExistsError(msg)
        return hits[0]
