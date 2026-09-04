"""The networked half of the real-event route: fetch a live ShakeMap and run a model on it.

Opt-in (``make test-integration``). The offline suite exercises every code path in
``fetch-shakemap`` with an injected fetcher; this is the only test that actually talks to the USGS
event API, and it is the one that would catch the product layout changing under us.

It fetches Gorkha's own ShakeMap — the event the committed slice was cut from — so the assertion
can be more than "something downloaded": the live grid must contain the committed slice's window
and agree with the committed PGA values there. If the USGS republishes the Atlas grid the two will
diverge, and this test says so rather than the offline suite quietly running on a stale slice.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.cascade import cases, comcat_shakemap, gorkha
from rupture.adapters.cascade.shakemap import read_grid_xml
from rupture.cascade.models import build as build_model
from rupture.domain.common import sha256_hex

REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.integration


def test_fetch_shakemap_writes_a_usable_grid_and_its_provenance(tmp_path: Path) -> None:
    written = comcat_shakemap.fetch_shakemap(gorkha.EVENT_ID, tmp_path / "us20002926")
    payload = written["grid"].read_bytes()
    provenance = json.loads(written["provenance"].read_text())
    assert provenance["sha256"] == sha256_hex(payload)
    assert provenance["source_url"].startswith("https://earthquake.usgs.gov/")
    assert provenance["licence"] == "public-domain (USGS)"

    grid = read_grid_xml(written["grid"], source_url=provenance["source_url"])
    assert grid.event_id == gorkha.EVENT_ID
    assert grid.magnitude == pytest.approx(gorkha.MAGNITUDE, abs=0.1)

    committed = gorkha.load_shakemap(REPO_ROOT)
    lons = committed.longitudes[50:60]
    lats = committed.latitudes[50:60]
    live = grid.ground_motion_field(imt="PGA", lons=lons, lats=lats, scenario_id=gorkha.EVENT_ID)
    offline = committed.ground_motion_field(
        imt="PGA", lons=lons, lats=lats, scenario_id=gorkha.EVENT_ID
    )
    assert np.allclose(live.median(), offline.median(), rtol=1e-6), (
        "the live ShakeMap no longer matches the committed slice; re-cut the fixture and "
        "re-record its provenance rather than loosening this tolerance"
    )


def test_a_fetched_grid_drives_a_ground_failure_model(tmp_path: Path) -> None:
    written = comcat_shakemap.fetch_shakemap(gorkha.EVENT_ID, tmp_path / "us20002926")
    shaking = cases.from_grid_xml(written["grid"], scenario_id=gorkha.EVENT_ID, stride=25)
    field = build_model("landslide", cell_size_deg=shaking.cell_size_deg).evaluate(
        shaking.pgv,
        scenario_id=gorkha.EVENT_ID,
        pga_field=shaking.pga,
        magnitude=shaking.magnitude,
    )
    coverage = np.array([c.probability for c in field.cells], dtype=np.float64)
    assert coverage.size > 100
    assert np.all(np.isfinite(coverage))
    assert 0.0 <= coverage.min() <= coverage.max() <= 1.0
    assert "susceptibility" in (field.notes or "")
