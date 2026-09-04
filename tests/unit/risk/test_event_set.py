"""Sampling a stochastic event set from a promoted F1 forecast (ADR-0036).

Every test here runs on the **committed real slice** of an issued ETAS ``ForecastGrid``
(``tests/fixtures/risk/forecast/``), not on a grid the test invented, so what is exercised is the
join rupture actually ships.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter

import numpy as np
import pytest

from rupture.domain.forecast import ForecastGrid
from rupture.domain.region import Region
from rupture.risk import event_set as es
from tests.unit.risk.conftest import REPO_ROOT, RISK_FIXTURES

FORECAST_DIR = RISK_FIXTURES / "forecast"
SLICE_FILE = FORECAST_DIR / "trishuli-corridor-slice.json"


@pytest.fixture(scope="module")
def grid() -> ForecastGrid:
    return ForecastGrid.model_validate(json.loads(SLICE_FILE.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def region() -> Region:
    path = REPO_ROOT / "data" / "regions" / "nepal-himalaya" / "region.json"
    return Region.model_validate(json.loads(path.read_text(encoding="utf-8")))


def test_the_committed_slice_matches_the_digest_its_provenance_records() -> None:
    record = json.loads((FORECAST_DIR / "provenance.json").read_text(encoding="utf-8"))
    entry = record["files"][0]
    payload = SLICE_FILE.read_text(encoding="utf-8").rstrip("\n")
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == entry["sha256"]
    assert record["parent_grid_id"].startswith("etas-mizrahi-nepal-himalaya")
    assert record["cells_kept"] < record["cells_in_parent"]


def test_sampling_reproduces_the_grid_rate_in_expectation(grid: ForecastGrid) -> None:
    """The Poisson draw must be unbiased: many catalogues converge on the grid's own rate."""
    cfg = es.SamplingConfig(
        n_catalogues=4000, catalogue_duration_years=1.0, min_magnitude=0.0, seed=11
    )
    ses = es.sample_from_forecast_grid(grid, config=cfg)
    expected = grid.total_expected() * cfg.catalogue_duration_years / es.horizon_years(grid.horizon)
    assert ses.total_annual_rate == pytest.approx(expected, rel=0.05)
    assert ses.expected_events_per_catalogue == pytest.approx(expected, rel=1e-9)


def test_every_event_carries_the_same_rate_and_they_sum_to_the_set_rate(
    grid: ForecastGrid,
) -> None:
    ses = es.sample_from_forecast_grid(grid, config=es.SamplingConfig(n_catalogues=200, seed=3))
    rates = {e.annual_rate for e in ses.events}
    assert len(rates) == 1
    assert next(iter(rates)) == pytest.approx(1.0 / (200 * 1.0))
    assert len(ses.catalogues()) == 200


def test_sampling_is_deterministic_under_a_seed(grid: ForecastGrid) -> None:
    a = es.sample_from_forecast_grid(grid, config=es.SamplingConfig(n_catalogues=50, seed=5))
    b = es.sample_from_forecast_grid(grid, config=es.SamplingConfig(n_catalogues=50, seed=5))
    assert [e.id for e in a.events] == [e.id for e in b.events]
    assert [e.magnitude for e in a.events] == [e.magnitude for e in b.events]


def test_events_lie_in_their_cells_and_above_the_threshold(grid: ForecastGrid) -> None:
    ses = es.sample_from_forecast_grid(
        grid, config=es.SamplingConfig(n_catalogues=100, min_magnitude=5.2, seed=9)
    )
    lons = [lon for lon, _ in grid.cell_origins]
    lats = [lat for _, lat in grid.cell_origins]
    for event in ses.events:
        assert event.magnitude >= 5.2
        assert min(lons) <= event.longitude <= max(lons) + grid.cell_size_deg
        assert min(lats) <= event.latitude <= max(lats) + grid.cell_size_deg
        assert event.depth_km == es.DEFAULT_DEPTH_KM


def test_magnitudes_follow_the_supplied_b_value(grid: ForecastGrid) -> None:
    """A steeper b puts proportionally fewer events in the upper magnitude bins."""
    shallow = es.sample_from_forecast_grid(
        grid,
        config=es.SamplingConfig(n_catalogues=800, min_magnitude=4.7, b_value=0.6, seed=17),
    )
    steep = es.sample_from_forecast_grid(
        grid,
        config=es.SamplingConfig(n_catalogues=800, min_magnitude=4.7, b_value=1.6, seed=17),
    )
    assert float(np.mean([e.magnitude for e in shallow.events])) > float(
        np.mean([e.magnitude for e in steep.events])
    )


def test_the_regions_fitted_b_value_is_preferred_over_the_assumed_one(
    grid: ForecastGrid, region: Region
) -> None:
    ses = es.sample_from_forecast_grid(
        grid, config=es.SamplingConfig(n_catalogues=10, seed=1), region=region
    )
    assert any("fitted" in a for a in ses.assumptions)
    without = es.sample_from_forecast_grid(grid, config=es.SamplingConfig(n_catalogues=10, seed=1))
    assert any("ASSUMED b" in a for a in without.assumptions)


def test_the_annualisation_factor_is_reported(grid: ForecastGrid) -> None:
    ses = es.sample_from_forecast_grid(
        grid, config=es.SamplingConfig(n_catalogues=10, catalogue_duration_years=0.5, seed=1)
    )
    assert ses.horizon_scaling == pytest.approx(0.5 / es.horizon_years(grid.horizon))
    assert any("if this rate persisted" in a for a in ses.assumptions)


def test_the_forecasts_fit_cutoff_is_carried_so_leakage_can_be_checked(
    grid: ForecastGrid,
) -> None:
    """Nothing in an event set may post-date what the forecast was allowed to see."""
    ses = es.sample_from_forecast_grid(grid, config=es.SamplingConfig(n_catalogues=5, seed=1))
    assert ses.fit_cutoff == grid.fit_cutoff.isoformat()
    assert ses.provenance.notes is not None
    assert "fit cutoff" in ses.provenance.notes
    assert ses.provenance.sha256 == grid.parameter_snapshot_hash


def test_the_guard_refuses_a_runaway_sampling_rather_than_truncating(grid: ForecastGrid) -> None:
    with pytest.raises(es.EventSetError, match="max_events guard"):
        es.sample_from_forecast_grid(
            grid,
            config=es.SamplingConfig(
                n_catalogues=100_000, min_magnitude=0.0, max_events=100, seed=1
            ),
        )


def test_every_event_becomes_a_point_rupture_that_says_so(grid: ForecastGrid) -> None:
    ses = es.sample_from_forecast_grid(grid, config=es.SamplingConfig(n_catalogues=20, seed=2))
    assert ses.events
    rupture = ses.events[0].rupture()
    assert rupture.corners == ()
    assert rupture.hypothetical is True
    assert rupture.notes is not None
    assert "POINT" in rupture.notes


def test_catalogue_membership_partitions_the_events(grid: ForecastGrid) -> None:
    ses = es.sample_from_forecast_grid(grid, config=es.SamplingConfig(n_catalogues=40, seed=4))
    counts = Counter(e.catalogue for e in ses.events)
    assert sum(counts.values()) == len(ses.events)
    assert max(counts) < 40
    assert sum(len(c) for c in ses.catalogues()) == len(ses.events)
