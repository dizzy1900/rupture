"""NGL tenv3 parser on the committed P595 prefix (Ridgecrest-area station)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from rupture.adapters.observations.ngl import (
    FINAL_ORBIT_LAG,
    RAPID_ORBIT_LAG,
    NglGnssSource,
    lag_for_product,
    parse_tenv3,
    stamp_available_time,
)
from rupture.domain import Provenance
from rupture.domain.observation import GnssPosition, GnssProduct, ObservableKind
from tests.unit.observations.conftest import FIXTURES, fixture_file


def test_p595_fixture_parses_station_finite_coordinates_and_provenance() -> None:
    fx = fixture_file("gnss/ngl", "P595.tenv3.head")
    positions = parse_tenv3(fx.content, provenance=fx.provenance, product=GnssProduct.FINAL)
    assert len(positions) == 21
    assert all(p.station_id == "P595" for p in positions)
    assert all(
        math.isfinite(p.east_m) and math.isfinite(p.north_m) and math.isfinite(p.up_m)
        for p in positions
    )
    assert all(p.provenance.sha256 == fx.provenance.sha256 for p in positions)
    assert all(p.product is GnssProduct.FINAL for p in positions)
    first = positions[0]
    assert first.valid_time == datetime(2005, 10, 22, tzinfo=UTC)
    assert first.east_m == -256 + -0.595907
    assert first.available_time == first.valid_time + FINAL_ORBIT_LAG


def test_final_and_rapid_lags_are_named_constants_not_inline_arithmetic() -> None:
    instant = datetime(2019, 7, 4, tzinfo=UTC)
    assert lag_for_product(GnssProduct.FINAL) is FINAL_ORBIT_LAG
    assert lag_for_product(GnssProduct.RAPID) is RAPID_ORBIT_LAG
    assert (
        stamp_available_time(instant, GnssProduct.FINAL, publish_stamp=None)
        == instant + timedelta(days=14)
    )
    assert (
        stamp_available_time(instant, GnssProduct.RAPID, publish_stamp=None)
        == instant + timedelta(days=1)
    )
    published = datetime(2019, 7, 5, 12, tzinfo=UTC)
    assert stamp_available_time(instant, GnssProduct.FINAL, publish_stamp=published) == published


def test_available_time_has_no_default() -> None:
    provenance = Provenance(
        source="ngl-gnss",
        retrieved_at=datetime(2026, 9, 13, tzinfo=UTC),
        adapter_version="test",
    )
    with pytest.raises(ValidationError):
        GnssPosition(  # type: ignore[call-arg]
            station_id="P595",
            valid_time=datetime(2005, 10, 22, tzinfo=UTC),
            east_m=0.0,
            north_m=0.0,
            up_m=0.0,
            sigma_e=0.001,
            sigma_n=0.001,
            sigma_u=0.001,
            product=GnssProduct.FINAL,
            provenance=provenance,
        )


def test_offline_source_loads_the_fixture_without_fetching() -> None:
    source = NglGnssSource("P595", offline_fixtures=FIXTURES)
    assert source.kind is ObservableKind.GNSS_POSITION
    series = source.series()
    assert series[0].station_id == "P595"
    assert len(series) == 21
