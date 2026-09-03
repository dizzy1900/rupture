"""Fixtures for the learned-model tests: the real ComCat slice and the test region.

Everything here is a slice of a committed real catalogue (``tests/fixtures/forecasting/``), never
synthesised data. Where a test needs a specific pathological timestamp it *shifts* a real event
rather than inventing one, so the leakage assertions are exercised against real origin times.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rupture.domain import Catalog, Region
from tests.fixtures.forecasting.loader import fixture_region, load_fixture_catalog

CUTOFF = datetime(2019, 7, 1, tzinfo=UTC)
MC = 3.0


@pytest.fixture(scope="session")
def fixture_catalog() -> Catalog:
    return load_fixture_catalog()


@pytest.fixture(scope="session")
def region() -> Region:
    return fixture_region()


@pytest.fixture
def catalog_with_late_event(fixture_catalog: Catalog) -> Catalog:
    """The pre-cutoff slice plus one real event moved to exactly the cutoff.

    Exactly the cutoff, not after it: the window is half-open, so an event *at* the cutoff must be
    refused too, and an off-by-one that used ``<=`` would otherwise pass every test.
    """
    clean = fixture_catalog.earthquakes().before(CUTOFF).at_least(MC)
    late = clean.events[-1].model_copy(update={"id": "late", "origin_time": CUTOFF})
    return clean.model_copy(update={"events": (*clean.events, late)})


@pytest.fixture
def short_history(fixture_catalog: Catalog) -> Catalog:
    """A small real slice: three months before the cutoff, earthquakes at or above Mc."""
    start = CUTOFF - timedelta(days=90)
    return fixture_catalog.earthquakes().at_least(MC).between(start, CUTOFF)
