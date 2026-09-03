"""Test-region loader: ``data/regions/<id>/region.json`` (a ``Region`` dump) + ``region.geojson``.

The JSON record is authoritative; the GeoJSON is a convenience copy written from the same model
(``Region.to_geojson``) so GIS tools can open it. ``load_region`` verifies the two agree.
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point, Polygon

from rupture.domain import CompletenessEstimate, Region

REGIONS_DIRNAME = "regions"
REGION_FILE = "region.json"
GEOJSON_FILE = "region.geojson"


def default_regions_root(repo_root: Path) -> Path:
    return repo_root / "data" / REGIONS_DIRNAME


def list_region_ids(regions_root: Path) -> list[str]:
    if not regions_root.exists():
        return []
    return sorted(p.name for p in regions_root.iterdir() if (p / REGION_FILE).exists())


def load_region(regions_root: Path, region_id: str) -> Region:
    """Load one region; raise ``FileNotFoundError`` with the ids that do exist."""
    path = regions_root / region_id / REGION_FILE
    if not path.exists():
        known = ", ".join(list_region_ids(regions_root)) or "(none)"
        msg = f"unknown region {region_id!r} (no {path}); known regions: {known}"
        raise FileNotFoundError(msg)
    region = Region.model_validate_json(path.read_text(encoding="utf-8"))
    if region.id != region_id:
        msg = f"{path} declares id {region.id!r}, directory says {region_id!r}"
        raise ValueError(msg)
    geo_path = regions_root / region_id / GEOJSON_FILE
    if geo_path.exists():
        geo = json.loads(geo_path.read_text(encoding="utf-8"))
        ring = [tuple(map(float, p)) for p in geo["geometry"]["coordinates"][0]]
        if tuple(ring) != tuple((float(a), float(b)) for a, b in region.closed_ring()):
            msg = f"{geo_path} polygon disagrees with {path}; regenerate with write_region"
            raise ValueError(msg)
    return region


def write_region(regions_root: Path, region: Region) -> tuple[Path, Path]:
    """Write ``region.json`` and ``region.geojson`` for a region (used by the CLI to store Mc)."""
    directory = regions_root / region.id
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / REGION_FILE
    geo_path = directory / GEOJSON_FILE
    json_path.write_text(
        json.dumps(region.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    geo_path.write_text(
        json.dumps(region.to_geojson(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return json_path, geo_path


def with_mc(region: Region, mc: CompletenessEstimate) -> Region:
    return region.model_copy(update={"mc": mc})


def region_polygon(region: Region) -> Polygon:
    """The region as a shapely polygon (exterior ring only)."""
    poly = Polygon(region.closed_ring())
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly


def contains(polygon: Polygon, lon: float, lat: float) -> bool:
    """Point-in-polygon including the boundary (``covers``)."""
    return bool(polygon.covers(Point(lon, lat)))


# ---------------------------------------------------------------------- defaults
def california_relm_polygon(tolerance_deg: float = 0.05) -> tuple[tuple[float, float], ...]:
    """Outer boundary of the pycsep RELM California region.

    pycsep ships the RELM region as 7682 cell origins (0.1 degree); the boundary is the union
    of those cells, exterior ring, simplified with ``tolerance_deg`` (0.05 keeps the area
    exactly and gives 158 distinct vertices; every cell centre stays covered). Forecast grids built
    from ``csep.core.regions.california_relm_region()`` therefore align with this polygon.
    """
    from csep.core import regions as csep_regions  # noqa: PLC0415  heavy optional import
    from shapely.geometry import box  # noqa: PLC0415
    from shapely.ops import unary_union  # noqa: PLC0415

    relm = csep_regions.california_relm_region()
    dh = float(relm.dh)
    cells = [
        box(round(x, 4), round(y, 4), round(x + dh, 4), round(y + dh, 4)) for x, y in relm.origins()
    ]
    union = unary_union([c.buffer(1e-6) for c in cells]).buffer(-1e-6)
    simplified = union.simplify(tolerance_deg, preserve_topology=True)
    if not isinstance(simplified, Polygon):
        msg = f"RELM cell union is a {simplified.geom_type}, expected a single Polygon"
        raise TypeError(msg)
    coords = [(round(x, 4), round(y, 4)) for x, y in simplified.exterior.coords]
    if coords[0] == coords[-1]:
        coords = coords[:-1]
    return tuple(coords)


# Corridors defined by rupture, not official regions. Longitude/latitude pairs, anticlockwise.
NEPAL_HIMALAYA_POLYGON: tuple[tuple[float, float], ...] = (
    (80.0, 28.2),
    (83.0, 27.3),
    (85.5, 26.8),
    (89.0, 26.5),
    (89.0, 28.4),
    (86.5, 28.9),
    (84.0, 29.6),
    (80.0, 30.5),
)
TURKIYE_EAF_POLYGON: tuple[tuple[float, float], ...] = (
    (35.5, 36.6),
    (36.3, 36.0),
    (37.5, 36.0),
    (39.0, 36.6),
    (41.5, 38.4),
    (41.5, 39.5),
    (38.8, 39.5),
    (35.5, 38.0),
)


def default_regions() -> list[Region]:
    """The three Prompt-1 test regions with ``mc=None`` (filled by ``rupture catalog build``)."""
    from rupture.domain import MagnitudePolicy, TectonicSetting  # noqa: PLC0415

    return [
        Region(
            id="california",
            name="California (RELM testing region)",
            polygon=california_relm_polygon(),
            depth_min_km=0.0,
            depth_max_km=30.0,
            tectonic_setting=TectonicSetting.TRANSFORM,
            target_min_magnitude=3.95,
            magnitude_policy=MagnitudePolicy.NETWORK_PREFERRED_AS_MW,
            description=(
                "Outer boundary of the pycsep RELM California region (union of the 7682 0.1-degree "
                "cells, simplified to 158 vertices with the area preserved). RELM conventions: "
                "M >= 3.95, depth <= 30 km. Magnitude policy network-preferred-as-mw (ADR-0019)."
            ),
            references=(
                "Schorlemmer & Gerstenberger 2007, SRL 78(1) (RELM testing region)",
                "Savran et al. 2022, SRL (pycsep; csep.core.regions.california_relm_region)",
            ),
        ),
        Region(
            id="nepal-himalaya",
            name="Nepal Himalaya (Main Himalayan Thrust corridor)",
            polygon=NEPAL_HIMALAYA_POLYGON,
            depth_min_km=0.0,
            depth_max_km=70.0,
            tectonic_setting=TectonicSetting.CONTINENTAL_COLLISION,
            target_min_magnitude=4.7,
            description=(
                "Corridor defined by rupture, not an official region: an octagon following the "
                "Himalayan arc between about 80 and 89 E; the southern edge runs just south of "
                "the Main Frontal Thrust from about 28.2 N in the west to 26.5 N in the east, the "
                "northern edge from about 30.5 N in the west to 28.4 N in the east. Includes the "
                "2015 Gorkha sequence and the 2026-08-26 landslide-type entry us7000tbwb."
            ),
            references=("Avouac 2003, Adv. Geophys. 46 (MHT geometry)",),
        ),
        Region(
            id="turkiye-eaf",
            name="Türkiye, East Anatolian Fault corridor",
            polygon=TURKIYE_EAF_POLYGON,
            depth_min_km=0.0,
            depth_max_km=50.0,
            tectonic_setting=TectonicSetting.TRANSFORM,
            target_min_magnitude=4.6,
            description=(
                "Corridor defined by rupture, not an official region: an octagon along the "
                "left-lateral East Anatolian Fault from the Amanos/Hatay segment near 36 E, 36 N "
                "to the Karliova junction near 41 E, 39.3 N, about 150 km wide. Includes the 2023 "
                "Kahramanmaras doublet."
            ),
            references=("Duman & Emre 2013, Geol. Soc. London Spec. Publ. 372 (EAF segmentation)",),
        ),
    ]
