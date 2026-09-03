"""rupture.adapters.catalogs — event sources implementing the ``CatalogSource`` port.

Each adapter is a pure ``parse_*`` function (raw payload -> events) plus a thin fetch class.
``make_sources`` builds instances by id for the pipeline and CLI.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from rupture.adapters.catalogs.comcat import ComCatSource, parse_comcat_geojson
from rupture.adapters.catalogs.gcmt import GcmtSource, parse_ndk
from rupture.adapters.catalogs.isc import IscSource, parse_isc_text
from rupture.adapters.catalogs.isc_gem import (
    IscGemSource,
    IscGemUnavailableError,
    parse_isc_gem_csv,
)
from rupture.ports.catalog_source import CatalogSource

SOURCE_IDS: tuple[str, ...] = ("comcat", "isc", "gcmt", "isc-gem")
"""CLI names, in the order they are listed in ``--sources``."""

# CLI name -> source_id as recorded on events
CLI_TO_SOURCE_ID: dict[str, str] = {
    "comcat": "usgs-comcat",
    "isc": "isc",
    "gcmt": "gcmt",
    "isc-gem": "isc-gem",
}


def make_sources(
    names: Iterable[str],
    *,
    offline_fixtures: Path | None = None,
    raw_dir: Path | None = None,
) -> list[CatalogSource]:
    """Instantiate adapters by CLI name. Unknown names raise ``ValueError``.

    ``raw_dir`` (``data/raw``) is where online fetches cache their raw payloads; ignored offline.
    """
    out: list[CatalogSource] = []
    for raw_name in names:
        name = raw_name.strip().lower().replace("_", "-")
        if name == "comcat":
            out.append(
                ComCatSource(
                    offline_fixtures=offline_fixtures,
                    cache_dir=None if raw_dir is None else raw_dir / "comcat",
                )
            )
        elif name == "isc":
            out.append(
                IscSource(
                    offline_fixtures=offline_fixtures,
                    cache_dir=None if raw_dir is None else raw_dir / "isc",
                )
            )
        elif name == "gcmt":
            out.append(
                GcmtSource(
                    offline_fixtures=offline_fixtures,
                    cache_dir=None if raw_dir is None else raw_dir / "gcmt",
                )
            )
        elif name in {"isc-gem", "iscgem"}:
            out.append(IscGemSource(offline_fixtures=offline_fixtures))
        else:
            msg = f"unknown catalogue source {raw_name!r}; known: {', '.join(SOURCE_IDS)}"
            raise ValueError(msg)
    return out


__all__ = [
    "CLI_TO_SOURCE_ID",
    "SOURCE_IDS",
    "ComCatSource",
    "GcmtSource",
    "IscGemSource",
    "IscGemUnavailableError",
    "IscSource",
    "make_sources",
    "parse_comcat_geojson",
    "parse_isc_gem_csv",
    "parse_isc_text",
    "parse_ndk",
]
