"""STAC index for forecast grids (ADR-0012): one Item per grid, one Collection per region/model."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pystac

from rupture.domain import ForecastGrid

ZARR_MEDIA_TYPE = "application/vnd+zarr"
ITEM_SUFFIX = ".stac.json"
COLLECTION_FILE = "collection.json"


def _bbox(grid: ForecastGrid) -> list[float]:
    lons = [o[0] for o in grid.cell_origins]
    lats = [o[1] for o in grid.cell_origins]
    dh = grid.cell_size_deg
    return [min(lons), min(lats), max(lons) + dh, max(lats) + dh]


def _geometry(bbox: list[float]) -> dict[str, Any]:
    w, s, e, n = bbox
    return {"type": "Polygon", "coordinates": [[[w, s], [e, s], [e, n], [w, n], [w, s]]]}


def item_path(zarr_path: Path) -> Path:
    return zarr_path.with_name(zarr_path.name[: -len(".zarr")] + ITEM_SUFFIX)


def build_item(grid: ForecastGrid, zarr_path: Path) -> pystac.Item:
    bbox = _bbox(grid)
    item = pystac.Item(
        id=grid.id,
        geometry=_geometry(bbox),
        bbox=bbox,
        datetime=grid.issue_time,
        start_datetime=grid.issue_time,
        end_datetime=grid.window_end,
        properties={
            "rupture:region_id": grid.region_id,
            "rupture:model_id": grid.model_id,
            "rupture:model_version": grid.model_version,
            "rupture:parameter_snapshot_hash": grid.parameter_snapshot_hash,
            "rupture:fit_cutoff": grid.fit_cutoff.isoformat(),
            "rupture:training_catalog_hash": grid.training_catalog_hash,
            "rupture:horizon_seconds": int(grid.horizon.total_seconds()),
            "rupture:n_simulations": grid.n_simulations,
            "rupture:total_expected": grid.total_expected(),
            "rupture:magnitude_min": grid.magnitude_bin_edges[0],
            "description": "Gridded expected counts. rupture does not predict earthquakes.",
        },
    )
    item.add_asset(
        "grid",
        pystac.Asset(
            href=zarr_path.name,
            media_type=ZARR_MEDIA_TYPE,
            roles=["data"],
            title="ForecastGrid as zarr (dims cell, magnitude_bin)",
        ),
    )
    return item


def write_item(grid: ForecastGrid, zarr_path: Path) -> Path:
    path = item_path(zarr_path)
    payload = build_item(grid, zarr_path).to_dict(include_self_link=False, transform_hrefs=False)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_items(directory: Path) -> list[pystac.Item]:
    return [
        pystac.Item.from_dict(json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(Path(directory).glob(f"*{ITEM_SUFFIX}"))
    ]


def refresh_collection(directory: Path) -> Path:
    """Rebuild ``collection.json`` from the items present in ``directory``."""
    directory = Path(directory)
    items = read_items(directory)
    region_id = directory.parent.name
    model_id = directory.name
    if items:
        bboxes = [it.bbox for it in items if it.bbox]
        union = [
            min(b[0] for b in bboxes),
            min(b[1] for b in bboxes),
            max(b[2] for b in bboxes),
            max(b[3] for b in bboxes),
        ]
        starts = [it.datetime for it in items if it.datetime is not None]
        ends = [
            it.common_metadata.end_datetime
            for it in items
            if it.common_metadata.end_datetime is not None
        ]
        interval = [min(starts) if starts else None, max(ends) if ends else None]
    else:
        union = [-180.0, -90.0, 180.0, 90.0]
        interval = [None, None]
    collection = pystac.Collection(
        id=f"rupture-forecasts-{region_id}-{model_id}",
        description=(
            f"Gridded rate forecasts for region {region_id!r} from model {model_id!r}. "
            "rupture does not predict earthquakes."
        ),
        extent=pystac.Extent(pystac.SpatialExtent([union]), pystac.TemporalExtent([interval])),
        license="Apache-2.0",
        extra_fields={"rupture:item_count": len(items)},
    )
    for it in items:
        collection.add_link(pystac.Link(rel="item", target=f"./{it.id}{ITEM_SUFFIX}"))
    path = directory / COLLECTION_FILE
    payload = collection.to_dict(include_self_link=False, transform_hrefs=False)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path
