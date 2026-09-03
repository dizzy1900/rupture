"""Log-linear (geometric) ensemble of ETAS and any challenger (ADR-0032).

``log lambda_ens = sum_k w_k log lambda_k``, normalised, with ``w_k >= 0`` and ``sum_k w_k = 1``.
The weights are fitted on a **validation window strictly before the test window** and on nothing
else; the ensemble then implements ``ForecastModel`` so it is issued and scored exactly like any
other model.

Two things a log-linear pool has to get right, and this module makes both explicit.

**Zero-rate cells.** ``log 0`` is not a number, and a gridded rate forecast has cell-magnitude
bins whose expected count is zero or denormal. Each component's rates are floored at
``floor_fraction`` times that component's *own* mean rate per cell-bin
(``total / (n_cells * n_bins)``). A relative floor is used rather than an absolute one so the
floor means the same thing for a region with a hundred target events per year as for one with
two, and so that it is invariant to the choice of magnitude threshold. The default
``floor_fraction = 1e-6`` was fixed in advance and was **not** tuned on any window: it is small
enough to leave every cell either model gives real support to unchanged, and large enough that a
cell one model has effectively excluded cannot drive the pooled log-likelihood to minus infinity
on its own. A geometric pool is intolerant of disagreement by construction — that is the point of
choosing it over a linear pool — and the floor bounds how intolerant it is allowed to be.

**Normalisation.** The pooled rates are rescaled so the ensemble's total expected count is the
weighted geometric mean of the components' totals, ``log N_ens = sum_k w_k log N_k``. Without a
rescaling step the pooled field is not a rate at all (the geometric mean of two rate fields does
not integrate to anything in particular); with it, the ensemble's N-test behaviour is a
predictable interpolation between its components' rather than an artefact of the pooling.

Weights are fitted by maximising the Poisson log-likelihood of the observed target catalogues over
the validation windows, on a deterministic grid over the simplex (coarse pass then a refinement
pass). No gradient optimiser, so the fitted weights are reproducible to the grid step and do not
depend on an initialisation.

rupture does not predict earthquakes; the ensemble issues expected counts per cell and magnitude
bin, as its components do.
"""

from __future__ import annotations

import itertools
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import numpy.typing as npt

from rupture.adapters.forecasting.grid import build_lattice, magnitude_bin_indices
from rupture.adapters.forecasting.leakage import assert_all_before, assert_within_window
from rupture.domain import (
    Catalog,
    EventType,
    FitResult,
    ForecastGrid,
    Region,
    snapshot_hash,
    utc_now,
)

log = logging.getLogger(__name__)

MODEL_ID = "ensemble-loglinear"
MODEL_VERSION = "ensemble-loglinear-0.1.0"

DEFAULT_FLOOR_FRACTION = 1e-6

#: A component supplies a forecast for one issue time from a causal history.
Component = Callable[[Catalog, datetime, timedelta], ForecastGrid]


@dataclass(frozen=True)
class EnsembleWeights:
    """Fitted weights on the simplex, with the validation evidence that produced them."""

    names: tuple[str, ...]
    values: tuple[float, ...]
    floor_fraction: float
    validation_log_likelihood: float
    validation_windows: int
    validation_target_events: int
    grid_step: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "weights": dict(zip(self.names, self.values, strict=True)),
            "floor_fraction": self.floor_fraction,
            "validation_log_likelihood": self.validation_log_likelihood,
            "validation_windows": self.validation_windows,
            "validation_target_events": self.validation_target_events,
            "grid_step": self.grid_step,
        }


# ---------------------------------------------------------------------- pooling
def floored_log_rates(
    counts: npt.NDArray[np.float64], floor_fraction: float
) -> tuple[npt.NDArray[np.float64], float]:
    """``log(max(lambda, floor))`` with ``floor = floor_fraction * mean rate per cell-bin``."""
    total = float(counts.sum())
    size = int(counts.size)
    floor = floor_fraction * max(total, np.finfo(np.float64).tiny) / max(size, 1)
    floor = max(floor, np.finfo(np.float64).tiny)
    return np.log(np.maximum(counts, floor)), floor


