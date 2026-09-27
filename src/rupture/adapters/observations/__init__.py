"""Observation-source adapters below the catalogue: NGL GNSS daily positions.

These implement the data port that later adjudication needs. They do not reconstruct
Bletery & Nocquet (or any other) test, and they do not claim GNSS predicts earthquakes.

The catalogue-shaped observation feeds (USGS real-time GeoJSON, FDSN event text) emit
``Catalog`` records and live in :mod:`rupture.adapters.catalogs` beside ComCat, whose parsing
they reuse. HTTP fetch and fixture loading are shared adapter infrastructure in
:mod:`rupture.adapters._http` and :mod:`rupture.adapters.fixtures` (ADR-0071).
"""

from rupture.adapters.observations.ngl import NglGnssSource, parse_tenv3

__all__ = [
    "NglGnssSource",
    "parse_tenv3",
]
