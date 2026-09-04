"""Stochastic event sets: synthetic catalogues sampled from a promoted F1 forecast (ADR-0036).

This is the join between rupture's two halves. F1 issues a :class:`~rupture.domain.forecast.
ForecastGrid` — expected counts per cell per magnitude bin over a horizon. F2 prices ruptures.
An event set is what turns the first into an input for the second: draw whole synthetic
catalogues from the grid's rates, turn each drawn event into a
:class:`~rupture.domain.hazard.ScenarioRupture`, and carry the **rate** each event stands for so
the losses can be reduced to an annual figure rather than a what-if.

Four choices are made here, and each is named in :attr:`StochasticEventSet.assumptions` on every
set produced, so a reader never has to find them in the source:

1. **Poisson occurrence within a catalogue.** Counts per cell and magnitude bin are drawn
   independently, ``n_ij ~ Poisson(rate_ij * duration)``. An ETAS forecast's expected counts are
   the mean of a clustered process, so a Poisson draw reproduces the mean exactly and
   **understates** the variance of the annual count; the aggregate exceedance curve is therefore
   tighter in its tail than the underlying process. Recorded, not hidden.
2. **Rates outside the forecast's own horizon are the same rates.** A 30-day ETAS forecast
   describes a decaying, time-dependent rate. Scaling it to a year states "if this rate
   persisted", which for an aftershock sequence it will not. The scaling factor is reported and
   an annual figure from a short-horizon time-dependent grid is labelled every time.
3. **Uniform location within a cell**, which is the finest the grid resolves.
4. **Point ruptures at one stated depth.** rupture will not manufacture a fault plane from a
   magnitude (ADR-0025), so every sampled event is a point rupture unless the caller supplies a
   geometry. Distances are therefore longer than a finite rupture of the same magnitude would
   give and the resulting loss is a lower estimate.

Magnitudes within a bin are drawn from a Gutenberg-Richter density truncated to the bin, using
the region's **fitted** b-value where one is supplied and a stated assumed value otherwise. The
last bin of a ``ForecastGrid`` is open above, so it is sampled from the same density truncated at
``magnitude_max`` when one is known and left unbounded (with a note) when it is not.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta

import numpy as np

from rupture import __version__
from rupture.domain.common import Provenance, utc_now
from rupture.domain.forecast import ForecastGrid
from rupture.domain.hazard import ScenarioRupture
from rupture.domain.region import Region
from rupture.risk import scenarios as scenario_module

ADAPTER_VERSION = __version__
SECONDS_PER_YEAR = 365.0 * 86400.0
"""One year, matching :func:`rupture.domain.forecast.parse_horizon`'s ``1y`` (365 days)."""

DEFAULT_DEPTH_KM = 15.0
"""ASSUMED hypocentral depth for every sampled event, km.

The USGS hypocentral depth for the 2015-04-25 Mw 7.8 Gorkha mainshock (event ``us20002926``) is
15 km, and the Main Himalayan Thrust's locked seismogenic zone sits at broadly that depth. One
stated depth is used rather than a depth distribution because no depth distribution for the
region was fitted in this pass; a made-up distribution would look more informative than a stated
constant while being no better founded.
"""

DEFAULT_B_VALUE = 1.0
"""ASSUMED b-value, used only when no fitted region b-value is supplied."""

DEFAULT_MIN_MAGNITUDE = 5.0
"""Events below this are not sampled at all.

Below about M 5 a point rupture at 15 km depth produces ground motion far below the lowest
fragility median in the library (0.15 g), so such events contribute a negligible loss for a
large share of the run time. Discarding them makes the annual loss a **lower** estimate, by an
amount the caller can bound by lowering the threshold and re-running.
"""

DEFAULT_MAX_EVENTS = 200_000
"""A guard, not a truncation: exceeding it raises rather than silently sampling fewer events."""


class EventSetError(ValueError):
    """The event set cannot be sampled as asked."""


