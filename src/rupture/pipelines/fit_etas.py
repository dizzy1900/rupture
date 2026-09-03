"""Pipeline: fit the ETAS baseline up to a hard cutoff and persist it under ``baselines/``."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS, save_fit
from rupture.domain import Catalog, FitResult, Region, utc_now
from rupture.ports import RunRecord, Tracker


def fit_etas(
    catalog: Catalog,
    region: Region,
    cutoff: datetime,
    *,
    baselines_dir: Path,
    mc: float | None = None,
    model: MizrahiETAS | None = None,
    tracker: Tracker | None = None,
    kind: str = "fit",
) -> FitResult:
    """Fit on ``origin_time < cutoff``, write ``baselines/etas/<region>/`` and log the run.

    ``kind`` is ``"fit"`` for the first fit of a schedule and ``"refit"`` at declared boundaries;
    the run log entry carries the new ``parameter_snapshot_hash`` and the training hash either way.
    """
    model = model or MizrahiETAS()
    result = model.fit(catalog, region, cutoff, mc=mc)
    out = save_fit(result, baselines_dir)
    if tracker is not None:
        tracker.log(
            RunRecord(
                run_id=f"{kind}-{region.id}-{cutoff:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}",
                kind=kind,
                at=utc_now(),
                region_id=region.id,
                model_id=model.model_id,
                parameter_snapshot_hash=result.parameter_snapshot_hash,
                inputs={
                    "catalog_id": catalog.id,
                    "cutoff": cutoff.isoformat(),
                    "mc": result.mc,
                    "training_catalog_hash": result.training_catalog_hash,
                    "n_events": result.n_events,
                },
                outputs={
                    "fit_dir": str(out),
                    "converged": result.converged,
                    "iterations": result.diagnostics.get("iterations"),
                    "branching_ratio": result.diagnostics.get("branching_ratio"),
                },
            )
        )
    return result
