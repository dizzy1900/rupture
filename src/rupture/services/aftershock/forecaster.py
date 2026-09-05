"""Issue an :class:`~rupture.domain.AftershockForecast` for a mainshock sequence.

What this does, in order:

1. Build the aftershock zone (:mod:`rupture.services.aftershock.window`) and turn it into a
   :class:`~rupture.domain.Region` that inherits the published Mc, target threshold, depth range
   and binning of the parent region.
2. Fit the ETAS baseline (:class:`~rupture.adapters.forecasting.etas_mizrahi.MizrahiETAS`; rupture
   writes no second ETAS) on everything in that zone with ``origin_time < fit_cutoff``: the
   pre-mainshock seismicity, which supplies the auxiliary window and the background rate, plus
   the sequence so far. The cutoff moves with the refit schedule below, so the parameters start
   as the zone's long-run parameters and become sequence-specific as the sequence accumulates
   target events.
3. Issue a :class:`~rupture.domain.ForecastGrid` for ``[issue_time, issue_time + horizon)`` from
   that fit, conditioned on the history up to ``issue_time``.
4. Summarise the grid as probabilities of at least one event above a ladder of magnitudes.

**The Gutenberg-Richter b-value is fixed, not fitted.** ``beta`` is pinned to the published
long-run b of the parent region (``Region.mc.b_value``, fitted by the catalogue build over
decades). A b estimated on the sequence itself is biased low by short-term aftershock
incompleteness -- the minutes-to-days after a large mainshock are missing small events, which
flattens the observed frequency-magnitude distribution -- and a low b inflates the large-magnitude
tail. Fitting b freely here made the 2023 Kahramanmaras fit at +1 d supercritical (branching ratio
1.07 with b = 0.76), which is not a usable model: its stochastic continuations do not terminate.
With b fixed at the region's published value every fit in ``docs/AFTERSHOCK.md`` is sub-critical.
Simulated magnitudes are additionally capped at ``Region.magnitude_max``.

**The Poisson assumption.** The grid holds *expected counts*. The probability of at least one
event of magnitude at least ``m`` in the window is computed as ``P = 1 - exp(-lambda)``, where
``lambda`` is the expected count above ``m`` summed over every cell. That is exact only if events
above ``m`` in the window are a Poisson process. They are not: ETAS is a clustering process, so
the real count is over-dispersed relative to Poisson and ``1 - exp(-lambda)`` **over-states** the
probability of at least one event whenever ``lambda`` is not small (it puts all of the extra
variance into more mass at zero than the formula allows). At small ``lambda`` the two agree to
first order. The number is reported as computed, with the assumption named, in
``docs/AFTERSHOCK.md``, ``reports/MODEL_CARD_aftershock.md`` and in the ``notes`` of every
forecast this module issues.

everything here is a rate and a probability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.adapters.forecasting.leakage import assert_all_before
from rupture.domain import (
    AftershockForecast,
    Catalog,
    FitResult,
    ForecastGrid,
    MagnitudeProbability,
    Region,
    format_horizon,
    utc_now,
)
from rupture.services.aftershock.sequences import Mainshock
from rupture.services.aftershock.window import (
    ZONE_MULTIPLIER,
    aftershock_zone_radius_km,
    sequence_catalog,
    sequence_region,
)

POISSON_NOTE = (
    "P = 1 - exp(-lambda) assumes events above the threshold in the window are Poisson; ETAS "
    "clusters, so this over-states P(at least one) when lambda is not small"
)

REFIT_SCHEDULE: tuple[timedelta, ...] = (
    timedelta(hours=1),
    timedelta(hours=3),
    timedelta(hours=6),
    timedelta(hours=12),
    *(timedelta(days=d) for d in range(1, 31)),
)
"""Elapsed times at which an operating service refits: +1, 3, 6, 12 h, then daily to +30 d.