def combine(
    grids: Sequence[ForecastGrid],
    weights: Sequence[float],
    *,
    floor_fraction: float = DEFAULT_FLOOR_FRACTION,
) -> npt.NDArray[np.float64]:
    """Pooled expected counts, ``(n_cells, n_bins)``, normalised to the geometric-mean total."""
    if len(grids) != len(weights):
        msg = "one weight per component is required"
        raise ValueError(msg)
    w = np.asarray(weights, dtype=np.float64)
    if w.min() < 0.0 or not np.isclose(w.sum(), 1.0, atol=1e-9):
        msg = f"weights must be non-negative and sum to 1; got {w.tolist()}"
        raise ValueError(msg)
    logs = []
    log_totals = []
    for grid in grids:
        counts = grid.counts()
        lg, _ = floored_log_rates(counts, floor_fraction)
        logs.append(lg)
        log_totals.append(np.log(max(float(counts.sum()), np.finfo(np.float64).tiny)))
    pooled = np.tensordot(w, np.stack(logs), axes=(0, 0))
    target_total = float(np.exp(float(np.dot(w, np.asarray(log_totals)))))
    shifted = np.exp(pooled - pooled.max())
    denom = float(shifted.sum())
    if denom <= 0.0 or not np.isfinite(denom):  # pragma: no cover - guarded by the floor
        msg = "pooled rates vanished; check the floor"
        raise ValueError(msg)
    out: npt.NDArray[np.float64] = shifted * (target_total / denom)
    return np.where(np.isfinite(out) & (out > 0.0), out, 0.0)


def observed_counts(target: Catalog, grid: ForecastGrid) -> npt.NDArray[np.float64]:
    """Target events binned onto the forecast's own cells and magnitude bins.

    The filters are the evaluator's (``PyCSEPEvaluator.to_csep_catalog``): earthquakes with a
    homogenised Mw at or above the first bin edge whose epicentre falls in a cell of the grid.
    """
    lattice_edges = np.asarray(grid.magnitude_bin_edges, dtype=np.float64)
    out = np.zeros((len(grid.cell_origins), len(lattice_edges)), dtype=np.float64)
    rows = [
        e
        for e in target.events
        if e.event_type == EventType.EARTHQUAKE
        and e.mw is not None
        and e.mw >= float(lattice_edges[0])
    ]
    if not rows:
        return out
    origins = np.asarray(grid.cell_origins, dtype=np.float64)
    dh = grid.cell_size_deg
    lon0 = float(np.min(origins[:, 0]))
    lat0 = float(np.min(origins[:, 1]))
    index_of = {
        (round((lon - lon0) / dh), round((lat - lat0) / dh)): i
        for i, (lon, lat) in enumerate(origins)
    }
    lons = np.array([e.longitude for e in rows], dtype=np.float64)
    lats = np.array([e.latitude for e in rows], dtype=np.float64)
    mws = np.array([e.mw for e in rows], dtype=np.float64)
    ix = np.floor((lons - lon0) / dh + 1e-9).astype(np.int64)
    iy = np.floor((lats - lat0) / dh + 1e-9).astype(np.int64)
    bins = magnitude_bin_indices(mws, grid.magnitude_bin_edges, grid.magnitude_bin_width)
    for k in range(len(rows)):
        cell = index_of.get((int(ix[k]), int(iy[k])))
        if cell is not None and bins[k] >= 0:
            out[cell, int(bins[k])] += 1.0
    return out


def poisson_log_likelihood(
    rates: npt.NDArray[np.float64], counts: npt.NDArray[np.float64]
) -> float:
    """``sum(n log lambda - lambda)`` (constant factorial terms dropped)."""
    tiny = np.finfo(np.float64).tiny
    return float(np.sum(counts * np.log(np.maximum(rates, tiny)) - rates))


