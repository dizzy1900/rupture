"""Half-open ``available_as_of`` on the committed NGL fixture (ADR-0054)."""

from __future__ import annotations

from rupture.adapters.observations.ngl import NglGnssSource, parse_tenv3
from rupture.domain import VintagePolicy
from rupture.domain.observation import GnssProduct, readable_as_of
from tests.unit.observations.conftest import fixture_file


def _source() -> NglGnssSource:
    fx = fixture_file("gnss/ngl", "P595.tenv3.head")
    positions = parse_tenv3(fx.content, provenance=fx.provenance, product=GnssProduct.FINAL)
    return NglGnssSource("P595", positions=positions, product=GnssProduct.FINAL)


def test_available_as_of_excludes_final_positions_not_yet_readable() -> None:
    source = _source()
    series = source.series()
    as_of = series[-1].available_time
    kept = source.available_as_of(as_of, policy=VintagePolicy.EXCLUDE_UNKNOWN)
    assert len(kept) == len(series) - 1
    assert all(readable_as_of(p.available_time, as_of) for p in kept)
    assert all(p.available_time < as_of for p in kept)


def test_available_time_equal_to_as_of_is_excluded_half_open() -> None:
    """Negative twin: the boundary is excluded, not served."""
    source = _source()
    series = source.series()
    boundary = series[0].available_time
    kept = source.available_as_of(boundary, policy=VintagePolicy.EXCLUDE_UNKNOWN)
    assert series[0] not in kept
    assert all(p.available_time != boundary for p in kept)
    assert all(p.available_time < boundary for p in kept)


def test_as_of_before_any_available_time_is_empty() -> None:
    source = _source()
    earliest = min(p.available_time for p in source.series())
    kept = source.available_as_of(earliest, policy=VintagePolicy.EXCLUDE_UNKNOWN)
    assert kept == ()
