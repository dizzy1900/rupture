"""Real Ridgecrest / Gorkha slices for the one-neuron comparator tests.

Every event comes from a committed ComCat GeoJSON with provenance. Nothing here is synthesised.
The Ridgecrest box is small so a fit is cheap; the cutoff sits after the M7.1 so the sequence
is actually in the training window. The Gorkha slice is the 30-day aftershock catalogue paired
with the USGS NEIC finite-fault table, which is the only committed slip model in the tree.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from tests.fixtures.forecasting.loader import load_fixture_catalog

from rupture.adapters.catalogs.comcat import parse_comcat_geojson
from rupture.domain import (
    Catalog,
    Event,
    Provenance,
    Region,
    TectonicSetting,
    utc_now,
)
from rupture.models.comparators.logistic import OneNeuronAftershockModel

CUTOFF = datetime(2019, 8, 1, tzinfo=UTC)
ISSUE = CUTOFF
HORIZON = timedelta(days=30)
MC = 3.5
M_MAIN = 6.0

REPO_ROOT = Path(__file__).resolve().parents[4]
GORKHA_GEOJSON = REPO_ROOT / "data" / "fixtures" / "comcat" / "gorkha-2015-30d-m4.geojson"
GORKHA_FSP = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "risk"
    / "scenarios"
    / "gorkha2015"
    / "complete_inversion.fsp"
)
GORKHA_CUTOFF = datetime(2015, 5, 15, tzinfo=UTC)
GORKHA_MC = 4.0
GORKHA_M_MAIN = 7.0


@pytest.fixture(scope="session")
def fixture_catalog() -> Catalog:
    return load_fixture_catalog()


@pytest.fixture(scope="session")
def ridgecrest_region() -> Region:
    """A box around the 2019 Ridgecrest sequence; test-only, not a protocol region."""
    return Region(
        id="ridgecrest-one-neuron-box",
        name="Ridgecrest one-neuron test box",
        polygon=((-118.5, 35.2), (-116.8, 35.2), (-116.8, 36.5), (-118.5, 36.5)),
        depth_max_km=30.0,
        tectonic_setting=TectonicSetting.TRANSFORM,
        cell_size_deg=0.25,
        target_min_magnitude=MC,
        magnitude_bin_width=0.5,
        magnitude_max=7.95,
        description="Test-only rectangle around Ridgecrest; not a protocol region.",
    )


@pytest.fixture(scope="session")
def training(fixture_catalog: Catalog) -> Catalog:
    return fixture_catalog.earthquakes().before(CUTOFF).at_least(MC)


@pytest.fixture(scope="session")
def fitted(fixture_catalog: Catalog, ridgecrest_region: Region) -> OneNeuronAftershockModel:
    model = OneNeuronAftershockModel(m_main=M_MAIN, mc=MC)
    model.fit(fixture_catalog, ridgecrest_region, CUTOFF)
    return model


@pytest.fixture(scope="session")
def gorkha_catalog() -> Catalog:
    payload = GORKHA_GEOJSON.read_bytes()
    provenance = Provenance(
        source="usgs-comcat",
        source_url="https://earthquake.usgs.gov/fdsnws/event/1/query",
        retrieved_at=utc_now(),
        licence="public-domain (USGS)",
        adapter_version="tests.unit.models.comparators.conftest",
        notes="committed Gorkha 30-day ComCat slice; magnitudes labelled reported-as-mw",
    )
    events = parse_comcat_geojson(payload, provenance=provenance)
    labelled = tuple(_reported_as_mw(event) for event in events)
    return Catalog(
        id="fixture-comcat-gorkha-2015-30d-m4",
        region_id="gorkha-one-neuron-box",
        events=labelled,
        sources=("usgs-comcat",),
        built_at=provenance.retrieved_at,
        builder_version="tests.unit.models.comparators.conftest",
        notes="real ComCat Gorkha slice; mw is the reported preferred magnitude",
    )


@pytest.fixture(scope="session")
def gorkha_region() -> Region:
    return Region(
        id="gorkha-one-neuron-box",
        name="Gorkha one-neuron test box",
        polygon=((84.0, 27.4), (86.0, 27.4), (86.0, 28.8), (84.0, 28.8)),
        depth_max_km=40.0,
        tectonic_setting=TectonicSetting.CONTINENTAL_COLLISION,
        cell_size_deg=0.2,
        target_min_magnitude=GORKHA_MC,
        magnitude_bin_width=0.5,
        magnitude_max=8.45,
        description="Test-only rectangle around Gorkha; not a protocol region.",
    )


def _reported_as_mw(event: Event) -> Event:
    if event.mw is not None:
        return event
    return event.model_copy(
        update={
            "mw": event.magnitude.value,
            "mw_conversion": f"reported-as-mw:{event.magnitude.type.value}",
        }
    )


def load_gorkha_subfaults() -> tuple[list[float], list[float], list[float]]:
    """Lon, lat, slip (m) rows of the committed USGS NEIC Gorkha finite-fault table."""
    lons: list[float] = []
    lats: list[float] = []
    slips: list[float] = []
    for line in GORKHA_FSP.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        cells = stripped.split()
        if len(cells) < 6:
            continue
        try:
            lat = float(cells[0])
            lon = float(cells[1])
            slip = float(cells[5])
        except ValueError:
            continue
        lats.append(lat)
        lons.append(lon)
        slips.append(slip)
    return lons, lats, slips
