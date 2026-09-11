"""The trivial alarm: declare near whatever just broke.

Luen & Stark (2008, `widely-used`) scored a rule of this shape — alarm for a fixed period in a
fixed radius after every M >= 5.5 — and reached p < 0.001 against a Poisson null on clustering
alone, without any precursor, any physics or any parameter worth fitting. It is in this repository
for exactly that reason. It is the thing an alarm scorer has to be able to expose, and any
reference measure that this rule beats is a reference measure that will hand a spurious result to
the next model that walks in.

The rule is graded rather than binary so that it traces a whole Molchan trajectory, but it carries
a declared operating point whose meaning is fixed in advance and does not depend on the targets:
``declared_threshold = 0.5`` is exactly "within ``radius_km`` of one trigger of the minimum
trigger magnitude", because the spatial kernel is ``1 / (1 + (d / radius_km) ** 2)``.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

import numpy as np
import numpy.typing as npt

from rupture.domain.alarm import AlarmSet
from rupture.domain.catalog import Catalog
from rupture.domain.common import utc_now
from rupture.domain.forecast import snapshot_hash

RECENT_LARGE_MODEL_ID = "recent-large-alarm"
MODEL_VERSION = "1.0.0"
DECLARED_THRESHOLD = 0.5
_KM_PER_DEG = 111.19492664455873


@dataclass(frozen=True, slots=True)
class RecentLargeParameters:
    """Every number the rule uses. Frozen before the window, hashed into the alarm set."""

    trigger_magnitude: float = 5.5
    lookback_days: float = 30.0
    radius_km: float = 50.0
    magnitude_scaling: float = 0.5
    """Weight of a trigger is ``10 ** (scaling * (mw - trigger_magnitude))``: a bigger event
    reaches further, in the same way the Utsu-Seki aftershock area does."""

    def as_dict(self) -> dict[str, float]:
        return {k: float(v) for k, v in asdict(self).items()}


def _distances_km(
    cell_lon: npt.NDArray[np.float64],
    cell_lat: npt.NDArray[np.float64],
    lon: float,
    lat: float,
) -> npt.NDArray[np.float64]:
    """Equirectangular distance, which is accurate enough over an alarm radius."""
    dx = (cell_lon - lon) * math.cos(math.radians(lat)) * _KM_PER_DEG
    dy = (cell_lat - lat) * _KM_PER_DEG
    return np.asarray(np.hypot(dx, dy), dtype=np.float64)


def recent_large_alarm(
    catalog: Catalog,
    *,
    region_id: str,
    cell_origins: tuple[tuple[float, float], ...],
    cell_size_deg: float,
    issue_time: datetime,
    horizon: timedelta,
    target_min_magnitude: float,
    parameters: RecentLargeParameters | None = None,
    declared_threshold: float | None = DECLARED_THRESHOLD,
) -> AlarmSet:
    """Build the alarm for one window from the events strictly before ``issue_time``.

    The catalogue is cut at ``issue_time`` here rather than by the caller, so the rule cannot see
    its own target window even if it is handed the full catalogue.
    """
    params = parameters or RecentLargeParameters()
    history = catalog.before(issue_time)
    start = issue_time - timedelta(days=params.lookback_days)
    triggers: list[tuple[float, float, float]] = [
        (e.mw, e.longitude, e.latitude)
        for e in history.earthquakes().events
        if e.mw is not None and e.mw >= params.trigger_magnitude and e.origin_time >= start
    ]
    half = cell_size_deg / 2.0
    cell_lon = np.asarray([lon + half for lon, _ in cell_origins], dtype=np.float64)
    cell_lat = np.asarray([lat + half for _, lat in cell_origins], dtype=np.float64)
    values = np.zeros(len(cell_origins), dtype=np.float64)
    for mw, lon, lat in triggers:
        weight = 10.0 ** (params.magnitude_scaling * (mw - params.trigger_magnitude))
        d = _distances_km(cell_lon, cell_lat, lon, lat)
        values = np.maximum(values, weight / (1.0 + (d / params.radius_km) ** 2))

    return AlarmSet(
        id=AlarmSet.make_id(RECENT_LARGE_MODEL_ID, region_id, issue_time, horizon),
        region_id=region_id,
        model_id=RECENT_LARGE_MODEL_ID,
        model_version=MODEL_VERSION,
        issue_time=issue_time,
        horizon=horizon,
        target_min_magnitude=target_min_magnitude,
        cell_size_deg=cell_size_deg,
        cell_origins=cell_origins,
        alarm_values=tuple(float(v) for v in values),
        declared_threshold=declared_threshold,
        binary=False,
        fit_cutoff=issue_time,
        training_catalog_hash=history.event_hash(),
        parameter_snapshot_hash=snapshot_hash(params.as_dict()),
        created_at=utc_now(),
        notes=(
            f"{len(triggers)} trigger(s) at or above M{params.trigger_magnitude} in the "
            f"{params.lookback_days:g} days before issue; kernel 1/(1+(d/{params.radius_km:g}km)^2)"
        ),
    )