Before the first scheduled refit the service uses a fit cut at the mainshock time, i.e. purely
pre-mainshock parameters for the zone. This is the usual operational shape -- generic parameters
first, sequence-specific parameters as the sequence accumulates events -- reached here by moving
the ETAS cutoff rather than by a second model.
"""

DEFAULT_LADDER_OFFSETS: tuple[float, ...] = (-3.0, -2.0, -1.0, 0.0)
DEFAULT_HORIZONS: tuple[timedelta, ...] = (
    timedelta(days=1),
    timedelta(days=7),
    timedelta(days=30),
)


def scheduled_fit_cutoff(mainshock_time: datetime, issue_time: datetime) -> datetime:
    """The cutoff of the fit a service following :data:`REFIT_SCHEDULE` holds at ``issue_time``."""
    if issue_time < mainshock_time:
        msg = "issue_time cannot precede the mainshock"
        raise ValueError(msg)
    elapsed = issue_time - mainshock_time
    best = timedelta(0)
    for offset in REFIT_SCHEDULE:
        if offset <= elapsed:
            best = offset
    return mainshock_time + best


def magnitude_ladder(
    mainshock_magnitude: float,
    *,
    floor: float,
    bin_width: float,
    offsets: tuple[float, ...] = DEFAULT_LADDER_OFFSETS,
) -> tuple[float, ...]:
    """Thresholds ``M + offset`` snapped to the magnitude-bin edges and clipped at ``floor``.

    A rung below the region's target threshold is dropped rather than extrapolated: the grid
    carries no mass there, so a probability for it would be made up.
    """
    out: list[float] = []
    for offset in offsets:
        raw = mainshock_magnitude + offset
        steps = round((raw - floor) / bin_width)
        snapped = round(floor + steps * bin_width, 6)
        if snapped < floor - 1e-9:
            continue
        if snapped not in out:
            out.append(snapped)
    return tuple(sorted(out))


def probabilities_from_grid(
    grid: ForecastGrid, thresholds: tuple[float, ...]
) -> tuple[MagnitudeProbability, ...]:
    """Expected count above each threshold over the whole grid, and ``1 - exp(-lambda)``."""
    if not thresholds:
        msg = "at least one magnitude threshold is required"
        raise ValueError(msg)
    edges = np.asarray(grid.magnitude_bin_edges, dtype=np.float64)
    per_bin = grid.counts().sum(axis=0)
    out: list[MagnitudeProbability] = []
    for threshold in sorted(thresholds):
        if threshold < edges[0] - 1e-9:
            msg = (
                f"threshold {threshold} is below the grid's first magnitude bin {edges[0]}; "
                "the grid carries no mass there"
            )
            raise ValueError(msg)
        lam = float(per_bin[edges >= threshold - 1e-9].sum())
        if not math.isfinite(lam) or lam < 0.0:  # pragma: no cover - grid validator forbids it
            msg = f"expected count above {threshold} is not finite and non-negative: {lam}"
            raise ValueError(msg)
        out.append(
            MagnitudeProbability(
                magnitude=threshold,
                probability=-math.expm1(-lam),
                expected_count=lam,
            )
        )
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Issuance:
    """One issued forecast with the grid it summarises and the fit it came from."""

    forecast: AftershockForecast
    grid: ForecastGrid
    fit: FitResult
    region: Region


@dataclass(frozen=True)
class AftershockForecaster:
    """Configuration for fitting and issuing aftershock forecasts.

    ``auxiliary_years`` is the ETAS auxiliary window at the start of the zone catalogue (events
    there act as triggering sources only). ``n_simulations`` is the number of stochastic
    continuations averaged for the triggered component; ``seed`` makes a forecast reproducible.
    """

    auxiliary_years: float = 2.0
    n_simulations: int = 100
    seed: int | None = 20150425
    max_iterations: int = 200
    max_seconds: float = 900.0
    cell_size_deg: float | None = None
    ladder_offsets: tuple[float, ...] = DEFAULT_LADDER_OFFSETS
    fix_b_value: bool = True

    # ------------------------------------------------------------------ model
    def model_for(self, region: Region) -> MizrahiETAS:
        """A configured :class:`MizrahiETAS` for ``region``.

        ``beta`` is pinned to the region's published long-run b (see the module docstring) when
        one is available and ``fix_b_value`` is set; otherwise it is estimated, which the caller
        can detect from ``FitResult.diagnostics['beta_fixed']``.
        """
        b_value = region.mc.b_value if region.mc is not None else None
        fixed_beta = b_value * math.log(10.0) if (self.fix_b_value and b_value) else None
        return MizrahiETAS(
            auxiliary_years=self.auxiliary_years,
            fixed_beta=fixed_beta,
            m_max=region.magnitude_max,
            max_iterations=self.max_iterations,
            max_seconds=self.max_seconds,
        )

    # ------------------------------------------------------------------ zone
    def zone(self, mainshock: Mainshock, parent: Region) -> Region:
        """The aftershock-zone region for ``mainshock``."""
        radius = aftershock_zone_radius_km(mainshock.magnitude)
        region = sequence_region(
            parent,
            region_id=f"aftershock-{_slug(mainshock.event_id)}",
            name=f"{mainshock.event_id} M{mainshock.magnitude:.1f} aftershock zone",
            latitude=mainshock.latitude,
            longitude=mainshock.longitude,
            radius_km=radius,
        )
        if self.cell_size_deg is not None:
            region = region.model_copy(update={"cell_size_deg": self.cell_size_deg})
        return region

    # ------------------------------------------------------------------ fit
    def fit(self, catalog: Catalog, region: Region, cutoff: datetime) -> FitResult:
        """Fit ETAS on the zone catalogue before ``cutoff`` (leakage asserted by the adapter)."""
        return self.model_for(region).fit(catalog, region, cutoff)

    def refit_for(
        self, catalog: Catalog, region: Region, mainshock: Mainshock, issue_time: datetime
    ) -> FitResult:
        """The fit a service following :data:`REFIT_SCHEDULE` would hold at ``issue_time``."""
        return self.fit(catalog, region, scheduled_fit_cutoff(mainshock.origin_time, issue_time))

    # ------------------------------------------------------------------ issue
    def issue(
        self,
        *,
        history: Catalog,
        region: Region,
        mainshock: Mainshock,
        fit: FitResult,
        issue_time: datetime,
        horizon: timedelta,
        n_simulations: int | None = None,
        seed: int | None = None,
    ) -> Issuance:
        """Issue a forecast from an existing fit and a history that must already be truncated.

        ``history`` is **not** filtered here. It is asserted: every event must have
        ``origin_time < issue_time`` or the call raises
        :class:`~rupture.adapters.forecasting.leakage.LeakageError`. Use
        :meth:`forecast` for the ordinary path, which truncates and then calls this.
        """
        assert_all_before(history, issue_time, what="aftershock forecast history")
        if issue_time < mainshock.origin_time:
            msg = "issue_time cannot precede the mainshock"
            raise ValueError(msg)
        model = self.model_for(region)
        model.load_fit(fit, region)
        usable = history.earthquakes().at_least(fit.mc)
        grid = model.forecast(
            usable,
            issue_time,
            horizon,
            n_simulations=self.n_simulations if n_simulations is None else n_simulations,
            seed=self.seed if seed is None else seed,
        )
        thresholds = magnitude_ladder(
            mainshock.magnitude,
            floor=region.target_min_magnitude,
            bin_width=region.magnitude_bin_width,
            offsets=self.ladder_offsets,
        )
        probabilities = probabilities_from_grid(grid, thresholds)
        sequence = sequence_catalog(
            usable,
            mainshock_time=mainshock.origin_time,
            latitude=mainshock.latitude,
            longitude=mainshock.longitude,
            radius_km=aftershock_zone_radius_km(mainshock.magnitude),
        )
        elapsed = issue_time - mainshock.origin_time
        forecast = AftershockForecast(
            id=(
                f"aftershock-{_slug(mainshock.event_id)}-{issue_time:%Y%m%dT%H%M%SZ}-"
                f"{format_horizon(horizon)}"
            ),
            mainshock_event_id=mainshock.event_id,
            mainshock_time=mainshock.origin_time,
            mainshock_magnitude=mainshock.magnitude,
            region_id=region.id,
            issue_time=issue_time,
            horizon=horizon,
            elapsed=elapsed,
            model_id=model.model_id,
            model_version=model.model_version,
            parameter_snapshot_hash=fit.parameter_snapshot_hash,
            n_sequence_events=len(sequence),
            probabilities=probabilities,
            forecast_grid_id=grid.id,
            created_at=utc_now(),
            notes=(
                f"zone radius {aftershock_zone_radius_km(mainshock.magnitude):.0f} km "
                f"(Wells & Coppersmith 1994 rupture length x {ZONE_MULTIPLIER}); "
                f"fit cutoff {fit.fit_cutoff.isoformat()}, mc={fit.mc}, "
                f"n_training={fit.n_events}; {POISSON_NOTE}"
            ),
        )
        return Issuance(forecast=forecast, grid=grid, fit=fit, region=region)

    def forecast(
        self,
        *,
        catalog: Catalog,
        parent_region: Region,
        mainshock: Mainshock,
        issue_time: datetime,
        horizon: timedelta,
        fit: FitResult | None = None,
        n_simulations: int | None = None,
        seed: int | None = None,
    ) -> Issuance:
        """Full path: build the zone, refit on the schedule if needed, truncate, issue."""
        region = self.zone(mainshock, parent_region)
        if fit is None:
            fit = self.refit_for(catalog, region, mainshock, issue_time)
        return self.issue(
            history=catalog.before(issue_time),
            region=region,
            mainshock=mainshock,
            fit=fit,
            issue_time=issue_time,
            horizon=horizon,
            n_simulations=n_simulations,
            seed=seed,
        )


def _slug(text: str) -> str:
    """Lower-case, hyphen-safe form for a region/forecast id."""
    out = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    return out or "unknown"
