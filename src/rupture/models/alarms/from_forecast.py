"""Any fitted rate forecast, reinterpreted as a graded alarm function.

Not a way of turning a rate forecast into a different kind of claim — it is still the same
forecast — but the way to put a rate model and an alarm on the same axes.

Scoring a forecast as an alarm against *itself* is the scorer's calibration check, and it is worth
being precise about what it does and does not assert. The area skill score comes out at one half
plus sampling noise when the target events are drawn from the reference; that is the identity the
unit tests check, with simulated targets. On *real* targets it is not one half and is not supposed
to be — it measures how well the model's own allocation of its expected events matches where they
actually fell, in space and across windows together. A model that puts its mass in the wrong month
scores badly against itself, which is information rather than a defect in the scorer.
"""

from __future__ import annotations

import numpy as np

from rupture.domain.alarm import AlarmSet
from rupture.domain.common import utc_now
from rupture.domain.forecast import ForecastGrid
from rupture.scoring.errors import MissingReferenceError


def alarm_from_forecast_grid(
    grid: ForecastGrid,
    *,
    target_min_magnitude: float,
    declared_threshold: float | None = None,
    model_id_suffix: str = "-as-alarm",
) -> AlarmSet:
    """Sum the grid's expected counts above ``target_min_magnitude`` into an alarm function."""
    edges = np.asarray(grid.magnitude_bin_edges, dtype=np.float64)
    keep = edges >= target_min_magnitude - 1e-9
    if not keep.any():
        msg = (
            f"forecast {grid.id!r} has no magnitude bin at or above {target_min_magnitude}; it "
            "cannot be read as an alarm for that magnitude"
        )
        raise MissingReferenceError(msg)
    values = grid.counts()[:, keep].sum(axis=1)
    model_id = f"{grid.model_id}{model_id_suffix}"
    return AlarmSet(
        id=AlarmSet.make_id(model_id, grid.region_id, grid.issue_time, grid.horizon),
        region_id=grid.region_id,
        model_id=model_id,
        model_version=grid.model_version,
        issue_time=grid.issue_time,
        horizon=grid.horizon,
        target_min_magnitude=target_min_magnitude,
        cell_size_deg=grid.cell_size_deg,
        cell_origins=grid.cell_origins,
        alarm_values=tuple(float(v) for v in values),
        declared_threshold=declared_threshold,
        binary=False,
        fit_cutoff=grid.fit_cutoff,
        training_catalog_hash=grid.training_catalog_hash,
        parameter_snapshot_hash=grid.parameter_snapshot_hash,
        created_at=utc_now(),
        notes=f"expected counts of {grid.id} summed over magnitude bins >= {target_min_magnitude}",
    )
