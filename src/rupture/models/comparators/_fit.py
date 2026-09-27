"""Shared occupancy logistic: features, MLE, Gutenberg-Richter split.

No ``auc`` here. Occupancy probability is an intermediate; the artefact is an expected count.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import numpy.typing as npt
from scipy.optimize import minimize
from scipy.special import expit

from rupture.adapters.forecasting.etas_mizrahi import gr_bin_probabilities
from rupture.adapters.forecasting.grid import Lattice
from rupture.domain import Catalog, Event, Region
from rupture.models.comparators.errors import MissingSlipFieldError
from rupture.models.comparators.slip import SlipField
from rupture.models.data.geo import Projection

_F8 = npt.NDArray[np.float64]
LOG10_E = math.log10(math.e)
DISTANCE_FLOOR_KM = 0.1
SLIP_FLOOR_M = 1e-3
_SLIP_VARIATION_MIN = 1e-6


@dataclass(frozen=True, slots=True)
class LogisticFit:
    """Coefficients and the training-only conversion from occupancy P to a count."""

    a: float
    b: float
    c: float | None
    log_likelihood: float
    n_positive_cells: int
    n_training_events: int
    mean_events_per_positive_cell: float
    training_days: float
    n_cells: int
    used_slip: bool
    b_value: float | None
    mag_pmf: tuple[float, ...]


def cell_centres(lattice: Lattice) -> tuple[_F8, _F8]:
    half = lattice.cell_size_deg / 2.0
    lon = np.asarray([origin[0] + half for origin in lattice.origins], dtype=np.float64)
    lat = np.asarray([origin[1] + half for origin in lattice.origins], dtype=np.float64)
    return lon, lat


def log10_distance_to_anchors(
    lattice: Lattice,
    projection: Projection,
    anchors: tuple[Event, ...],
    *,
    distance_floor_km: float = DISTANCE_FLOOR_KM,
) -> _F8:
    """``log10`` of kilometres to the nearest training event with ``mw >= m_main``, floored."""
    if not anchors:
        msg = "no training events at or above m_main, so distance-to-mainshock is undefined"
        raise ValueError(msg)
    cell_lon, cell_lat = cell_centres(lattice)
    cx, cy = projection.forward(cell_lon, cell_lat)
    ax, ay = projection.forward(
        np.asarray([e.longitude for e in anchors], dtype=np.float64),
        np.asarray([e.latitude for e in anchors], dtype=np.float64),
    )
    dx = cx[:, None] - ax[None, :]
    dy = cy[:, None] - ay[None, :]
    dist = np.sqrt(dx * dx + dy * dy)
    nearest = np.min(dist, axis=1)
    return np.asarray(np.log10(np.maximum(nearest, distance_floor_km)), dtype=np.float64)


def events_on_lattice(lattice: Lattice, events: tuple[Event, ...]) -> tuple[Event, ...]:
    """Events whose epicentre falls in a lattice cell. Outside the region they do not label."""
    if not events:
        return ()
    cells = lattice.cell_indices(
        np.asarray([e.longitude for e in events], dtype=np.float64),
        np.asarray([e.latitude for e in events], dtype=np.float64),
    )
    return tuple(event for event, cell in zip(events, cells.tolist(), strict=True) if cell >= 0)


def occupancy_labels(
    lattice: Lattice, events: tuple[Event, ...]
) -> tuple[_F8, npt.NDArray[np.int64]]:
    """Binary occupancy per cell, and the integer event count used for productivity."""
    counts = np.zeros(lattice.n_cells, dtype=np.int64)
    if not events:
        return np.zeros(lattice.n_cells, dtype=np.float64), counts
    cells = lattice.cell_indices(
        np.asarray([e.longitude for e in events], dtype=np.float64),
        np.asarray([e.latitude for e in events], dtype=np.float64),
    )
    keep = cells >= 0
    np.add.at(counts, cells[keep], 1)
    y = (counts > 0).astype(np.float64)
    return y, counts


def log10_slip(field: SlipField, lattice: Lattice, *, slip_floor_m: float = SLIP_FLOOR_M) -> _F8:
    if field.cell_origins != lattice.origins:
        msg = (
            "finite-fault / slip field is not on this region's lattice "
            f"({len(field.cell_origins)} cell(s) vs {lattice.n_cells} lattice cell(s)); "
            "resample it with slip_field_from_subfaults rather than dropping the feature"
        )
        raise MissingSlipFieldError(msg)
    slip = np.maximum(field.as_array(), slip_floor_m)
    log_s = np.log10(slip)
    if float(np.std(log_s)) < _SLIP_VARIATION_MIN:
        msg = (
            "finite-fault / slip field is spatially constant on this lattice, so log mean slip "
            "is collinear with the intercept and the three-parameter model is not identified on "
            "a single sequence. Sample a spatially varying slip model at each cell."
        )
        raise MissingSlipFieldError(msg)
    return np.asarray(log_s, dtype=np.float64)


def occupancy_probability(
    a: float,
    b: float,
    log_distance: _F8,
    c: float | None = None,
    log_slip: _F8 | None = None,
) -> _F8:
    """P = 1 / (1 + exp(-(a + b x [+ c z]))). Intermediate only; multiply by productivity."""
    z = a + b * log_distance
    if c is not None:
        if log_slip is None:
            msg = "three-parameter logistic was given c but no log-slip vector"
            raise MissingSlipFieldError(msg)
        z = z + c * log_slip
    return np.asarray(expit(z), dtype=np.float64)


def _neg_log_likelihood(theta: _F8, design: _F8, y: _F8) -> float:
    logits = design @ theta
    # y log sigmoid(z) + (1-y) log sigmoid(-z), stable via logaddexp.
    pos = y * (-np.logaddexp(0.0, -logits))
    neg = (1.0 - y) * (-np.logaddexp(0.0, logits))
    return float(-np.sum(pos + neg))


def fit_logistic_mle(design: _F8, y: _F8) -> tuple[_F8, float]:
    """Maximum-likelihood Bernoulli logistic. ``design`` includes the intercept column."""
    n_pos = int(y.sum())
    n_neg = int(y.size - n_pos)
    if n_pos == 0 or n_neg == 0:
        msg = (
            f"training occupancy is degenerate ({n_pos} positive cell(s), {n_neg} negative); "
            "refusing to fit a logistic that cannot see both classes"
        )
        raise ValueError(msg)
    n_coef = int(design.shape[1])
    x0 = np.zeros(n_coef, dtype=np.float64)
    x0[1] = -2.0
    if n_coef > 2:
        x0[2] = 1.0
    result = minimize(
        _neg_log_likelihood,
        x0,
        args=(design, y),
        method="L-BFGS-B",
    )
    if not result.success:
        msg = f"logistic MLE did not converge: {result.message}"
        raise ValueError(msg)
    theta = np.asarray(result.x, dtype=np.float64)
    if not np.all(np.isfinite(theta)):
        msg = "logistic MLE returned a non-finite coefficient"
        raise ValueError(msg)
    nll = _neg_log_likelihood(theta, design, y)
    return theta, -nll


def aki_b_value(magnitudes: _F8, mc: float, delta_m: float) -> float | None:
    """Aki (1965) MLE b with the half-bin correction; ``None`` when the sample cannot support it."""
    sel = magnitudes[magnitudes >= mc - delta_m / 2.0 - 1e-9]
    if sel.size < 2:
        return None
    mean = float(sel.mean())
    denom = mean - (mc - delta_m / 2.0)
    if denom <= 0.0:
        return None
    return LOG10_E / denom


def magnitude_pmf(
    magnitudes: _F8, mc: float, edges: tuple[float, ...], width: float
) -> tuple[float, ...]:
    """Gutenberg-Richter mass per protocol bin, fitted on training magnitudes only."""
    n_bins = len(edges)
    fallback = tuple(1.0 if i == 0 else 0.0 for i in range(n_bins))
    b_val = aki_b_value(magnitudes, mc, width)
    if b_val is None:
        return fallback
    beta = b_val * math.log(10.0)
    mc_lower = mc - width / 2.0
    pmf = gr_bin_probabilities(beta, mc_lower, edges, None)
    total = float(pmf.sum())
    if not math.isfinite(total) or total <= 0.0:
        return fallback
    return tuple(float(v / total) for v in pmf)


def target_events(catalog: Catalog, *, min_mw: float) -> tuple[Event, ...]:
    return tuple(e for e in catalog.earthquakes().events if e.mw is not None and e.mw >= min_mw)


def mainshock_anchors(catalog: Catalog, *, m_main: float) -> tuple[Event, ...]:
    return target_events(catalog, min_mw=m_main)


def training_span_days(
    catalog: Catalog, cutoff: datetime, *, start: datetime | None = None
) -> float:
    """Length of the training window in days: first used event to cutoff, floored at one second.

    ``start`` is the first origin that actually labelled the lattice. The enclosing catalogue may
    be older and wider than the region; spreading occupancy events over that longer span would
    understate the local rate.
    """
    origin = start if start is not None else catalog.min_origin_time()
    if origin is None:
        msg = "empty training catalogue"
        raise ValueError(msg)
    seconds = (cutoff - origin).total_seconds()
    if seconds <= 0.0:
        msg = "training window is not positive"
        raise ValueError(msg)
    return seconds / 86400.0


def design_matrix(log_distance: _F8, log_slip: _F8 | None) -> _F8:
    intercept = np.ones((log_distance.size, 1), dtype=np.float64)
    cols = [intercept, log_distance.reshape(-1, 1)]
    if log_slip is not None:
        cols.append(log_slip.reshape(-1, 1))
    return np.concatenate(cols, axis=1)


def assemble_fit(
    *,
    theta: _F8,
    log_likelihood: float,
    y: _F8,
    event_counts: npt.NDArray[np.int64],
    training_days: float,
    used_slip: bool,
    magnitudes: _F8,
    mc: float,
    edges: tuple[float, ...],
    width: float,
) -> LogisticFit:
    n_positive = int(y.sum())
    n_events = int(event_counts.sum())
    if n_positive <= 0:
        msg = "no positive cells after binning; refusing to convert P to a count"
        raise ValueError(msg)
    b_val = aki_b_value(magnitudes, mc, width)
    return LogisticFit(
        a=float(theta[0]),
        b=float(theta[1]),
        c=float(theta[2]) if used_slip else None,
        log_likelihood=log_likelihood,
        n_positive_cells=n_positive,
        n_training_events=n_events,
        mean_events_per_positive_cell=n_events / n_positive,
        training_days=training_days,
        n_cells=int(y.size),
        used_slip=used_slip,
        b_value=b_val,
        mag_pmf=magnitude_pmf(magnitudes, mc, edges, width),
    )


def expected_counts_from_occupancy(
    probability: _F8,
    fit: LogisticFit,
    horizon_days: float,
    *,
    rate_scale: float | None = None,
) -> _F8:
    """Convert occupancy P to expected event counts over ``horizon_days``.

    Training-only scale: ``mean_events_per_positive_cell * (horizon_days / training_days)``.
    ``rate_scale``, when given, replaces that product so a caller can impose a different
    productivity without touching the spatial logistic.
    """
    if rate_scale is None:
        scale = fit.mean_events_per_positive_cell * (horizon_days / fit.training_days)
    else:
        if not math.isfinite(rate_scale) or rate_scale < 0.0:
            msg = f"rate_scale must be finite and non-negative, got {rate_scale!r}"
            raise ValueError(msg)
        scale = rate_scale
    counts = probability * scale
    return np.asarray(np.where(np.isfinite(counts) & (counts > 0.0), counts, 0.0), dtype=np.float64)


def split_across_magnitude_bins(
    spatial: _F8, pmf: tuple[float, ...]
) -> tuple[tuple[float, ...], ...]:
    weights = np.asarray(pmf, dtype=np.float64)
    expected = np.outer(spatial, weights)
    expected = np.where(np.isfinite(expected) & (expected > 0.0), expected, 0.0)
    return tuple(tuple(float(v) for v in row) for row in expected)


def resolve_mc(region: Region, catalog: Catalog, explicit: float | None) -> float:
    if explicit is not None:
        return explicit
    if region.mc is not None:
        return region.mc.mc
    preferred = catalog.preferred_mc()
    if preferred is not None:
        return preferred.mc
    return region.target_min_magnitude
