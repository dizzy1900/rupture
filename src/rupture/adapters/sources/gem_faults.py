"""GEM Global Active Faults Database (GAF; Styron & Pagani 2020), CC-BY-SA-4.0 (ADR-0007).

``fetch_gem_faults`` downloads the harmonised GeoJSON (about 10.6 MB) from the GEM repository,
writes ``data/interim/gem_active_faults.parquet`` (GeoParquet, every attribute kept, attribution
and licence in the Parquet metadata) and a ``provenance.json`` next to it. ``parse_gaf_geojson``
is the pure step used by the unit test on a committed real subset (features intersecting the
Nepal bbox). ``clip_to_region`` intersects the faults with a region polygon.

Everything derived from GAF is CC-BY-SA-4.0 and says so in its metadata.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pyarrow.parquet as pq
import requests

from rupture import __version__
from rupture.adapters.sources.regions import region_polygon
from rupture.domain import Region, sha256_hex, utc_now

SOURCE_ID = "gem-gaf"
ADAPTER_VERSION = "0.1.0"
LICENCE = "CC-BY-SA-4.0"
ATTRIBUTION = (
    "GEM Global Active Faults Database (GEM GAF-DB), Styron, R. & Pagani, M. (2020), "
    "Earthquake Spectra 36(1_suppl), 160-180, doi:10.1177/8755293020944182; (c) GEM Foundation, "
    "CC-BY-SA-4.0"
)
REPO = "GEMScienceTools/gem-global-active-faults"
FILE_PATH = "geojson/gem_active_faults_harmonized.geojson"
DEFAULT_REF = "master"
DEFAULT_PARQUET = Path("data") / "interim" / "gem_active_faults.parquet"


def raw_url(ref: str = DEFAULT_REF) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{ref}/{FILE_PATH}"


def parse_gaf_geojson(payload: bytes | str) -> gpd.GeoDataFrame:
    """Pure: GAF GeoJSON bytes -> GeoDataFrame (EPSG:4326), all properties kept as columns."""
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    doc = json.loads(text)
    if doc.get("type") != "FeatureCollection":
        msg = f"not a GeoJSON FeatureCollection (type={doc.get('type')!r})"
        raise ValueError(msg)
    gdf = gpd.GeoDataFrame.from_features(doc["features"], crs="EPSG:4326")
    gdf.insert(0, "gaf_feature_index", range(len(gdf)))
    return gdf


def _write_parquet(gdf: gpd.GeoDataFrame, path: Path, provenance: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(path, index=False, compression="zstd")
    table = pq.read_table(path)
    extra = {
        b"rupture:source": SOURCE_ID.encode(),
        b"rupture:licence": LICENCE.encode(),
        b"rupture:attribution": ATTRIBUTION.encode(),
        b"rupture:provenance": json.dumps(provenance).encode(),
    }
    pq.write_table(
        table.replace_schema_metadata({**(table.schema.metadata or {}), **extra}),
        path,
        compression="zstd",
    )


def fetch_gem_faults(
    out_parquet: Path = DEFAULT_PARQUET,
    *,
    ref: str = DEFAULT_REF,
    timeout_s: float = 300.0,
) -> tuple[Path, Path]:
    """Download GAF, write GeoParquet + ``provenance.json``; returns both paths. Fetch or raise."""
    url = raw_url(ref)
    headers = {"User-Agent": f"rupture/{__version__} (+https://github.com/dizzy1900/rupture)"}
    resp = requests.get(url, headers=headers, timeout=timeout_s)
    if resp.status_code != 200:
        msg = f"GET {url} -> HTTP {resp.status_code}"
        raise RuntimeError(msg)
    retrieved_at = utc_now()
    content = resp.content
    gdf = parse_gaf_geojson(content)
    prov = provenance_record(url, retrieved_at, sha256_hex(content), n_features=len(gdf), ref=ref)
    _write_parquet(gdf, out_parquet, prov)
    prov_path = out_parquet.with_name(out_parquet.stem + ".provenance.json")
    prov_path.write_text(json.dumps(prov, indent=2) + "\n", encoding="utf-8")
    return out_parquet, prov_path


def provenance_record(
    url: str, retrieved_at: datetime, sha256: str, *, n_features: int, ref: str
) -> dict[str, Any]:
    return {
        "source": SOURCE_ID,
        "source_url": url,
        "repository": f"https://github.com/{REPO}",
        "ref": ref,
        "retrieved_at": retrieved_at.isoformat(),
        "sha256": sha256,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "adapter_version": ADAPTER_VERSION,
        "n_features": n_features,
    }


def load_faults(parquet_path: Path = DEFAULT_PARQUET) -> gpd.GeoDataFrame:
    if not parquet_path.exists():
        msg = f"{parquet_path} not found; run fetch_gem_faults() (network) first"
        raise FileNotFoundError(msg)
    return gpd.read_parquet(parquet_path)


def clip_to_region(faults: gpd.GeoDataFrame, region: Region) -> gpd.GeoDataFrame:
    """Faults intersecting the region polygon, clipped to it. Result stays CC-BY-SA-4.0."""
    poly = region_polygon(region)
    hits = faults[faults.intersects(poly)].copy()
    if hits.empty:
        return hits
    clipped = gpd.clip(hits, poly)
    clipped.attrs["licence"] = LICENCE
    clipped.attrs["attribution"] = ATTRIBUTION
    clipped.attrs["region_id"] = region.id
    return clipped
