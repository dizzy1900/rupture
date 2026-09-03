"""Region polygon -> forecasting lattice, and binning of point events onto it.

Cells are squares of side ``region.cell_size_deg`` on a lattice anchored at the polygon's
bounding-box minimum (snapped to a multiple of the cell size). A cell belongs to the region when
its centre lies inside the polygon (shapely ``covers``). The same cells are used by the ETAS
adapter to bin simulated events and, via ``ForecastGrid.cell_origins``, by the evaluator to build
the pycsep ``CartesianGrid2D``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from shapely.geometry import Point, Polygon

from rupture.domain import Region

_ROUND = 6


@dataclass(frozen=True)
class Lattice:
    """The cells of a region: origins (lower-left lon/lat) plus an integer index map."""

    cell_size_deg: float
    lon0: float
    lat0: float
    origins: tuple[tuple[float, float], ...]
    index_of: dict[tuple[int, int], int]

    @property
    def n_cells(self) -> int:
        return len(self.origins)

    def cell_indices(self, lons: npt.ArrayLike, lats: npt.ArrayLike) -> npt.NDArray[np.int64]:
        """Cell index per point, or -1 for points outside every cell."""
        lon = np.asarray(lons, dtype=np.float64)
        lat = np.asarray(lats, dtype=np.float64)
        ix = np.floor((lon - self.lon0) / self.cell_size_deg + 1e-9).astype(np.int64)
        iy = np.floor((lat - self.lat0) / self.cell_size_deg + 1e-9).astype(np.int64)
        out = np.full(lon.shape, -1, dtype=np.int64)
        for k, key in enumerate(zip(ix.tolist(), iy.tolist(), strict=True)):
            out[k] = self.index_of.get(key, -1)
        return out


def region_polygon(region: Region) -> Polygon:
    """shapely polygon in (lon, lat) order."""
    return Polygon([(lon, lat) for lon, lat in region.closed_ring()])


def shape_coords_lat_lon(region: Region) -> list[list[float]]:
    """The polygon as ``[[lat, lon], ...]`` — the order the etas package expects."""
    return [[lat, lon] for lon, lat in region.closed_ring()]


def build_lattice(region: Region) -> Lattice:
    poly = region_polygon(region)
    dh = region.cell_size_deg
    min_lon, min_lat, max_lon, max_lat = region.bbox()
    lon0 = float(np.floor(min_lon / dh + 1e-9) * dh)
    lat0 = float(np.floor(min_lat / dh + 1e-9) * dh)
    nx = int(np.ceil((max_lon - lon0) / dh - 1e-9))
    ny = int(np.ceil((max_lat - lat0) / dh - 1e-9))
    origins: list[tuple[float, float]] = []
    index_of: dict[tuple[int, int], int] = {}
    for iy in range(ny):
        for ix in range(nx):
            lon = lon0 + ix * dh
            lat = lat0 + iy * dh
            if poly.covers(Point(lon + dh / 2.0, lat + dh / 2.0)):
                index_of[(ix, iy)] = len(origins)
                origins.append((round(lon, _ROUND), round(lat, _ROUND)))
    if not origins:
        msg = f"region {region.id!r} has no cell whose centre lies inside its polygon"
        raise ValueError(msg)
    return Lattice(
        cell_size_deg=dh, lon0=lon0, lat0=lat0, origins=tuple(origins), index_of=index_of
    )


def magnitude_bin_indices(
    magnitudes: npt.ArrayLike, edges: tuple[float, ...], width: float
) -> npt.NDArray[np.int64]:
    """Bin index per magnitude (last bin open); -1 below the first edge."""
    m = np.asarray(magnitudes, dtype=np.float64)
    j = np.floor((m - edges[0]) / width + 1e-9).astype(np.int64)
    j[m < edges[0] - 1e-9] = -1
    return np.minimum(j, len(edges) - 1)
