"""Shared paths and builders for the offline risk tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rupture.domain.common import Provenance
from rupture.domain.groundmotion import Site
from rupture.domain.hazard import ScenarioRupture

REPO_ROOT = Path(__file__).resolve().parents[3]
GSIM_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "risk" / "gsim"
RISK_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "risk"


@pytest.fixture
def provenance() -> Provenance:
    return Provenance(
        source="test",
        retrieved_at=datetime(2026, 9, 3, tzinfo=UTC),
        adapter_version="0.0.0",
        licence="none",
    )


def site(identifier: str, lon: float, lat: float, vs30: float = 600.0) -> Site:
    return Site(id=identifier, longitude=lon, latitude=lat, vs30=vs30)


@pytest.fixture
def crustal_rupture() -> ScenarioRupture:
    """A small vertical strike-slip rupture; geometry is an input to the distance code."""
    return ScenarioRupture(
        id="unit-crustal",
        magnitude=6.5,
        hypocentre_longitude=85.0,
        hypocentre_latitude=28.0,
        hypocentre_depth_km=10.0,
        strike=0.0,
        dip=90.0,
        rake=0.0,
        tectonic_region="Active Shallow Crust",
        corners=(
            (85.0, 27.8, 0.0),
            (85.0, 28.2, 0.0),
            (85.0, 28.2, 15.0),
            (85.0, 27.8, 15.0),
        ),
        hypothetical=True,
    )
