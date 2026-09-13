"""Alarm-set helper for a fitted occupancy logistic.

The comparator is scored on the AlarmSet arm (Molchan / area skill / probability gain G) — the
metrics this repository actually allows. Given a fitted logistic and a declared alarm fraction
``tau``, this emits an :class:`~rupture.domain.alarm.AlarmSet` of the highest-P cells whose
reference mass equals ``tau``.

The reference must be clustering-aware. A spatially uniform Poisson reference is refused
(:class:`~rupture.scoring.errors.UniformReferenceRefusedError`); covering a fraction of *area*
credits an alarm for knowing that earthquakes happen on faults (Zhang et al. 2024; Luen & Stark
2008).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import numpy.typing as npt

from rupture.domain.alarm import AlarmSet, ReferenceKind
from rupture.domain.catalog import Catalog
from rupture.domain.common import utc_now
from rupture.models.comparators.logistic import OneNeuronAftershockModel
from rupture.scoring.errors import MissingReferenceError, UniformReferenceRefusedError
from rupture.scoring.reference import ReferenceMeasure


def alarm_from_logistic(
    model: OneNeuronAftershockModel,
    history: Catalog,
    *,
    tau: float,
    reference: ReferenceMeasure,
    issue_time: datetime,
    horizon: timedelta,
    target_min_magnitude: float,
) -> AlarmSet:
    """Highest-P cells whose clustering-aware reference mass first reaches ``tau``.

    Alarm values are the occupancy probabilities (graded, so the scorer can trace a Molchan
    trajectory). ``declared_threshold`` is the operating point whose reference mass is ``tau``,
    committed before the targets are seen.
    """
    if not 0.0 < tau <= 1.0:
        msg = f"alarm fraction tau must be in (0, 1], got {tau!r}"
        raise ValueError(msg)
    fit = model.fit_result
    if fit is None:
        msg = f"{model.model_id} has not been fitted"
        raise ValueError(msg)
    _refuse_uniform(reference)
    if reference.kind is not ReferenceKind.CLUSTERING_AWARE:
        msg = (
            f"reference {reference.id!r} is {reference.kind.value}, not clustering-aware. "
            "The one-neuron AlarmSet arm takes a clustering-aware reference (fitted ETAS, or "
            "another model that carries the clustering). A spatially varying Poisson may be "
            "reported as a labelled contrast, not as the reference of record."
        )
        raise MissingReferenceError(msg)
    probability = model.occupancy_map(history, issue_time)
    lattice_origins = model.cell_origins
    if reference.cell_origins != lattice_origins:
        msg = (
            f"reference {reference.id!r} is defined on different cells from the fitted "
            f"logistic ({reference.n_cells} vs {len(lattice_origins)}); they must share a lattice"
        )
        raise MissingReferenceError(msg)
    threshold = _threshold_for_tau(probability, reference.probabilities, tau)
    return AlarmSet(
        id=AlarmSet.make_id(model.model_id, fit.region_id, issue_time, horizon),
        region_id=fit.region_id,
        model_id=model.model_id,
        model_version=model.model_version,
        issue_time=issue_time,
        horizon=horizon,
        target_min_magnitude=target_min_magnitude,
        cell_size_deg=reference.cell_size_deg,
        cell_origins=lattice_origins,
        alarm_values=tuple(float(v) for v in probability),
        declared_threshold=threshold,
        binary=False,
        fit_cutoff=fit.fit_cutoff,
        training_catalog_hash=fit.training_catalog_hash,
        parameter_snapshot_hash=fit.parameter_snapshot_hash,
        created_at=utc_now(),
        notes=(
            f"highest-P cells whose {reference.kind.value} reference mass is tau={tau:g}; "
            f"declared_threshold={threshold:.6g}. Score with area skill / Molchan, not AUC."
        ),
    )


def _refuse_uniform(reference: ReferenceMeasure) -> None:
    if reference.kind is ReferenceKind.SPATIALLY_UNIFORM:
        msg = (
            f"reference {reference.id!r} is spatially uniform. An alarm scored against area is "
            "credited for knowing that earthquakes happen on faults (Zhang et al. 2024; Luen & "
            "Stark 2008). Supply a clustering-aware reference."
        )
        raise UniformReferenceRefusedError(msg)


def _threshold_for_tau(
    probability: npt.NDArray[np.float64],
    reference_mass: npt.NDArray[np.float64],
    tau: float,
) -> float:
    """Smallest P such that cells with occupancy >= P cover at least ``tau`` of the reference."""
    order = np.argsort(-probability, kind="stable")
    values = probability[order]
    mass = reference_mass[order]
    _, starts = np.unique(-values, return_index=True)
    starts = np.sort(starts)
    ends = np.append(starts[1:], values.size)
    cumulative = 0.0
    threshold = float(values[-1])
    for start, end in zip(starts.tolist(), ends.tolist(), strict=True):
        cumulative += float(mass[start:end].sum())
        threshold = float(values[start])
        if cumulative + 1e-15 >= tau:
            return threshold
    return threshold