def simplex_grid(k: int, step: float) -> list[tuple[float, ...]]:
    """Every point of the ``k``-simplex on a lattice of spacing ``step``. Deterministic order."""
    n = round(1.0 / step)
    out: list[tuple[float, ...]] = []
    for combo in itertools.product(range(n + 1), repeat=k - 1):
        rest = n - sum(combo)
        if rest < 0:
            continue
        out.append(tuple(v / n for v in (*combo, rest)))
    return out


def fit_weights(
    grids_per_window: Sequence[Sequence[ForecastGrid]],
    counts_per_window: Sequence[npt.NDArray[np.float64]],
    names: Sequence[str],
    *,
    floor_fraction: float = DEFAULT_FLOOR_FRACTION,
    coarse_step: float = 0.05,
    refine_step: float = 0.01,
) -> tuple[tuple[float, ...], float, float]:
    """Weights maximising the summed Poisson log-likelihood over the validation windows."""
    k = len(names)
    if k < 1:
        msg = "the ensemble needs at least one component"
        raise ValueError(msg)
    if k == 1:
        rates = [combine(g, (1.0,), floor_fraction=floor_fraction) for g in grids_per_window]
        ll = sum(
            poisson_log_likelihood(r, c) for r, c in zip(rates, counts_per_window, strict=True)
        )
        return (1.0,), float(ll), refine_step

    def score(w: tuple[float, ...]) -> float:
        return sum(
            poisson_log_likelihood(combine(g, w, floor_fraction=floor_fraction), c)
            for g, c in zip(grids_per_window, counts_per_window, strict=True)
        )

    best_w = tuple(1.0 / k for _ in range(k))
    best = score(best_w)
    for w in simplex_grid(k, coarse_step):
        value = score(w)
        if value > best:
            best, best_w = value, w
    # refinement inside one coarse cell around the best point
    span = coarse_step
    for w in simplex_grid(k, refine_step):
        if max(abs(a - b) for a, b in zip(w, best_w, strict=True)) > span + 1e-9:
            continue
        value = score(w)
        if value > best:
            best, best_w = value, w
    return best_w, float(best), refine_step


