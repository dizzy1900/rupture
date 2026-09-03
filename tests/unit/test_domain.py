"""Domain invariants the rest of the system leans on."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rupture.domain import (
    Catalog,
    EventType,
    FitResult,
    ForecastGrid,
    Provenance,
    Region,
    TectonicSetting,
    format_horizon,
    parse_horizon,
    snapshot_hash,
)
from tests.unit.conftest import make_event

CUTOFF = datetime(2022, 1, 1, tzinfo=UTC)


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Provenance(source="x", retrieved_at=datetime(2026, 1, 1), adapter_version="0")  # noqa: DTZ001


def test_before_is_strict_and_between_is_half_open(catalog: Catalog) -> None:
    train = catalog.before(CUTOFF)
    assert [e.id for e in train.events] == ["e0"], "only events strictly before the cutoff"
    target = catalog.between(CUTOFF, CUTOFF + timedelta(days=30))
    assert {e.id for e in target.events} == {"e1", "e2", "ls"}
    latest = train.max_origin_time()
    assert latest is not None
    assert latest < CUTOFF
    assert target.min_origin_time() == CUTOFF


def test_landslides_are_retained_but_filterable(catalog: Catalog) -> None:
    assert catalog.count_by_type()[EventType.LANDSLIDE] == 1
    assert len(catalog.earthquakes()) == 3
    assert len(catalog.at_least(4.5)) == 3, "events without Mw are excluded by magnitude filters"


def test_event_hash_identifies_the_slice(catalog: Catalog) -> None:
    assert catalog.event_hash() != catalog.before(CUTOFF).event_hash()
    assert catalog.event_hash() == catalog.model_copy(update={"notes": "x"}).event_hash()


def test_mw_and_conversion_travel_together(provenance: Provenance) -> None:
    good = make_event(provenance, eid="ok", when=CUTOFF, mw=5.0)
    with pytest.raises(ValueError, match="mw_conversion"):
        good.model_copy(update={"mw_conversion": None}).model_validate(
            good.model_dump() | {"mw_conversion": None}
        )


def test_horizon_round_trip() -> None:
    assert parse_horizon("30d") == timedelta(days=30)
    assert parse_horizon("12h") == timedelta(hours=12)
    assert format_horizon(parse_horizon("1w")) == "7d"
    with pytest.raises(ValueError, match="horizon"):
        parse_horizon("30 days")


def _grid(counts: tuple[tuple[float, ...], ...]) -> ForecastGrid:
    return ForecastGrid(
        id="g",
        region_id="r",
        model_id="etas",
        model_version="0",
        parameter_snapshot_hash="h",
        fit_cutoff=CUTOFF,
        training_catalog_hash="t",
        issue_time=CUTOFF,
        horizon=timedelta(days=30),
        cell_size_deg=0.1,
        cell_origins=((85.0, 28.0), (85.1, 28.0)),
        magnitude_bin_edges=(4.5, 4.6),
        magnitude_bin_width=0.1,
        expected_counts=counts,
        created_at=CUTOFF,
    )


def test_forecast_grid_rejects_bad_shapes_and_values() -> None:
    good = _grid(((0.1, 0.05), (0.2, 0.0)))
    assert good.total_expected() == pytest.approx(0.35)
    assert good.window_end == CUTOFF + timedelta(days=30)
    with pytest.raises(ValueError, match="one row per cell"):
        _grid(((0.1, 0.05),))
    with pytest.raises(ValueError, match="finite and non-negative"):
        _grid(((0.1, -0.05), (0.2, 0.0)))
    with pytest.raises(ValueError, match="finite and non-negative"):
        _grid(((float("nan"), 0.05), (0.2, 0.0)))


def test_fit_result_hash_must_match_parameters() -> None:
    params = {"mu": 0.1, "alpha": 1.5}
    kwargs = {
        "model_id": "etas",
        "model_version": "0",
        "region_id": "r",
        "fit_cutoff": CUTOFF,
        "training_start": CUTOFF - timedelta(days=3650),
        "training_catalog_hash": "t",
        "n_events": 10,
        "mc": 4.5,
        "parameters": params,
        "fitted_at": CUTOFF,
    }
    FitResult(parameter_snapshot_hash=snapshot_hash(params), **kwargs)
    with pytest.raises(ValueError, match="parameter_snapshot_hash"):
        FitResult(parameter_snapshot_hash="stale", **kwargs)


def test_region_bins_and_geojson() -> None:
    region = Region(
        id="nepal-himalaya",
        name="Nepal Himalaya",
        polygon=((80.0, 26.5), (89.0, 26.5), (89.0, 30.5), (80.0, 30.5)),
        depth_max_km=70.0,
        tectonic_setting=TectonicSetting.CONTINENTAL_COLLISION,
        target_min_magnitude=4.5,
    )
    edges = region.magnitude_bin_edges()
    assert edges[0] == 4.5
    assert edges[-1] == pytest.approx(8.9, abs=1e-6)
    assert region.to_geojson()["geometry"]["coordinates"][0][-1] == [80.0, 26.5]
    assert region.bbox() == (80.0, 26.5, 89.0, 30.5)
