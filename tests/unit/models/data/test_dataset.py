"""Dataset builders refuse post-cutoff events rather than dropping them (ADR-0022 decision 1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import numpy as np
import pytest

from rupture.adapters.forecasting.grid import build_lattice
from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, Region
from rupture.models.data import (
    Projection,
    build_grid_counts,
    build_sequence,
    causal_slice,
    days_between,
    time_edges,
)
from tests.unit.models.conftest import CUTOFF, MC


def test_build_sequence_raises_on_an_event_at_the_cutoff(
    catalog_with_late_event: Catalog, region: Region
) -> None:
    with pytest.raises(LeakageError) as exc:
        build_sequence(catalog_with_late_event, region, CUTOFF, mc=MC)
    assert "late" in str(exc.value)
    assert CUTOFF.isoformat() in str(exc.value)


def test_build_sequence_does_not_filter_late_events_away(
    catalog_with_late_event: Catalog, region: Region
) -> None:
    """The point of raising: the offending event must not simply vanish from the output."""
    with pytest.raises(LeakageError):
        build_sequence(catalog_with_late_event, region, CUTOFF, mc=MC)
    # The explicit filter is the only thing that removes it, and it says so in the catalogue id.
    filtered = causal_slice(catalog_with_late_event, region, CUTOFF, MC)
    assert "late" not in {e.id for e in filtered.events}
    assert build_sequence(filtered, region, CUTOFF, mc=MC) is not None


def test_sequence_is_time_ordered_and_kilometre_projected(
    fixture_catalog: Catalog, region: Region
) -> None:
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    assert len(sequence) > 0
    assert np.all(np.diff(sequence.t) >= 0.0)
    assert sequence.t[0] == pytest.approx(0.0)
    # Round-tripping through the projection recovers the epicentres to metre accuracy.
    lon, lat = sequence.spec.projection.inverse(sequence.x, sequence.y)
    assert np.allclose(lon, sequence.lon, atol=1e-6)
    assert np.allclose(lat, sequence.lat, atol=1e-6)


def test_sequence_before_is_closed_left_open_right(
    fixture_catalog: Catalog, region: Region
) -> None:
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    when = sequence.spec.epoch + timedelta(days=float(sequence.t[10]))
    earlier = sequence.before(when)
    assert len(earlier) == 10
    assert float(earlier.t.max()) < sequence.days_of(when)


def test_sequence_spec_round_trips(fixture_catalog: Catalog, region: Region) -> None:
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    from rupture.models.data.dataset import SequenceSpec  # noqa: PLC0415 - local to the assertion

    assert SequenceSpec.from_dict(sequence.spec.to_dict()) == sequence.spec


def test_build_sequence_refuses_events_below_mc(fixture_catalog: Catalog, region: Region) -> None:
    unfiltered = fixture_catalog.earthquakes().before(CUTOFF)
    with pytest.raises(ValueError, match="below mc"):
        build_sequence(unfiltered, region, CUTOFF, mc=4.5)


def test_grid_counts_refuse_a_bin_that_straddles_the_cutoff(
    fixture_catalog: Catalog, region: Region
) -> None:
    clean = causal_slice(fixture_catalog, region, CUTOFF, MC)
    edges = [CUTOFF - timedelta(days=60), CUTOFF - timedelta(days=30), CUTOFF + timedelta(days=30)]
    with pytest.raises(LeakageError, match="after the cutoff"):
        build_grid_counts(clean, region, CUTOFF, edges=edges)


def test_grid_counts_land_on_the_protocol_lattice_and_bins(
    fixture_catalog: Catalog, region: Region
) -> None:
    clean = causal_slice(fixture_catalog, region, CUTOFF, MC)
    edges = time_edges(datetime(2018, 1, 1, tzinfo=UTC), CUTOFF, timedelta(days=90))
    counts = build_grid_counts(clean, region, CUTOFF, edges=edges)
    lattice = build_lattice(region)
    assert counts.counts.shape == (
        len(edges) - 1,
        lattice.n_cells,
        len(region.magnitude_bin_edges()),
    )
    assert counts.cell_origins == lattice.origins
    assert counts.magnitude_bin_edges == region.magnitude_bin_edges()
    # Every counted event is at or above the target threshold and inside the binned span.
    binned = int(counts.counts.sum())
    expected = (
        len(clean.at_least(region.target_min_magnitude).between(edges[0], edges[-1]))
        - counts.n_outside_grid
    )
    assert binned == expected


def test_grid_counts_raise_on_a_post_cutoff_event(
    catalog_with_late_event: Catalog, region: Region
) -> None:
    edges = time_edges(datetime(2018, 1, 1, tzinfo=UTC), CUTOFF, timedelta(days=90))
    with pytest.raises(LeakageError, match="origin_time >="):
        build_grid_counts(catalog_with_late_event, region, CUTOFF, edges=edges)


def test_time_edges_never_pass_the_end() -> None:
    edges = time_edges(datetime(2018, 1, 1, tzinfo=UTC), CUTOFF, timedelta(days=100))
    assert edges[0] == datetime(2018, 1, 1, tzinfo=UTC)
    assert edges[-1] <= CUTOFF
    assert all(b - a == timedelta(days=100) for a, b in pairwise(edges))


def test_projection_is_exact_at_its_origin() -> None:
    projection = Projection(lon0=-118.0, lat0=35.0)
    x, y = projection.forward([-118.0], [35.0])
    assert float(x[0]) == pytest.approx(0.0, abs=1e-9)
    assert float(y[0]) == pytest.approx(0.0, abs=1e-9)


def test_projection_distance_from_the_origin_is_a_great_circle_distance() -> None:
    projection = Projection(lon0=-118.0, lat0=35.0)
    x, y = projection.forward([-118.0], [36.0])
    one_degree_km = projection.radius_km * np.pi / 180.0
    assert float(np.hypot(x[0], y[0])) == pytest.approx(one_degree_km, rel=1e-9)


def test_days_between_is_signed_and_in_days() -> None:
    assert days_between(CUTOFF, CUTOFF + timedelta(hours=36)) == pytest.approx(1.5)
    assert days_between(CUTOFF, CUTOFF - timedelta(days=2)) == pytest.approx(-2.0)