# ---------------------------------------------------------------------- the model
class LogLinearEnsemble:
    """``ForecastModel``: a weighted geometric pool of component gridded rate forecasts.

    ``components`` maps a name to a callable ``(history, issue_time, horizon) -> ForecastGrid``.
    The list is configurable, so the ensemble runs with ETAS plus the gridded challenger alone
    when no other challenger is available in the tree.
    """

    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION

    def __init__(
        self,
        components: Mapping[str, Component],
        *,
        validation_issue_times: Sequence[datetime] = (),
        horizon: timedelta = timedelta(days=30),
        floor_fraction: float = DEFAULT_FLOOR_FRACTION,
        coarse_step: float = 0.05,
        refine_step: float = 0.01,
    ) -> None:
        if not components:
            msg = "the ensemble needs at least one component"
            raise ValueError(msg)
        self.components = dict(components)
        self.validation_issue_times = tuple(validation_issue_times)
        self.horizon = horizon
        self.floor_fraction = floor_fraction
        self.coarse_step = coarse_step
        self.refine_step = refine_step
        self._weights: EnsembleWeights | None = None
        self._fit: FitResult | None = None
        self._region: Region | None = None

    @property
    def weights(self) -> EnsembleWeights | None:
        return self._weights

    def load_weights(self, weights: EnsembleWeights, fit: FitResult) -> None:
        """Reuse weights fitted on a validation block with a different set of component callables.

        The component *names* must match the ones the weights were fitted for; the callables may
        differ (the same ETAS fit read from its store rather than re-issued, for instance). The
        fit record travels with the weights so the issued grid still carries the snapshot hash of
        the weight fit that produced it.
        """
        if tuple(self.components) != weights.names:
            msg = (
                f"weights were fitted for components {weights.names}, not {tuple(self.components)}"
            )
            raise ValueError(msg)
        self._weights = weights
        self._fit = fit

    @property
    def fit_result(self) -> FitResult | None:
        return self._fit

    def parameter_snapshot(self) -> dict[str, Any]:
        if self._weights is None:
            return {}
        return {
            "components": list(self._weights.names),
            "weights": list(self._weights.values),
            "floor_fraction": self._weights.floor_fraction,
            "normalisation": "geometric mean of component totals",
        }

    # ------------------------------------------------------------------ fit
    def fit(self, catalog: Catalog, region: Region, cutoff: datetime) -> FitResult:
        """Fit the weights on ``validation_issue_times``, every one of which ends before ``cutoff``.

        The cutoff here is the start of the test period. Every validation window must close at or
        before it, and every component forecast must have been issued from a fit whose own cutoff
        is at or before its issue time; both are asserted, not assumed.
        """
        if not self.validation_issue_times:
            msg = (
                "no validation issue times: ensemble weights may only be fitted on a window "
                "strictly before the test window (ADR-0022 § 4)"
            )
            raise ValueError(msg)
        names = tuple(self.components)
        grids_per_window: list[list[ForecastGrid]] = []
        counts_per_window: list[npt.NDArray[np.float64]] = []
        n_targets = 0
        for issue_time in self.validation_issue_times:
            window_end = issue_time + self.horizon
            if window_end > cutoff:
                msg = (
                    f"validation window ending {window_end.isoformat()} reaches past the test "
                    f"cutoff {cutoff.isoformat()}: weights would be fitted on test data"
                )
                raise ValueError(msg)
            history = catalog.before(issue_time)
            assert_all_before(history, issue_time, what="ensemble validation history")
            grids = [self.components[n](history, issue_time, self.horizon) for n in names]
            self._check_aligned(grids, issue_time)
            target = catalog.between(issue_time, window_end)
            assert_within_window(target, issue_time, window_end, what="ensemble validation target")
            counts = observed_counts(target, grids[0])
            grids_per_window.append(grids)
            counts_per_window.append(counts)
            n_targets += int(counts.sum())

        values, ll, step = fit_weights(
            grids_per_window,
            counts_per_window,
            names,
            floor_fraction=self.floor_fraction,
            coarse_step=self.coarse_step,
            refine_step=self.refine_step,
        )
        self._weights = EnsembleWeights(
            names=names,
            values=values,
            floor_fraction=self.floor_fraction,
            validation_log_likelihood=ll,
            validation_windows=len(self.validation_issue_times),
            validation_target_events=n_targets,
            grid_step=step,
        )
        parameters = {f"w_{n}": float(v) for n, v in zip(names, values, strict=True)}
        parameters["floor_fraction"] = float(self.floor_fraction)
        component_fits = {
            n: {
                "fit_cutoff": g.fit_cutoff.isoformat(),
                "model_id": g.model_id,
                "model_version": g.model_version,
                "parameter_snapshot_hash": g.parameter_snapshot_hash,
            }
            for n, g in zip(names, grids_per_window[0], strict=True)
        }
        diagnostics: dict[str, Any] = {
            "components": list(names),
            "component_fits_at_first_validation_window": component_fits,
            "weight_fitting": self._weights.as_dict(),
            "validation_issue_times": [t.isoformat() for t in self.validation_issue_times],
            "validation_window_end": (self.validation_issue_times[-1] + self.horizon).isoformat(),
            "objective": "summed Poisson log-likelihood of the observed cell-magnitude counts",
            "search": {
                "coarse_step": self.coarse_step,
                "refine_step": self.refine_step,
                "method": "deterministic simplex grid; no gradient optimiser, no random restart",
            },
            "zero_rate_floor": (
                "each component's rates are floored at floor_fraction * (its own total / "
                "(n_cells * n_bins)) before the logarithm; see ADR-0032"
            ),
        }
        training = catalog.before(cutoff)
        start = training.min_origin_time()
        result = FitResult(
            model_id=self.model_id,
            model_version=self.model_version,
            region_id=region.id,
            fit_cutoff=cutoff,
            training_start=start if start is not None else cutoff,
            training_catalog_hash=training.event_hash(),
            n_events=n_targets,
            mc=float(region.mc.mc) if region.mc is not None else float(region.target_min_magnitude),
            parameters=parameters,
            parameter_snapshot_hash=snapshot_hash(parameters),
            log_likelihood=ll,
            diagnostics=diagnostics,
            converged=True,
            fitted_at=utc_now(),
            notes=(
                "Weights fitted on the validation windows only; n_events is the number of "
                "validation target events the weights were fitted against, not a training count."
            ),
        )
        self._fit = result
        self._region = region
        return result

    # ------------------------------------------------------------------ forecast
    def forecast(self, history: Catalog, issue_time: datetime, horizon: timedelta) -> ForecastGrid:
        if self._weights is None or self._fit is None:
            msg = "no weights: call fit() on a validation window before issuing"
            raise RuntimeError(msg)
        assert_all_before(history, issue_time, what="ensemble forecast history")
        names = self._weights.names
        grids = [self.components[n](history, issue_time, horizon) for n in names]
        self._check_aligned(grids, issue_time)
        pooled = combine(grids, self._weights.values, floor_fraction=self._weights.floor_fraction)
        first = grids[0]
        weights_text = ", ".join(
            f"{n}={w:.2f}" for n, w in zip(names, self._weights.values, strict=True)
        )
        totals = ", ".join(
            f"{n}={g.total_expected():.4f}" for n, g in zip(names, grids, strict=True)
        )
        return ForecastGrid(
            id=ForecastGrid.make_id(self.model_id, first.region_id, issue_time, horizon),
            region_id=first.region_id,
            model_id=self.model_id,
            model_version=self.model_version,
            parameter_snapshot_hash=self._fit.parameter_snapshot_hash,
            fit_cutoff=self._fit.fit_cutoff,
            training_catalog_hash=self._fit.training_catalog_hash,
            issue_time=issue_time,
            horizon=horizon,
            cell_size_deg=first.cell_size_deg,
            cell_origins=first.cell_origins,
            magnitude_bin_edges=first.magnitude_bin_edges,
            magnitude_bin_width=first.magnitude_bin_width,
            expected_counts=tuple(tuple(float(v) for v in row) for row in pooled),
            n_simulations=None,
            created_at=utc_now(),
            notes=(
                f"log-linear pool of {len(names)} components ({weights_text}); component totals "
                f"{totals}; pooled total {float(pooled.sum()):.4f}; floor_fraction="
                f"{self._weights.floor_fraction:g}; component snapshots "
                + ", ".join(
                    f"{n}:{g.parameter_snapshot_hash[:8]}"
                    for n, g in zip(names, grids, strict=True)
                )
            ),
        )

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _check_aligned(grids: Sequence[ForecastGrid], issue_time: datetime) -> None:
        first = grids[0]
        for g in grids[1:]:
            if g.cell_origins != first.cell_origins:
                msg = f"components disagree on cells: {first.model_id} vs {g.model_id}"
                raise ValueError(msg)
            if g.magnitude_bin_edges != first.magnitude_bin_edges:
                msg = f"components disagree on magnitude bins: {first.model_id} vs {g.model_id}"
                raise ValueError(msg)
        for g in grids:
            if g.issue_time != issue_time:
                msg = (
                    f"component {g.model_id} returned a forecast issued at "
                    f"{g.issue_time.isoformat()}, not {issue_time.isoformat()}"
                )
                raise ValueError(msg)
            if g.fit_cutoff > issue_time:
                msg = (
                    f"component {g.model_id} was fitted to {g.fit_cutoff.isoformat()}, after its "
                    f"issue time {issue_time.isoformat()}"
                )
                raise ValueError(msg)


def lattice_cell_count(region: Region) -> int:
    """Convenience for reports: how many cells the region's lattice holds."""
    return build_lattice(region).n_cells
