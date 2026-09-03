"""Scoring: the target slice, the Poisson count check on each rung, and the report."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from rupture.adapters.forecasting.grid import build_lattice
from rupture.domain import (
    AftershockForecast,
    Catalog,
    ForecastGrid,
    MagnitudeProbability,
    Region,
    snapshot_hash,
    utc_now,
)
from rupture.services.aftershock.evaluation import (
    CsepOutcome,
    SequenceOutcome,
    WindowOutcome,
    observed_in_window,
    render_markdown,
    score_thresholds,
    write_report,
)
from rupture.services.aftershock.forecaster import AftershockForecaster
from rupture.services.aftershock.sequences import SequenceSpec

MAINSHOCK_TIME = datetime(2015, 4, 25, 6, 11, 25, 950000, tzinfo=UTC)  # us20002926


def _forecast(rungs: tuple[tuple[float, float], ...]) -> AftershockForecast:
    return AftershockForecast(
        id="f",
        mainshock_event_id="us20002926",
        mainshock_time=MAINSHOCK_TIME,
        mainshock_magnitude=7.8,
        region_id="aftershock-us20002926",
        issue_time=MAINSHOCK_TIME,
        horizon=timedelta(days=1),
        elapsed=timedelta(0),
        model_id="etas-mizrahi",
        model_version="v",
        parameter_snapshot_hash=snapshot_hash({}),
        n_sequence_events=1,
        probabilities=tuple(
            MagnitudeProbability(magnitude=m, probability=-math.expm1(-lam), expected_count=lam)
            for m, lam in rungs
        ),
        created_at=utc_now(),
    )


def test_score_thresholds_counts_and_flags(gorkha_catalog: Catalog) -> None:
    """The first day of the Gorkha sequence: many M>=4.8, one M>=5.8, none M>=6.8 except..."""
    window = gorkha_catalog.between(MAINSHOCK_TIME, MAINSHOCK_TIME + timedelta(days=1))
    forecast = _forecast(((4.8, 2.6), (5.8, 0.19), (6.8, 0.014), (7.8, 0.001)))
    outcomes = score_thresholds(forecast, window)
    assert [o.magnitude for o in outcomes] == [4.8, 5.8, 6.8, 7.8]
    counts = [o.observed_count for o in outcomes]
    assert counts == sorted(counts, reverse=True)
    # the mainshock itself is inside the window, so the top rung did occur
    assert outcomes[-1].observed_count >= 1
    assert outcomes[-1].occurred is True
    # a lambda of 0.001 against an observed event is not consistent with Poisson
    assert outcomes[-1].consistent is False
    assert outcomes[-1].poisson_p_at_least_observed < 0.01


def test_score_thresholds_with_nothing_observed() -> None:
    empty = Catalog(id="e", events=(), built_at=utc_now(), builder_version="t")
    (outcome,) = score_thresholds(_forecast(((4.8, 0.5),)), empty)
    assert outcome.observed_count == 0
    assert outcome.occurred is False
    assert outcome.poisson_p_at_least_observed == 1.0
    assert outcome.poisson_p_at_most_observed == pytest.approx(math.exp(-0.5))
    assert outcome.consistent is True


def test_score_thresholds_flags_a_gross_over_forecast() -> None:
    empty = Catalog(id="e", events=(), built_at=utc_now(), builder_version="t")
    (outcome,) = score_thresholds(_forecast(((4.8, 20.0),)), empty)
    assert outcome.poisson_p_at_most_observed < 1e-8
    assert outcome.consistent is False


def test_observed_in_window_uses_the_lattice(
    fast_forecaster: AftershockForecaster,
    gorkha: SequenceSpec,
    gorkha_catalog: Catalog,
    nepal_region: Region,
) -> None:
    """Only earthquakes inside a cell of the grid, in the half-open window, are targets."""
    zone = fast_forecaster.zone(gorkha.mainshock, nepal_region)
    start = MAINSHOCK_TIME
    end = start + timedelta(days=7)
    grid = _bare_grid(zone, start, end)
    target = observed_in_window(gorkha_catalog, zone, grid, start, end)
    assert 0 < len(target) < len(gorkha_catalog)
    assert all(start <= e.origin_time < end for e in target.events)
    assert all(e.event_type.value == "earthquake" for e in target.events)
    # nothing deeper than the region allows
    assert all(
        e.depth_km is None or zone.depth_min_km <= e.depth_km <= zone.depth_max_km
        for e in target.events
    )
    # an empty window gives an empty slice, not an error
    quiet_start = datetime(2010, 1, 1, tzinfo=UTC)
    quiet = observed_in_window(
        gorkha_catalog.model_copy(update={"events": ()}),
        zone,
        grid,
        quiet_start,
        quiet_start + timedelta(days=1),
    )
    assert len(quiet) == 0


def _bare_grid(region: Region, start: datetime, end: datetime) -> ForecastGrid:
    lattice = build_lattice(region)
    edges = region.magnitude_bin_edges()
    row = tuple(0.0 for _ in edges)
    return ForecastGrid(
        id="bare",
        region_id=region.id,
        model_id="m",
        model_version="v",
        parameter_snapshot_hash=snapshot_hash({}),
        fit_cutoff=start,
        training_catalog_hash="h",
        issue_time=start,
        horizon=end - start,
        cell_size_deg=region.cell_size_deg,
        cell_origins=lattice.origins,
        magnitude_bin_edges=edges,
        magnitude_bin_width=region.magnitude_bin_width,
        expected_counts=tuple(row for _ in lattice.origins),
        created_at=start,
    )


def _outcome() -> SequenceOutcome:
    window = WindowOutcome(
        sequence_id="gorkha",
        issue_label="1d",
        issue_time=MAINSHOCK_TIME.isoformat(),
        horizon="7d",
        window_end=(MAINSHOCK_TIME + timedelta(days=7)).isoformat(),
        elapsed="1d",
        forecast_id="f",
        forecast_grid_id="g",
        fit_cutoff=MAINSHOCK_TIME.isoformat(),
        n_training_events=123,
        n_sequence_events=40,
        branching_ratio=0.646,
        b_value=1.138,
        b_value_fixed=True,
        total_expected_above_target=2.9,
        n_observed_above_target=15,
        thresholds=score_thresholds(
            _forecast(((4.8, 2.6), (5.8, 0.2))),
            Catalog(id="e", events=(), built_at=utc_now(), builder_version="t"),
        ),
        csep=[
            CsepOutcome(
                test="N",
                statistic=15.0,
                quantile=None,
                quantile_low=1.0,
                quantile_high=0.0,
                passed=False,
                n_target_events=15,
            ),
            CsepOutcome(
                test="M",
                statistic=-14.3,
                quantile=0.44,
                quantile_low=None,
                quantile_high=None,
                passed=True,
                n_target_events=15,
            ),
        ],
    )
    return SequenceOutcome(
        sequence_id="gorkha",
        description="2015 Gorkha",
        mainshock_event_id="us20002926",
        mainshock_time=MAINSHOCK_TIME.isoformat(),
        mainshock_magnitude=7.8,
        region_id="aftershock-us20002926",
        zone_radius_km=217.8,
        n_cells=1366,
        mc=4.4,
        target_min_magnitude=4.7,
        catalog_coverage_end="2015-06-10T00:00:00+00:00",
        n_catalog_events=565,
        windows=[window],
        skipped=["a window that did not close"],
        evaluated_at=utc_now().isoformat(),
    )


def test_render_markdown_names_the_poisson_assumption_and_the_numbers() -> None:
    text = render_markdown(_outcome())
    assert "1 - exp(-lambda)" in text
    assert "us20002926" in text
    assert "| N |" in text
    assert "a window that did not close" in text
    assert "217.8" in text or "218" in text


def test_write_report_writes_both_files(tmp_path) -> None:
    json_path, md_path = write_report(_outcome(), tmp_path / "reports")
    assert json_path.name == "gorkha.json"
    assert md_path.name == "gorkha.md"
    assert '"sequence_id": "gorkha"' in json_path.read_text(encoding="utf-8")
    assert md_path.read_text(encoding="utf-8").startswith("# Aftershock forecast validation")
