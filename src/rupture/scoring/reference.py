"""The measure an alarm's skill is measured *against*.

A Molchan diagram's horizontal axis is not area. It is the fraction of the reference measure the
alarm covers, and the choice of that measure decides the answer: cover 1 % of California's area
with an alarm and you have covered far more than 1 % of its expected earthquakes. Scoring against
area — equivalently, against a spatially uniform Poisson reference — credits an alarm for knowing
that earthquakes happen on faults, which is not a prediction.

A reference here is a normalised probability over the same cells the alarm uses: the chance that
a target event, given one occurs in the window, lands in cell *i*. Three kinds exist and they are
not interchangeable; :class:`~rupture.domain.alarm.ReferenceKind` carries which one a score used,
and the scorer refuses to publish a uniform one as the reference of record.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from rupture.domain.alarm import ReferenceKind
from rupture.domain.forecast import ForecastGrid
from rupture.scoring.errors import MissingReferenceError

_EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True, slots=True)
class ReferenceMeasure:
    """Where the reference model expects the window's events to fall, cell by cell.

    ``probabilities`` sums to one over ``cell_origins``, in that order. ``model_id`` is the model
    that produced it, so a score can never be read without knowing what it beat.
    """

    id: str
    kind: ReferenceKind
    model_id: str
    cell_size_deg: float
    cell_origins: tuple[tuple[float, float], ...]
    probabilities: npt.NDArray[np.float64]
    expected_events: float | None = None
    """Expected target events in this window, before normalisation. Needed to pool windows:
    a window in which the reference expects ten events must weigh ten times one in which it
    expects one, or a quiet month counts as much as an aftershock sequence."""
    source_forecast_id: str | None = None
    fit_cutoff_iso: str | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.probabilities.shape != (len(self.cell_origins),):
            msg = "reference probabilities must have one value per cell"
            raise ValueError(msg)
        if not np.all(np.isfinite(self.probabilities)) or np.any(self.probabilities < 0.0):
            msg = "reference probabilities must be finite and non-negative"
            raise ValueError(msg)
        total = float(self.probabilities.sum())
        if not math.isclose(total, 1.0, rel_tol=1e-9, abs_tol=1e-12):
            msg = f"reference probabilities must sum to 1, got {total!r}"
            raise ValueError(msg)

    @property
    def n_cells(self) -> int:
        return len(self.cell_origins)


def _normalise(weights: npt.NDArray[np.float64], what: str) -> npt.NDArray[np.float64]:
    total = float(weights.sum())
    if not math.isfinite(total) or total <= 0.0:
        msg = f"{what} carries no mass, so it cannot be a reference measure"
        raise MissingReferenceError(msg)
    return weights / total


def from_forecast_grid(
    grid: ForecastGrid,
    *,
    kind: ReferenceKind = ReferenceKind.CLUSTERING_AWARE,
    min_magnitude: float | None = None,
    reference_id: str | None = None,
) -> ReferenceMeasure:
    """The spatial marginal of a fitted rate forecast, above ``min_magnitude``.

    ETAS is the reference of record for the alarm arm (ADR-0059), and this is how a fitted ETAS
    forecast becomes one: sum expected counts over the magnitude bins at or above the alarm's
    target magnitude, then normalise. The magnitude filter matters — an alarm for M >= 5 scored
    against the spatial pattern of M >= 3 rates is scored against the wrong reference, because
    small events are more numerous where the network is denser.
    """
    counts = grid.counts()
    if min_magnitude is None:
        weights = counts.sum(axis=1)
    else:
        edges = np.asarray(grid.magnitude_bin_edges, dtype=np.float64)
        keep = edges >= min_magnitude - 1e-9
        if not keep.any():
            msg = (
                f"forecast {grid.id!r} has no magnitude bin at or above {min_magnitude}; it "
                "cannot supply the reference for that alarm"
            )
            raise MissingReferenceError(msg)
        weights = counts[:, keep].sum(axis=1)
    return ReferenceMeasure(
        id=reference_id or f"ref-{grid.id}",
        kind=kind,
        model_id=grid.model_id,
        cell_size_deg=grid.cell_size_deg,
        cell_origins=grid.cell_origins,
        probabilities=_normalise(weights, f"forecast {grid.id!r}"),
        expected_events=float(weights.sum()),
        source_forecast_id=grid.id,
        fit_cutoff_iso=grid.fit_cutoff.isoformat(),
        notes=(
            f"spatial marginal of {grid.model_id} over magnitude bins >= "
            f"{min_magnitude if min_magnitude is not None else grid.magnitude_bin_edges[0]}",
        ),
    )


def cell_areas_km2(
    cell_origins: tuple[tuple[float, float], ...], cell_size_deg: float
) -> npt.NDArray[np.float64]:
    """Spherical area of each square-in-degrees cell: it falls off as cos(latitude)."""
    lats = np.asarray([lat for _, lat in cell_origins], dtype=np.float64)
    lat0 = np.radians(lats)
    lat1 = np.radians(lats + cell_size_deg)
    dlon = np.radians(cell_size_deg)
    areas = (_EARTH_RADIUS_KM**2) * dlon * np.abs(np.sin(lat1) - np.sin(lat0))
    return np.asarray(areas, dtype=np.float64)


def uniform(
    cell_origins: tuple[tuple[float, float], ...],
    cell_size_deg: float,
    *,
    expected_events: float | None = None,
    reference_id: str = "ref-uniform",
) -> ReferenceMeasure:
    """Area-weighted uniform over the region: the reference that manufactures alarm skill.

    Built only so that the size of that effect can be measured and reported alongside the real
    score. The scorer will not accept it as the reference of record; see
    :class:`~rupture.scoring.errors.UniformReferenceRefusedError`. It is area-weighted rather than
    cell-weighted because a degree square near the pole is smaller than one at the equator, and a
    contrast that got that wrong would understate its own point.
    """
    areas = cell_areas_km2(cell_origins, cell_size_deg)
    return ReferenceMeasure(
        id=reference_id,
        kind=ReferenceKind.SPATIALLY_UNIFORM,
        model_id="uniform-area",
        cell_size_deg=cell_size_deg,
        cell_origins=cell_origins,
        probabilities=_normalise(areas, "the region"),
        expected_events=expected_events,
        notes=("area-weighted uniform; a contrast, never the reference of record",),
    )


def smoothed_seismicity(
    cell_origins: tuple[tuple[float, float], ...],
    cell_size_deg: float,
    counts_per_cell: npt.NDArray[np.float64],
    *,
    smoothing_cells: float = 1.0,
    floor: float = 1e-6,
    model_id: str = "smoothed-seismicity",
    reference_id: str = "ref-smoothed-seismicity",
) -> ReferenceMeasure:
    """A spatially varying Poisson reference: past counts, isotropically smoothed, with a floor.

    This is the reference Zhang et al. (2024) swapped in for a uniform one, and it is the weakest
    reference this module will accept as the reference of record. It varies in space and carries
    no time clustering, so an alarm that beats it may still be reproducing Omori decay rather than
    predicting anything; that is what the ETAS reference is for. ``floor`` keeps a cell that has
    never had an event from making the score infinite, and is reported.
    """
    if counts_per_cell.shape != (len(cell_origins),):
        msg = "counts_per_cell must have one value per cell"
        raise ValueError(msg)
    lons = np.asarray([lon for lon, _ in cell_origins], dtype=np.float64)
    lats = np.asarray([lat for _, lat in cell_origins], dtype=np.float64)
    sigma = max(smoothing_cells, 1e-9) * cell_size_deg
    mean_lat = float(np.radians(lats.mean()))
    dx = (lons[None, :] - lons[:, None]) * math.cos(mean_lat)
    dy = lats[None, :] - lats[:, None]
    kernel = np.exp(-0.5 * (dx**2 + dy**2) / sigma**2)
    smoothed = kernel @ np.asarray(counts_per_cell, dtype=np.float64)
    smoothed = smoothed + floor * max(float(smoothed.max()), 1.0)
    return ReferenceMeasure(
        id=reference_id,
        kind=ReferenceKind.SPATIALLY_VARYING_POISSON,
        model_id=model_id,
        cell_size_deg=cell_size_deg,
        cell_origins=tuple(cell_origins),
        probabilities=_normalise(smoothed, "the smoothed catalogue"),
        notes=(
            f"isotropic Gaussian smoothing, sigma = {smoothing_cells} cells; "
            f"floor = {floor} of the maximum smoothed weight",
        ),
    )


def pool(
    references: Sequence[ReferenceMeasure], *, reference_id: str = "ref-pooled"
) -> tuple[ReferenceMeasure, npt.NDArray[np.int64]]:
    """Concatenate per-window references into one measure over space-time bins.

    A pseudo-prospective alarm experiment is not one Molchan diagram per window. It is one diagram
    over the whole schedule, whose bins are ``(window, cell)`` pairs and whose horizontal axis is
    the fraction of the *total expected events* the alarm covers. Weighting each window by its own
    ``expected_events`` is what makes a month during an aftershock sequence count for more than a
    quiet one; normalising each window to 1 and averaging would silently give them equal weight and
    would flatter any alarm that fires during the busy months.

    Returns the pooled measure and the offset of each window's first bin, so a caller can
    concatenate its alarm values and event counts in the same order.
    """
    if not references:
        msg = "no references to pool"
        raise MissingReferenceError(msg)
    kinds = {r.kind for r in references}
    if len(kinds) != 1:
        msg = f"cannot pool references of different kinds: {sorted(k.value for k in kinds)}"
        raise MissingReferenceError(msg)
    sizes = [r.cell_size_deg for r in references]
    if len(set(sizes)) != 1:
        msg = f"cannot pool references on different cell sizes: {sorted(set(sizes))}"
        raise MissingReferenceError(msg)
    weights: list[npt.NDArray[np.float64]] = []
    origins: list[tuple[float, float]] = []
    offsets: list[int] = []
    cursor = 0
    for r in references:
        if r.expected_events is None:
            msg = (
                f"reference {r.id!r} carries no expected_events, so it cannot be weighted against "
                "the other windows in the schedule"
            )
            raise MissingReferenceError(msg)
        weights.append(r.probabilities * r.expected_events)
        origins.extend(r.cell_origins)
        offsets.append(cursor)
        cursor += r.n_cells
    stacked = np.concatenate(weights)
    total = float(sum(float(r.expected_events or 0.0) for r in references))
    first = references[0]
    return (
        ReferenceMeasure(
            id=reference_id,
            kind=first.kind,
            model_id=first.model_id,
            cell_size_deg=first.cell_size_deg,
            cell_origins=tuple(origins),
            probabilities=_normalise(stacked, "the pooled schedule"),
            expected_events=total,
            notes=(
                f"pooled over {len(references)} window(s), weighted by expected events; "
                f"{total:.3g} expected in total",
            ),
        ),
        np.asarray(offsets, dtype=np.int64),
    )


def uniform_like(reference: ReferenceMeasure) -> ReferenceMeasure:
    """The uniform contrast to a real reference: same cells, same expectation, flat in space.

    Copying ``expected_events`` is what makes the comparison mean one thing. Both references then
    expect the same number of events in the window and differ only in where they put them, so the
    difference between the two scores is the effect of the spatial distribution alone — which is
    the effect Zhang et al. (2024) measured — and not a mixture of that with a difference in rate.
    """
    return uniform(
        reference.cell_origins,
        reference.cell_size_deg,
        expected_events=reference.expected_events,
        reference_id=f"{reference.id}-uniform-contrast",
    )
