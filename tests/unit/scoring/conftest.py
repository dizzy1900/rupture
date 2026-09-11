"""A small synthetic region, alarm and catalogue: enough to exercise every refusal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.domain import (
    Catalog,
    Event,
    EventType,
    FitResult,
    MagnitudeRecord,
    MagnitudeType,
    Provenance,
)
from rupture.domain.alarm import AlarmSet, ReferenceKind
from rupture.domain.forecast import snapshot_hash
from rupture.scoring.reference import ReferenceMeasure
from tests.fixtures.forecasting.loader import (
    FIXTURE_DIR,
    fixture_region,
    load_fixture_catalog,
)

ISSUE = datetime(2020, 1, 1, tzinfo=UTC)
HORIZON = timedelta(days=30)
CELL = 0.1
GRID_SIDE = 10
TARGET_MW = 4.0


@pytest.fixture(scope="session")
def cell_origins() -> tuple[tuple[float, float], ...]:
    return tuple(
        (round(-120.0 + i * CELL, 6), round(35.0 + j * CELL, 6))
        for j in range(GRID_SIDE)
        for i in range(GRID_SIDE)
    )


@pytest.fixture(scope="session")
def scoring_provenance() -> Provenance:
    return Provenance(source="test", retrieved_at=ISSUE, adapter_version="0.0.0", licence="none")


def make_catalog(
    provenance: Provenance,
    cells: list[tuple[float, float]],
    *,
    inside_window: bool = True,
    mw: float = 5.0,
) -> Catalog:
    """One event at the centre of each named cell, inside or outside the alarm window."""
    when = ISSUE + timedelta(days=1) if inside_window else ISSUE - timedelta(days=1)
    events = tuple(
        Event(
            id=f"e{k}",
            origin_time=when + timedelta(minutes=k),
            latitude=lat + CELL / 2,
            longitude=lon + CELL / 2,
            depth_km=8.0,
            magnitude=MagnitudeRecord(value=mw, type=MagnitudeType.MWW, agency="t"),
            mw=mw,
            mw_conversion="identity:mww",
            event_type=EventType.EARTHQUAKE,
            source_catalog="test",
            source_event_id=f"e{k}",
            provenance=provenance,
        )
        for k, (lon, lat) in enumerate(cells)
    )
    return Catalog(
        id="scoring-fixture",
        region_id="synthetic",
        events=events,
        built_at=ISSUE,
        builder_version="tests",
    )


def make_alarm(
    cell_origins: tuple[tuple[float, float], ...],
    values: np.ndarray,
    *,
    declared_threshold: float | None = 0.5,
    issue_time: datetime = ISSUE,
    fit_cutoff: datetime | None = None,
    model_id: str = "test-alarm",
) -> AlarmSet:
    return AlarmSet(
        id=f"{model_id}-{issue_time:%Y%m%d}",
        region_id="synthetic",
        model_id=model_id,
        model_version="1.0.0",
        issue_time=issue_time,
        horizon=HORIZON,
        target_min_magnitude=TARGET_MW,
        cell_size_deg=CELL,
        cell_origins=cell_origins,
        alarm_values=tuple(float(v) for v in values),
        declared_threshold=declared_threshold,
        fit_cutoff=fit_cutoff or issue_time,
        training_catalog_hash="0" * 64,
        parameter_snapshot_hash=snapshot_hash({"a": 1.0}),
        created_at=issue_time,
    )


def make_reference(
    cell_origins: tuple[tuple[float, float], ...],
    weights: np.ndarray,
    *,
    kind: ReferenceKind = ReferenceKind.CLUSTERING_AWARE,
    expected_events: float | None = 10.0,
    fit_cutoff_iso: str | None = None,
) -> ReferenceMeasure:
    w = np.asarray(weights, dtype=np.float64)
    return ReferenceMeasure(
        id="ref-test",
        kind=kind,
        model_id="test-reference",
        cell_size_deg=CELL,
        cell_origins=cell_origins,
        probabilities=w / w.sum(),
        expected_events=expected_events,
        fit_cutoff_iso=fit_cutoff_iso,
    )


@pytest.fixture(scope="session")
def ridgecrest_grid() -> object:
    """A real 30-day ETAS issuance on the committed California fixture, for the adapter tests."""
    cutoff = datetime(2019, 7, 1, tzinfo=UTC)
    fit = FitResult.model_validate_json(
        (FIXTURE_DIR / "fit-2019-07-01" / "fit_result.json").read_text(encoding="utf-8")
    )
    region = fixture_region()
    model = MizrahiETAS(auxiliary_years=0.5)
    model.load_fit(fit, region)
    catalog = load_fixture_catalog()
    history = catalog.earthquakes().before(cutoff).at_least(fit.mc)
    return model.forecast(history, cutoff, timedelta(days=30), n_simulations=5, seed=3)
