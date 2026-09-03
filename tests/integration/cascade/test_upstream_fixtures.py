"""Network checks that the committed cascade fixtures still match their upstream sources.

Opt-in (``make test-integration``). These are the tests that would catch the committed USGS
coefficients or the committed Gorkha product silently diverging from what the USGS now publishes.
They fetch and compare; they never rewrite a fixture.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[3]
CASCADE_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "cascade"
TIMEOUT = 120

pytestmark = pytest.mark.integration


def fetch(url: str) -> bytes:
    response = requests.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    return response.content


@pytest.mark.parametrize(
    "name",
    ["jessee_2018.ini", "zhu_2017_general.ini", "jessee_2018.py.txt", "zhu_2017.py.txt"],
)
def test_the_usgs_coefficient_sources_are_unchanged_upstream(name: str) -> None:
    """A change here means the USGS revised a published model; rupture must not drift silently."""
    base = CASCADE_FIXTURES / "usgs_groundfailure"
    record = json.loads((base / "provenance.json").read_text())["files"][name]
    upstream = fetch(record["source_url"])
    if hashlib.sha256(upstream).hexdigest() != record["sha256"]:
        pytest.fail(
            f"{name} has changed upstream since {record['retrieved_at']}. Re-fetch it, re-record "
            f"provenance, and re-check every coefficient in rupture.cascade.coefficients against "
            f"the new file before touching anything else."
        )


def test_the_gorkha_ground_failure_product_still_exists_and_is_unchanged() -> None:
    """The published product rupture reproduces must still be the one it was cut from."""
    base = CASCADE_FIXTURES / "gorkha-2015"
    record = json.loads((base / "provenance.json").read_text())
    entry = record["files"]["usgs_zhu_2017_general_coverage_slice.csv"]
    upstream = fetch(entry["source_url"])
    assert hashlib.sha256(upstream).hexdigest() == entry["parent_sha256"], (
        "the published Gorkha liquefaction raster has changed; the committed slice and every "
        "number in docs/CASCADE.md were computed from the previous version"
    )


def test_comcat_still_publishes_a_ground_failure_product_for_gorkha() -> None:
    payload = json.loads(
        fetch("https://earthquake.usgs.gov/fdsnws/event/1/query?eventid=us20002926&format=geojson")
    )
    products = payload["properties"]["products"]
    assert "ground-failure" in products
    assert "shakemap" in products
    contents = products["ground-failure"][0]["contents"]
    assert "jessee_2017_model.tif" in contents
    assert "zhu_2017_general_model.tif" in contents


def test_comcat_still_types_us7000tbwb_as_a_landslide() -> None:
    """The discriminator fixture case. Reuses the committed record's id, not its bytes."""
    payload = json.loads(
        fetch("https://earthquake.usgs.gov/fdsnws/event/1/query?eventid=us7000tbwb&format=geojson")
    )
    assert payload["properties"]["type"] == "landslide"
    assert payload["properties"]["mag"] == pytest.approx(5.2, abs=0.1)
