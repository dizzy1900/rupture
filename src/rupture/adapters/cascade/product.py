"""Read a published USGS ground-failure product, so rupture can be checked against it.

The committed slices under ``tests/fixtures/cascade/<event>/`` hold cell-centre coordinates and
the product's own areal-coverage values, verbatim and at the product's own four-decimal rounding.
Nothing here re-grids, smooths or fills.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class PublishedCoverage:
    """One published ground-failure raster, as scattered cell centres."""

    model_id: str
    longitudes: FloatArray
    latitudes: FloatArray
    coverage: FloatArray
    source_url: str | None
    source_sha256: str | None
    parent_sha256: str | None
    cell_size_deg: float | None

    def __len__(self) -> int:
        return int(self.coverage.size)

    def where(self, keep: npt.NDArray[np.bool_]) -> PublishedCoverage:
        return PublishedCoverage(
            model_id=self.model_id,
            longitudes=self.longitudes[keep],
            latitudes=self.latitudes[keep],
            coverage=self.coverage[keep],
            source_url=self.source_url,
            source_sha256=self.source_sha256,
            parent_sha256=self.parent_sha256,
            cell_size_deg=self.cell_size_deg,
        )


def read_coverage_csv(
    path: Path,
    *,
    model_id: str,
    provenance_path: Path | None = None,
    cell_size_deg: float | None = None,
) -> PublishedCoverage:
    """Read a committed ``lon,lat,coverage`` slice of a published product."""
    lons: list[float] = []
    lats: list[float] = []
    values: list[float] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            lons.append(float(row["lon"]))
            lats.append(float(row["lat"]))
            values.append(float(row["coverage"]))
    if not values:
        msg = f"{path} is empty"
        raise ValueError(msg)
    source_url: str | None = None
    sha: str | None = None
    parent: str | None = None
    if provenance_path is not None and provenance_path.exists():
        record = json.loads(provenance_path.read_text(encoding="utf-8"))
        entry = record.get("files", {}).get(path.name, {})
        source_url = entry.get("source_url")
        sha = entry.get("sha256")
        parent = entry.get("parent_sha256")
    return PublishedCoverage(
        model_id=model_id,
        longitudes=np.array(lons, dtype=np.float64),
        latitudes=np.array(lats, dtype=np.float64),
        coverage=np.array(values, dtype=np.float64),
        source_url=source_url,
        source_sha256=sha,
        parent_sha256=parent,
        cell_size_deg=cell_size_deg,
    )
