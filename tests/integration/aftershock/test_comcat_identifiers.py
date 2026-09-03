"""Network: confirm the two mainshock identifiers against the live ComCat service.

The declared parameters in :mod:`rupture.services.aftershock.sequences` come from the committed
slices, and the offline suite already checks that. This test goes one step further and asks the
live FDSN event service for each id on its own, so a wrong identifier cannot survive on the
strength of a fixture that was cut with the same wrong assumption.

Opt in with ``make test-integration``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.request import urlopen

import pytest

from rupture.services.aftershock.sequences import SEQUENCES

DETAIL_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson&eventid={}"
TIMEOUT_S = 120

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_declared_mainshock_matches_comcat(name: str) -> None:
    spec = SEQUENCES[name]
    declared = spec.mainshock
    with urlopen(DETAIL_URL.format(declared.event_id), timeout=TIMEOUT_S) as response:
        doc = json.loads(response.read())
    props = doc["properties"]
    lon, lat, depth = doc["geometry"]["coordinates"]
    origin = datetime.fromtimestamp(props["time"] / 1000.0, tz=UTC)

    assert props["type"] == "earthquake"
    assert props["magType"].lower().startswith("mw"), (
        f"{declared.event_id}: preferred magnitude is {props['magType']}, not a moment magnitude; "
        "the declared magnitude would not be an identity conversion"
    )
    assert props["mag"] == pytest.approx(declared.magnitude, abs=0.05)
    assert abs((origin - declared.origin_time).total_seconds()) < 1.0
    assert lat == pytest.approx(declared.latitude, abs=0.05)
    assert lon == pytest.approx(declared.longitude, abs=0.05)
    if declared.depth_km is not None:
        assert depth == pytest.approx(declared.depth_km, abs=0.5)


@pytest.mark.parametrize(
    ("event_id", "magnitude"),
    [("us20002ejl", 7.3), ("us6000jlqa", 7.5)],
)
def test_the_two_large_aftershocks_match_comcat(event_id: str, magnitude: float) -> None:
    """The 2015-05-12 M7.3 and the 2023-02-06 M7.5: the events the forecasts are judged on."""
    with urlopen(DETAIL_URL.format(event_id), timeout=TIMEOUT_S) as response:
        doc = json.loads(response.read())
    assert doc["properties"]["mag"] == pytest.approx(magnitude, abs=0.05)
    assert doc["properties"]["type"] == "earthquake"
