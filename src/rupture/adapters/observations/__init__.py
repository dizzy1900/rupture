"""Observation-source adapters: NGL GNSS, USGS real-time feeds, IRIS FDSN events.

These implement the data port that later adjudication needs. They do not reconstruct
Bletery & Nocquet (or any other) test, and they do not claim GNSS predicts earthquakes.
"""

from rupture.adapters.observations.fdsn_events import FdsnEventSource, parse_fdsn_text
from rupture.adapters.observations.ngl import NglGnssSource, parse_tenv3
from rupture.adapters.observations.usgs_feed import UsgsRealtimeFeed, parse_usgs_feed_geojson

__all__ = [
    "FdsnEventSource",
    "NglGnssSource",
    "UsgsRealtimeFeed",
    "parse_fdsn_text",
    "parse_tenv3",
    "parse_usgs_feed_geojson",
]
