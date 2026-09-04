"""Fetch the published ShakeMap ``grid.xml`` for a real ComCat event, with provenance.

This is the "real events" half of the layer's input contract: given a ComCat event id, find the
event's preferred ``shakemap`` product, download its ``grid.xml``, and write it next to a
``provenance.json`` recording the exact URL, the retrieval time, the sha256 of the bytes and the
licence. :func:`rupture.adapters.cascade.shakemap.read_grid_xml` then parses it, and
:mod:`rupture.adapters.cascade.cases` feeds it to the ground-failure models.

Two deliberate choices:

* **The USGS event API, not libcomcat.** ``libcomcat`` is an optional extra in ``pyproject.toml``
  and would be a heavyweight import for one JSON document and one file. The FDSN event detail
  endpoint returns the product index directly, so rupture reads it with the same ``requests``
  every other adapter uses. A caller who has libcomcat can pass the product URL it found through
  ``--url`` instead, which is why that option exists.
* **Fetch or fail loudly.** There is no cache fallback and no partial write: if the event has no
  ShakeMap product, or the download fails, the function raises and nothing is written. Nothing in
  this module can produce a grid rupture did not receive.

Network, therefore never exercised by ``tests/unit``: the offline tests inject a fetcher and check
the URL selection, the provenance record and the failure messages;
``tests/integration/cascade/`` is where it may touch the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from rupture import __version__
from rupture.domain.common import sha256_hex, utc_now

ADAPTER_VERSION = "0.1.0"
LICENCE = "public-domain (USGS)"
DETAIL_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query?eventid={event_id}&format=geojson"
GRID_FILE = "grid.xml"
PROVENANCE_FILE = "provenance.json"
DEFAULT_TIMEOUT_S = 300.0

Fetcher = Callable[[str], bytes]
"""URL to bytes. Injected so the offline suite can exercise every path but the socket."""


class ShakeMapFetchError(RuntimeError):
    """The ShakeMap could not be fetched, or the event has none."""


def _user_agent() -> str:
    return f"rupture/{__version__} (+https://github.com/dizzy1900/rupture)"


def http_fetch(url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> bytes:
    """The default fetcher: one GET, no retries, raise for status."""
    response = requests.get(url, headers={"User-Agent": _user_agent()}, timeout=timeout_s)
    if response.status_code != requests.codes.ok:
        msg = f"GET {url} returned {response.status_code}"
        raise ShakeMapFetchError(msg)
    return bytes(response.content)


@dataclass(frozen=True, slots=True)
class ShakeMapProduct:
    """The bits of a ComCat ``shakemap`` product rupture needs."""

    event_id: str
    grid_url: str
    shakemap_version: str | None
    magnitude: float | None
    longitude: float | None
    latitude: float | None
    origin_time_ms: int | None
    title: str | None


def select_grid_url(detail: dict[str, Any], *, event_id: str) -> ShakeMapProduct:
    """Pick the preferred ``shakemap`` product's ``grid.xml`` out of an event detail document.

    ComCat orders each product list with the preferred contribution first, so rupture takes the
    first entry rather than inventing a preference rule of its own.
    """
    properties = detail.get("properties") or {}
    products = (properties.get("products") or {}).get("shakemap") or []
    if not products:
        msg = (
            f"ComCat event {event_id} has no shakemap product; rupture cannot compute a "
            f"ground-failure field for it from a ShakeMap"
        )
        raise ShakeMapFetchError(msg)
    product = products[0]
    contents = product.get("contents") or {}
    entry = contents.get("download/grid.xml") or contents.get("grid.xml")
    if not entry or not entry.get("url"):
        available = ", ".join(sorted(contents)) or "none"
        msg = (
            f"the shakemap product for {event_id} has no download/grid.xml; "
            f"contents are: {available}"
        )
        raise ShakeMapFetchError(msg)
    geometry = (detail.get("geometry") or {}).get("coordinates") or []
    return ShakeMapProduct(
        event_id=event_id,
        grid_url=str(entry["url"]),
        shakemap_version=(
            str(product["properties"]["version"])
            if product.get("properties", {}).get("version") is not None
            else None
        ),
        magnitude=float(properties["mag"]) if properties.get("mag") is not None else None,
        longitude=float(geometry[0]) if len(geometry) > 0 else None,
        latitude=float(geometry[1]) if len(geometry) > 1 else None,
        origin_time_ms=int(properties["time"]) if properties.get("time") is not None else None,
        title=properties.get("title"),
    )


def fetch_shakemap(
    event_id: str,
    out_dir: Path,
    *,
    fetcher: Fetcher | None = None,
    grid_url: str | None = None,
) -> dict[str, Path]:
    """Download ``grid.xml`` for ``event_id`` into ``out_dir`` and record its provenance.

    ``grid_url`` short-circuits the product lookup for a caller who already has the URL (from
    libcomcat, say). Returns the paths written.
    """
    get = fetcher or http_fetch
    if grid_url is None:
        detail_url = DETAIL_URL.format(event_id=event_id)
        detail = json.loads(get(detail_url).decode("utf-8"))
        product = select_grid_url(detail, event_id=event_id)
    else:
        detail_url = None
        product = ShakeMapProduct(
            event_id=event_id,
            grid_url=grid_url,
            shakemap_version=None,
            magnitude=None,
            longitude=None,
            latitude=None,
            origin_time_ms=None,
            title=None,
        )
    payload = get(product.grid_url)
    if b"<grid_specification" not in payload:
        msg = (
            f"{product.grid_url} did not return a ShakeMap grid.xml "
            f"(no <grid_specification> in {len(payload)} bytes)"
        )
        raise ShakeMapFetchError(msg)
    retrieved_at = utc_now()
    out_dir.mkdir(parents=True, exist_ok=True)
    grid_path = out_dir / GRID_FILE
    grid_path.write_bytes(payload)
    provenance = {
        "source": "usgs-comcat-products",
        "source_url": product.grid_url,
        "detail_url": detail_url,
        "retrieved_at": retrieved_at.isoformat(),
        "sha256": sha256_hex(payload),
        "licence": LICENCE,
        "adapter_version": ADAPTER_VERSION,
        "event": {
            "id": event_id,
            "title": product.title,
            "magnitude": product.magnitude,
            "longitude": product.longitude,
            "latitude": product.latitude,
            "origin_time_ms": product.origin_time_ms,
            "shakemap_version": product.shakemap_version,
        },
        "rule": (
            "fetched, never edited by hand; re-fetch with "
            f"`rupture cascade fetch-shakemap --event {event_id}` and re-record this file"
        ),
        "files": {GRID_FILE: {"sha256": sha256_hex(payload), "size": len(payload)}},
    }
    provenance_path = out_dir / PROVENANCE_FILE
    provenance_path.write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {"grid": grid_path, "provenance": provenance_path}