@dataclass(frozen=True, slots=True)
class StochasticEvent:
    """One event of one synthetic catalogue, with the rate it stands for."""

    id: str
    catalogue: int
    """Index of the synthetic catalogue (each covers ``catalogue_duration_years``)."""
    magnitude: float
    longitude: float
    latitude: float
    depth_km: float
    annual_rate: float
    """Occurrence rate this event carries, per year: ``1 / (n_catalogues * duration_years)``."""

    def rupture(self) -> ScenarioRupture:
        """The point rupture this event is priced as (:func:`scenarios.from_stochastic_event`)."""
        return scenario_module.from_stochastic_event(
            event_id=self.id,
            magnitude=self.magnitude,
            longitude=self.longitude,
            latitude=self.latitude,
            depth_km=self.depth_km,
        )


@dataclass(frozen=True, slots=True)
class StochasticEventSet:
    """``n_catalogues`` synthetic catalogues, each covering ``catalogue_duration_years``."""

    id: str
    source_id: str
    """The ForecastGrid (or other rate model) the rates came from."""
    events: tuple[StochasticEvent, ...]
    n_catalogues: int
    catalogue_duration_years: float
    min_magnitude: float
    seed: int | None
    provenance: Provenance
    sampling_rule: str
    assumptions: tuple[str, ...] = ()
    horizon_scaling: float = 1.0
    """``catalogue_duration_years`` divided by the source grid's own horizon, in years."""
    expected_events_per_catalogue: float = 0.0
    fit_cutoff: str | None = None
    """The source forecast's ``fit_cutoff``, carried so a reader can check for leakage."""

    @property
    def total_annual_rate(self) -> float:
        """Summed occurrence rate of every event in the set, per year."""
        return float(sum(e.annual_rate for e in self.events))

    def catalogues(self) -> tuple[tuple[StochasticEvent, ...], ...]:
        """The events grouped by catalogue; empty catalogues are kept as empty tuples."""
        buckets: list[list[StochasticEvent]] = [[] for _ in range(self.n_catalogues)]
        for event in self.events:
            buckets[event.catalogue].append(event)
        return tuple(tuple(b) for b in buckets)

    def lines(self) -> list[str]:
        out = [
            f"event set: {self.id}",
            f"source: {self.source_id}"
            + (f" (fit cutoff {self.fit_cutoff})" if self.fit_cutoff else ""),
            (
                f"{len(self.events)} events over {self.n_catalogues} catalogues of "
                f"{self.catalogue_duration_years:g} year(s); M >= {self.min_magnitude:g}"
            ),
            f"summed occurrence rate: {self.total_annual_rate:.4g} events/year",
            f"sampling: {self.sampling_rule}",
        ]
        out.extend(f"assumption: {a}" for a in self.assumptions)
        return out


@dataclass(frozen=True, slots=True)
class SamplingConfig:
    """Everything about the sampling that is a choice rather than data."""

    n_catalogues: int = 500
    catalogue_duration_years: float = 1.0
    min_magnitude: float = DEFAULT_MIN_MAGNITUDE
    b_value: float | None = None
    """``None`` means: take the region's fitted b-value, or :data:`DEFAULT_B_VALUE` with a note."""
    magnitude_max: float | None = None
    depth_km: float = DEFAULT_DEPTH_KM
    seed: int | None = 20260903
    max_events: int = DEFAULT_MAX_EVENTS

    def __post_init__(self) -> None:
        if self.n_catalogues < 1:
            msg = "n_catalogues must be at least 1"
            raise EventSetError(msg)
        if self.catalogue_duration_years <= 0.0:
            msg = "catalogue_duration_years must be positive"
            raise EventSetError(msg)
        if self.b_value is not None and self.b_value <= 0.0:
            msg = "b_value must be positive"
            raise EventSetError(msg)


def horizon_years(horizon: timedelta) -> float:
    """A forecast horizon in years, on the 365-day year the forecast domain uses."""
    return horizon.total_seconds() / SECONDS_PER_YEAR


def _bin_bounds(grid: ForecastGrid, index: int, magnitude_max: float | None) -> tuple[float, float]:
    """Lower and upper magnitude of bin ``index``; the last bin is open above."""
    edges = grid.magnitude_bin_edges
    lower = edges[index]
    if index + 1 < len(edges):
        return lower, edges[index + 1]
    if magnitude_max is not None:
        return lower, max(magnitude_max, lower + grid.magnitude_bin_width)
    return lower, math.inf


