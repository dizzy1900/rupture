"""Monte Carlo simulation of the fitted intensity over a forecast window.

The model is a branching process, so it can be simulated exactly without thinning: every event
draws a Poisson number of direct offspring whose mean is the closed-form mass of its kernel inside
the window, and each offspring's delay and displacement are inverse-CDF samples from the same
mixture the likelihood used. Descendants are generated generation by generation until none remain.

The forecast this produces is a *rate* forecast: the mean number of events per cell over the
window, across ``n_simulations`` independent continuations of the observed history. It is not a
statement that anything takes place in any cell.

The **background component is analytic, not sampled** (``include_background=False``, which is what
the adapter uses), for the same reason the ETAS adapter makes it analytic in ADR-0018: sampling it
leaves cells with exactly zero expected count wherever no simulated event happened to land, and an
observed event in a zero-rate cell sends the log-likelihood to negative infinity, which makes the
consistency and paired tests undefined rather than merely bad. The cost is the same one the
baseline pays — offspring of background events that occur *inside* the window are not counted —
and it is small over a thirty-day horizon at these rates. Sampling the background is kept as an
option because it is the self-consistent thing to do when the question is about the process rather
than about the grid.

Magnitudes are handled the way the ETAS adapter handles them (ADR-0018): sampled from the
Gutenberg-Richter law during simulation, because an event's magnitude drives its own productivity,
but the final per-cell counts are spread across magnitude bins by the **analytic** GR mass rather
than by the sampled magnitudes. Binning sampled magnitudes would add Monte Carlo noise to a
quantity available in closed form, and the sparse upper bins are exactly where that noise is worst.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt
import torch

from rupture.adapters.forecasting.grid import Lattice
from rupture.models.challengers.ntpp.kernels import sample_powerlaw_radius
from rupture.models.challengers.ntpp.model import FeatureBuilder, NeuralKernelHawkes
from rupture.models.data.geo import Projection

_F8 = npt.NDArray[np.float64]

MAX_GENERATIONS = 50
MAX_EVENTS_PER_SIMULATION = 200_000


@dataclass(frozen=True)
class EventBatch:
    """A set of events as parallel arrays: time in days, projected km, mark, depth."""

    t: _F8
    x: _F8
    y: _F8
    mw: _F8
    depth: _F8

    def __len__(self) -> int:
        return int(self.t.size)

    @classmethod
    def empty(cls) -> EventBatch:
        z = np.zeros(0, dtype=np.float64)
        return cls(t=z, x=z.copy(), y=z.copy(), mw=z.copy(), depth=z.copy())

    @classmethod
    def concat(cls, batches: list[EventBatch]) -> EventBatch:
        live = [b for b in batches if len(b) > 0]
        if not live:
            return cls.empty()
        return cls(
            t=np.concatenate([b.t for b in live]),
            x=np.concatenate([b.x for b in live]),
            y=np.concatenate([b.y for b in live]),
            mw=np.concatenate([b.mw for b in live]),
            depth=np.concatenate([b.depth for b in live]),
        )


def history_batch(
    t: npt.ArrayLike,
    x: npt.ArrayLike,
    y: npt.ArrayLike,
    mw: npt.ArrayLike,
    depth: npt.ArrayLike,
    *,
    fill_depth: float,
) -> EventBatch:
    """Build the conditioning batch, replacing missing depths with the training fill value."""
    d = np.asarray(depth, dtype=np.float64)
    return EventBatch(
        t=np.asarray(t, dtype=np.float64),
        x=np.asarray(x, dtype=np.float64),
        y=np.asarray(y, dtype=np.float64),
        mw=np.asarray(mw, dtype=np.float64),
        depth=np.where(np.isfinite(d), d, fill_depth).astype(np.float64),
    )


@dataclass
class SimulationDiagnostics:
    """What the sampler did, so an implausible forecast can be traced to its cause."""

    n_simulations: int
    n_background: int = 0
    n_triggered: int = 0
    n_outside_cells: int = 0
    max_generation: int = 0
    truncated_simulations: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "n_simulations": self.n_simulations,
            "n_background_sampled": self.n_background,
            "n_triggered_sampled": self.n_triggered,
            "n_outside_cells": self.n_outside_cells,
            "max_generation": self.max_generation,
            "truncated_simulations": self.truncated_simulations,
            "notes": sorted(set(self.notes)),
        }


def _head_outputs(
    model: NeuralKernelHawkes, features: FeatureBuilder, mw: _F8, depth: _F8
) -> tuple[_F8, _F8, _F8]:
    """Mixture weights and productivity for a batch of events, as numpy."""
    with torch.no_grad():
        feat = torch.tensor(features.transform(mw, depth), dtype=torch.float64)
        w_time, w_space = model.kernel_weights(feat)
        amp = model.productivity(torch.tensor(mw, dtype=torch.float64))
    return (
        np.asarray(w_time.numpy(), dtype=np.float64),
        np.asarray(w_space.numpy(), dtype=np.float64),
        np.asarray(amp.numpy(), dtype=np.float64),
    )


def _sample_categorical(weights: _F8, rng: np.random.Generator) -> npt.NDArray[np.int64]:
    """One category per row of ``weights`` (rows need not be normalised)."""
    cdf: _F8 = np.asarray(np.cumsum(weights, axis=1), dtype=np.float64)
    cdf = cdf / cdf[:, -1:]
    u = np.asarray(rng.random(weights.shape[0]), dtype=np.float64)[:, None]
    picked: npt.NDArray[np.int64] = np.asarray((u > cdf).sum(axis=1), dtype=np.int64)
    out: npt.NDArray[np.int64] = np.minimum(picked, weights.shape[1] - 1)
    return out


def _sample_gr(rng: np.random.Generator, n: int, beta: float, mc_lower: float) -> _F8:
    out: _F8 = mc_lower + rng.exponential(scale=1.0 / beta, size=n)
    return out


def _sample_depths(rng: np.random.Generator, n: int, pool: _F8, fill: float) -> _F8:
    if n == 0:
        return np.zeros(0, dtype=np.float64)
    if pool.size == 0:
        return np.full(n, fill, dtype=np.float64)
    out: _F8 = rng.choice(pool, size=n, replace=True).astype(np.float64)
    return out


def offspring(
    model: NeuralKernelHawkes,
    features: FeatureBuilder,
    sources: EventBatch,
    *,
    window_start: float,
    window_end: float,
    beta: float,
    mc_lower: float,
    depth_pool: _F8,
    rng: np.random.Generator,
) -> EventBatch:
    """Direct offspring of ``sources`` falling inside ``[window_start, window_end)``.

    A source before the window contributes only the part of its kernel that lands inside it; a
    source inside the window contributes from its own time onwards. Both are the same closed-form
    difference of Omori integrals, so no offspring is ever sampled and then discarded for being
    early.
    """
    if len(sources) == 0:
        return EventBatch.empty()
    w_time, w_space, amp = _head_outputs(model, features, sources.mw, sources.depth)
    c = np.asarray(model.time_scales.numpy(), dtype=np.float64)
    d = np.asarray(model.space_scales.numpy(), dtype=np.float64)
    p, s = model.config.omori_p, model.config.spatial_s

    lower = np.maximum(window_start - sources.t, 0.0)
    upper = np.maximum(window_end - sources.t, 0.0)
    f_lo = 1.0 - (1.0 + lower[:, None] / c[None, :]) ** (-(p - 1.0))
    f_hi = 1.0 - (1.0 + upper[:, None] / c[None, :]) ** (-(p - 1.0))
    mass = np.clip(f_hi - f_lo, 0.0, None)
    expected = amp * (w_time * mass).sum(axis=1)
    counts = rng.poisson(np.clip(expected, 0.0, None))
    total = int(counts.sum())
    if total == 0:
        return EventBatch.empty()

    parent = np.repeat(np.arange(len(sources)), counts)
    k = _sample_categorical(w_time[parent] * mass[parent], rng)
    lo_k, hi_k = f_lo[parent, k], f_hi[parent, k]
    u = lo_k + rng.random(total) * (hi_k - lo_k)
    delay = c[k] * ((1.0 - np.clip(u, 0.0, 1.0 - 1e-12)) ** (-1.0 / (p - 1.0)) - 1.0)
    t_child = sources.t[parent] + delay

    ell = _sample_categorical(w_space[parent], rng)
    radius = sample_powerlaw_radius(rng.random(total), d[ell], s)
    angle = rng.random(total) * 2.0 * np.pi
    keep = (t_child >= window_start) & (t_child < window_end)
    n_keep = int(np.count_nonzero(keep))
    return EventBatch(
        t=t_child[keep],
        x=(sources.x[parent] + radius * np.cos(angle))[keep],
        y=(sources.y[parent] + radius * np.sin(angle))[keep],
        mw=_sample_gr(rng, n_keep, beta, mc_lower),
        depth=_sample_depths(rng, n_keep, depth_pool, features.depth_fill),
    )


def simulate_window(
    model: NeuralKernelHawkes,
    features: FeatureBuilder,
    *,
    history: EventBatch,
    background_x: _F8,
    background_y: _F8,
    depth_pool: _F8,
    window_start: float,
    window_end: float,
    lattice: Lattice,
    projection: Projection,
    n_simulations: int,
    seed: int,
    mc_lower: float,
    include_background: bool = True,
) -> tuple[_F8, SimulationDiagnostics]:
    """Mean number of events per lattice cell over ``[window_start, window_end)`` in days.

    ``history`` holds every event the model conditions on. The caller is responsible for it
    containing nothing at or after the issue time and asserts that separately, through
    ``assert_all_before``; this function is deliberately not the place that check lives, because a
    sampler that silently drops late events is exactly the failure ADR-0022 is about.

    With ``include_background=False`` only the cascade seeded by ``history`` is simulated, and the
    caller adds the background analytically; see the module docstring for why that is the default
    on the forecasting path.
    """
    if n_simulations < 1:
        msg = "n_simulations must be >= 1"
        raise ValueError(msg)
    if window_end <= window_start:
        msg = "window_end must be after window_start"
        raise ValueError(msg)
    rng = np.random.default_rng(seed)
    with torch.no_grad():
        mu = float(torch.exp(model.log_mu).item())
        beta = float(torch.exp(model.log_beta).item())
    sigma = model.config.background_sigma_km
    duration = window_end - window_start
    diag = SimulationDiagnostics(n_simulations=n_simulations)
    totals = np.zeros(lattice.n_cells, dtype=np.float64)

    for _ in range(n_simulations):
        n_bg = int(rng.poisson(mu * duration)) if include_background else 0
        if n_bg and background_x.size == 0:
            msg = "background rate is positive but no background reference points are set"
            raise RuntimeError(msg)
        pick = (
            rng.integers(0, background_x.size, size=n_bg) if n_bg else np.zeros(0, dtype=np.int64)
        )
        background = EventBatch(
            t=window_start + rng.random(n_bg) * duration,
            x=background_x[pick] + rng.normal(0.0, sigma, size=n_bg),
            y=background_y[pick] + rng.normal(0.0, sigma, size=n_bg),
            mw=_sample_gr(rng, n_bg, beta, mc_lower),
            depth=_sample_depths(rng, n_bg, depth_pool, features.depth_fill),
        )
        diag.n_background += n_bg
        emitted: list[EventBatch] = [background]
        n_in_sim = n_bg
        sources = EventBatch.concat([history, background])
        for generation in range(MAX_GENERATIONS):
            children = offspring(
                model,
                features,
                sources,
                window_start=window_start,
                window_end=window_end,
                beta=beta,
                mc_lower=mc_lower,
                depth_pool=depth_pool,
                rng=rng,
            )
            if len(children) == 0:
                break
            emitted.append(children)
            diag.n_triggered += len(children)
            n_in_sim += len(children)
            diag.max_generation = max(diag.max_generation, generation + 1)
            if n_in_sim > MAX_EVENTS_PER_SIMULATION:
                diag.truncated_simulations += 1
                diag.notes.append(
                    f"simulation truncated at the {MAX_EVENTS_PER_SIMULATION}-event cap"
                )
                break
            sources = children
        else:  # pragma: no cover - reached only by a supercritical fit
            diag.truncated_simulations += 1
            diag.notes.append(f"cascade reached the generation cap ({MAX_GENERATIONS})")

        whole = EventBatch.concat(emitted)
        if len(whole):
            lon, lat = projection.inverse(whole.x, whole.y)
            cells = lattice.cell_indices(lon, lat)
            inside = cells >= 0
            diag.n_outside_cells += int(np.count_nonzero(~inside))
            np.add.at(totals, cells[inside], 1.0)

    totals /= float(n_simulations)
    return totals, diag
