"""Pipeline: issue one ``ForecastGrid`` at ``issue_time`` from a loaded fit; store and log it."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.adapters.forecasting.leakage import assert_all_before
from rupture.domain import Catalog, ForecastGrid, utc_now
from rupture.ports import GridStore, RunRecord, Tracker


def history_for(catalog: Catalog, issue_time: datetime, mc: float) -> Catalog:
    """Everything a model may see at ``issue_time``: earthquakes, ``mw >= mc``, strictly before."""
    history = catalog.earthquakes().before(issue_time).at_least(mc)
    assert_all_before(history, issue_time, what="forecast history")
    return history


def issue_forecast(
    model: MizrahiETAS,
    catalog: Catalog,
    issue_time: datetime,
    horizon: timedelta,
    *,
    n_simulations: int = 100,
    seed: int | None = None,
    store: GridStore | None = None,
    tracker: Tracker | None = None,
) -> ForecastGrid:
    fit = model.fit_result
    if fit is None:
        msg = "model has no fit loaded"
        raise RuntimeError(msg)
    history = history_for(catalog, issue_time, fit.mc)
    grid = model.forecast(history, issue_time, horizon, n_simulations=n_simulations, seed=seed)
    locator = store.save(grid) if store is not None else None
    if tracker is not None:
        tracker.log(
            RunRecord(
                run_id=f"issue-{grid.id}-{uuid.uuid4().hex[:8]}",
                kind="issue",
                at=utc_now(),
                region_id=grid.region_id,
                model_id=grid.model_id,
                parameter_snapshot_hash=grid.parameter_snapshot_hash,
                inputs={
                    "catalog_id": catalog.id,
                    "issue_time": issue_time.isoformat(),
                    "horizon_seconds": int(horizon.total_seconds()),
                    "history_events": len(history),
                    "history_hash": history.event_hash(),
                    "fit_cutoff": fit.fit_cutoff.isoformat(),
                    "n_simulations": n_simulations,
                    "seed": seed,
                },
                outputs={
                    "forecast_id": grid.id,
                    "total_expected": grid.total_expected(),
                    "locator": locator,
                },
            )
        )
    return grid