def _sample_magnitudes(
    lower: float, upper: float, b_value: float, size: int, rng: np.random.Generator
) -> np.ndarray:
    """Magnitudes in ``[lower, upper)`` from a Gutenberg-Richter density, by inverse transform."""
    beta = b_value * math.log(10.0)
    u = rng.random(size)
    if not math.isfinite(upper):
        return lower - np.log1p(-u) / beta
    span = 1.0 - math.exp(-beta * (upper - lower))
    return lower - np.log1p(-u * span) / beta


def sample_from_forecast_grid(
    grid: ForecastGrid,
    *,
    config: SamplingConfig | None = None,
    region: Region | None = None,
) -> StochasticEventSet:
    """Sample synthetic catalogues from a :class:`ForecastGrid`'s expected counts.

    The grid's expected counts are over its own ``horizon``. They are scaled to
    ``config.catalogue_duration_years`` before sampling, which is the step that turns a
    time-dependent short-horizon forecast into an annualised rate; the scaling factor and what it
    assumes are recorded on the returned set.
    """
    cfg = config or SamplingConfig()
    grid_years = horizon_years(grid.horizon)
    if grid_years <= 0.0:
        msg = f"forecast grid {grid.id!r} has a non-positive horizon"
        raise EventSetError(msg)
    scaling = cfg.catalogue_duration_years / grid_years

    b_value, b_note = _b_value(cfg, region)
    magnitude_max = cfg.magnitude_max if cfg.magnitude_max is not None else _region_max(region)

    counts = grid.counts() * scaling
    edges = grid.magnitude_bin_edges
    keep_bins = [
        j for j in range(len(edges)) if edges[j] + grid.magnitude_bin_width > cfg.min_magnitude
    ]
    expected = float(counts[:, keep_bins].sum()) if keep_bins else 0.0
    if expected * cfg.n_catalogues > cfg.max_events:
        msg = (
            f"this sampling would draw about {expected * cfg.n_catalogues:,.0f} events, over the "
            f"max_events guard of {cfg.max_events:,}; raise min_magnitude, lower n_catalogues, or "
            "raise max_events deliberately"
        )
        raise EventSetError(msg)

    rng = np.random.default_rng(cfg.seed)
    events: list[StochasticEvent] = []
    rate = 1.0 / (cfg.n_catalogues * cfg.catalogue_duration_years)
    serial = 0
    for catalogue in range(cfg.n_catalogues):
        drawn = rng.poisson(counts)
        for cell_index, bin_index in zip(*np.nonzero(drawn), strict=True):
            j = int(bin_index)
            if j not in keep_bins:
                continue
            lower, upper = _bin_bounds(grid, j, magnitude_max)
            n = int(drawn[cell_index, j])
            magnitudes = _sample_magnitudes(lower, upper, b_value, n, rng)
            lon0, lat0 = grid.cell_origins[int(cell_index)]
            lons = lon0 + rng.random(n) * grid.cell_size_deg
            lats = lat0 + rng.random(n) * grid.cell_size_deg
            for magnitude, lon, lat in zip(magnitudes, lons, lats, strict=True):
                if magnitude < cfg.min_magnitude:
                    continue
                events.append(
                    StochasticEvent(
                        id=f"{grid.id}-ses{catalogue:05d}-{serial:07d}",
                        catalogue=catalogue,
                        magnitude=float(magnitude),
                        longitude=float(lon),
                        latitude=float(lat),
                        depth_km=cfg.depth_km,
                        annual_rate=rate,
                    )
                )
                serial += 1
        if len(events) > cfg.max_events:
            msg = (
                f"sampling exceeded max_events ({cfg.max_events:,}) at catalogue {catalogue}; "
                "nothing is truncated silently"
            )
            raise EventSetError(msg)

    now = utc_now()
    sampling_rule = (
        f"Poisson per cell per magnitude bin on the grid's expected counts scaled by "
        f"{scaling:.6g} (from a {grid.horizon} horizon to "
        f"{cfg.catalogue_duration_years:g} year(s)); location uniform in the "
        f"{grid.cell_size_deg:g} degree cell; magnitude from a Gutenberg-Richter density with "
        f"b = {b_value:.4g} truncated to the bin; point rupture at {cfg.depth_km:g} km depth"
    )
    assumptions = [
        (
            "occurrence within a catalogue is Poisson, which reproduces an ETAS grid's expected "
            "counts exactly but understates the variance of a clustered process, so the tail of "
            "the aggregate exceedance curve is tighter than the underlying process"
        ),
        (
            f"the grid's rates are treated as constant over {cfg.catalogue_duration_years:g} "
            f"year(s), a factor of {scaling:.4g} on its own {grid.horizon} horizon. For a "
            "time-dependent (ETAS) grid this states 'if this rate persisted', which for a "
            "decaying sequence it does not: read the annual figure as a rate-equivalent, not as "
            "a statement about the coming year"
        ),
        b_note,
        (
            f"every sampled event is a POINT rupture at {cfg.depth_km:g} km depth (ADR-0025: no "
            "fault plane is manufactured from a magnitude), so distances are longer and the loss "
            "is a lower estimate than a finite rupture of the same magnitude would give"
        ),
        (
            f"events below M {cfg.min_magnitude:g} are not sampled, which makes the annual loss a "
            "lower estimate"
        ),
    ]
    if magnitude_max is None:
        assumptions.append(
            "the grid's last magnitude bin is open above and no magnitude_max was supplied, so "
            "its magnitudes are drawn from an unbounded Gutenberg-Richter tail"
        )
    return StochasticEventSet(
        id=f"ses-{grid.id}-n{cfg.n_catalogues}-d{cfg.catalogue_duration_years:g}",
        source_id=grid.id,
        events=tuple(events),
        n_catalogues=cfg.n_catalogues,
        catalogue_duration_years=cfg.catalogue_duration_years,
        min_magnitude=cfg.min_magnitude,
        seed=cfg.seed,
        provenance=Provenance(
            source="rupture.risk.event_set",
            source_url=None,
            retrieved_at=now,
            sha256=grid.parameter_snapshot_hash,
            licence="Apache-2.0 (rupture)",
            adapter_version=ADAPTER_VERSION,
            notes=(
                f"sampled from ForecastGrid {grid.id} ({grid.model_id} {grid.model_version}), "
                f"fit cutoff {grid.fit_cutoff.isoformat()}, issued {grid.issue_time.isoformat()}. "
                "No event in this set carries information the forecast did not already have."
            ),
        ),
        sampling_rule=sampling_rule,
        assumptions=tuple(assumptions),
        horizon_scaling=scaling,
        expected_events_per_catalogue=expected,
        fit_cutoff=grid.fit_cutoff.isoformat(),
    )


def _b_value(cfg: SamplingConfig, region: Region | None) -> tuple[float, str]:
    """The b-value to sample magnitudes with, and the sentence that says where it came from."""
    if cfg.b_value is not None:
        return cfg.b_value, (
            f"magnitudes within a bin follow a Gutenberg-Richter density with b = {cfg.b_value:g}, "
            "supplied by the caller"
        )
    fitted = _region_b(region)
    if fitted is not None:
        return fitted, (
            f"magnitudes within a bin follow a Gutenberg-Richter density with the region's fitted "
            f"b = {fitted:.4g} (Aki 1965 maximum likelihood, from the region's Mc estimate)"
        )
    return DEFAULT_B_VALUE, (
        f"magnitudes within a bin follow a Gutenberg-Richter density with an ASSUMED "
        f"b = {DEFAULT_B_VALUE:g}: no fitted b-value was supplied for this region"
    )


def _region_b(region: Region | None) -> float | None:
    mc = getattr(region, "mc", None) if region is not None else None
    value = getattr(mc, "b_value", None)
    return float(value) if isinstance(value, int | float) else None


def _region_max(region: Region | None) -> float | None:
    value = getattr(region, "magnitude_max", None) if region is not None else None
    return float(value) if isinstance(value, int | float) else None
