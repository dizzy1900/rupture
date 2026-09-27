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

**The day-one under-forecast, and the switch that addresses it.** Step 2 is honest about what it
has: one hour after the mainshock the zone's catalogue is a decade of background seismicity plus a
handful of aftershocks, and the fit says so. Measured against the closed windows in
``reports/aftershock/``, that under-forecasts the first day by 3-12x. :class:`RateModel` makes the
alternative reachable and the choice explicit: ``ETAS_RJ_GENERIC`` keeps the ETAS grid's shape but
takes its *level* from the generic Reasenberg-Jones prior of
:mod:`rupture.services.aftershock.generic`, updated toward the sequence as events arrive. The
default is ``ETAS``, unchanged, so the committed reports regenerate. What the switch is worth on
the two committed sequences is measured, window for window, by
:mod:`rupture.services.aftershock.generic_validation` -- including the two windows where it is
worse.

everything here is a rate and a probability.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

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
    snapshot_hash,
    utc_now,
)
from rupture.services.aftershock.generic import (
    GENERIC_RJ,
    GENERIC_SOURCE,
    SECONDS_PER_DAY,
    APosterior,
    GenericRJParameters,
    generic_for_region,
    generic_prior,
    sequence_observation,
    update,
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


class RateModel(StrEnum):
    """Which model sets the *level* of the forecast. The default is the one already published.

    ``ETAS``
        The zone's own ETAS fit decides everything: where, how big, and how many. This is what
        ``reports/aftershock/`` and ``reports/MODEL_CARD_aftershock.md`` describe, and it is what
        a default-constructed forecaster still does, so those reports regenerate unchanged.

    ``ETAS_RJ_GENERIC``
        ETAS still decides *where* and *how big* -- the grid's spatial pattern and its
        magnitude-bin shape are untouched -- and the generic Reasenberg-Jones prior, updated
        toward the sequence (:mod:`rupture.services.aftershock.generic`), decides *how many*: the
        whole grid is multiplied by the single scalar that makes its mass at or above the region's
        target threshold equal the R-J posterior-mean count for the same window. The two products
        therefore stay consistent with each other, and the rung probabilities are still read off
        the grid.

        This is a hybrid, and the seam is real: ETAS's magnitude shape uses the region's published
        b, while the R-J count that sets the level was computed with the generic table's b. The
        rescale matches them at the target threshold only. It is offered because it measurably
        reduces the day-one under-forecast on both committed sequences and does not pretend to be
        a single coherent likelihood.
    """

    ETAS = "etas"
    ETAS_RJ_GENERIC = "etas-rj-generic"


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


RESCALED_MODEL_SUFFIX = "+rj-generic"
"""Appended to the source model id so a rescaled grid never reads as the model it came from."""


def rescaled_to_total(
    grid: ForecastGrid, *, target: float, above: float, note: str
) -> ForecastGrid:
    """``grid`` multiplied by the scalar that makes its mass at or above ``above`` equal ``target``.

    Only the level moves: every cell and every magnitude bin is multiplied by the same number, so
    the spatial pattern and the magnitude shape the ETAS simulation produced survive intact. The
    grid's id gains a suffix, because a rescaled grid is a different forecast and must not be
    fetchable under the id of the one it was derived from.

    A grid with no mass at or above ``above`` cannot be rescaled -- there is nothing to scale -- and
    that is raised rather than silently turned into a flat or zero forecast.

    **The result's provenance describes what it is, not what it came from.** A rescaled grid is a
    composite: ETAS supplied the spatial pattern and the magnitude shape, a Reasenberg-Jones rate
    supplied the level. Returning it with ETAS's ``model_id`` and ETAS's ``parameter_snapshot_hash``
    would put a forecast nobody fitted under a label somebody did -- and that hash is what
    ``pipelines/schedule.py`` compares to prove no parameter changed mid-schedule, so the lie would
    be load-bearing. The id, the model id and the snapshot hash all move, and the rebuilt grid goes
    through ``ForecastGrid`` validation rather than ``model_copy``, which skips it.
    """
    edges = np.asarray(grid.magnitude_bin_edges, dtype=np.float64)
    current = float(grid.counts().sum(axis=0)[edges >= above - 1e-9].sum())
    if current <= 0.0:
        msg = (
            f"grid {grid.id} carries no expected mass at or above M{above}; it cannot be rescaled "
            "to a target count"
        )
        raise ValueError(msg)
    factor = target / current
    scaled = tuple(tuple(float(v * factor) for v in row) for row in grid.expected_counts)
    model_id = f"{grid.model_id}{RESCALED_MODEL_SUFFIX}"
    snapshot = snapshot_hash(
        {
            "source_parameter_snapshot_hash": grid.parameter_snapshot_hash,
            "source_model_id": grid.model_id,
            "rescale_factor": factor,
            "rescale_above": above,
            "rescale_target": target,
        }
    )
    return ForecastGrid(
        **{
            **grid.model_dump(),
            "id": ForecastGrid.make_id(model_id, grid.region_id, grid.issue_time, grid.horizon),
            "model_id": model_id,
            "parameter_snapshot_hash": snapshot,
            "expected_counts": scaled,
            "notes": f"{grid.notes or ''}; rescaled x{factor:.4g} at M>={above}: {note}".lstrip(
                "; "
            ),
        }
    )


@dataclass(frozen=True, slots=True)
class Issuance:
    """One issued forecast with the grid it summarises and the fit it came from.

    ``posterior`` is the generic-prior posterior over the Reasenberg-Jones productivity that set
    the level, and is ``None`` for the plain ETAS rate model -- which is the honest way to say
    that no generic information entered that forecast at all.
    """

    forecast: AftershockForecast
    grid: ForecastGrid
    fit: FitResult
    region: Region
    posterior: APosterior | None = None


@dataclass(frozen=True)
class AftershockForecaster:
    """Configuration for fitting and issuing aftershock forecasts.

    ``auxiliary_years`` is the ETAS auxiliary window at the start of the zone catalogue (events
    there act as triggering sources only). ``n_simulations`` is the number of stochastic
    continuations averaged for the triggered component; ``seed`` makes a forecast reproducible.

    ``rate_model`` chooses what sets the level of the forecast (:class:`RateModel`) and defaults
    to ``ETAS``, the behaviour the committed reports describe. ``generic_regime`` overrides the
    tectonic regime that would otherwise be read off the region, for a zone whose setting the
    coarse ``TectonicSetting`` gets wrong; ``generic_likelihood_start`` drops the first part of the
    sequence from the Bayesian likelihood, which is the only lever here against short-term
    aftershock incompleteness and is off by default.
    """

    auxiliary_years: float = 2.0
    n_simulations: int = 100
    seed: int | None = 20150425
    max_iterations: int = 200
    max_seconds: float = 900.0
    cell_size_deg: float | None = None
    ladder_offsets: tuple[float, ...] = DEFAULT_LADDER_OFFSETS
    fix_b_value: bool = True
    rate_model: RateModel = RateModel.ETAS
    generic_regime: str | None = None
    generic_likelihood_start: timedelta = timedelta(0)

    # ------------------------------------------------------------------ generic prior
    def posterior_for(
        self, *, history: Catalog, region: Region, mainshock: Mainshock, issue_time: datetime
    ) -> APosterior:
        """The generic-prior posterior over the R-J productivity given the sequence so far.

        The likelihood counts events at or above the zone's Mc, the lowest threshold at which the
        catalogue is claimed complete; with no Mc on the region it falls back to the target
        threshold, which counts fewer events and so leans further on the prior.
        """
        parameters = (
            generic_for_region(region)
            if self.generic_regime is None
            else _generic_named(self.generic_regime)
        )
        floor = region.mc.mc if region.mc is not None else region.target_min_magnitude
        prior = generic_prior(parameters, mainshock_magnitude=mainshock.magnitude)
        observation = sequence_observation(
            history,
            mainshock=mainshock,
            issue_time=issue_time,
            min_magnitude=floor,
            start_offset=self.generic_likelihood_start,
        )
        return update(prior, observation)

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
        posterior: APosterior | None = None
        generic_note = ""
        if self.rate_model is RateModel.ETAS_RJ_GENERIC:
            posterior = self.posterior_for(
                history=history, region=region, mainshock=mainshock, issue_time=issue_time
            )
            t1 = (issue_time - mainshock.origin_time).total_seconds() / SECONDS_PER_DAY
            t2 = t1 + horizon.total_seconds() / SECONDS_PER_DAY
            target = posterior.expected_count(
                min_magnitude=region.target_min_magnitude, t1_days=t1, t2_days=t2
            )
            generic_note = (
                f"level from generic R-J regime {posterior.parameters.regime} "
                f"(a_mean {posterior.parameters.a_mean}, sigma_a "
                f"{posterior.parameters.a_sigma_for(mainshock.magnitude):.3f}, "
                f"p {posterior.parameters.p_value}, c {posterior.parameters.c_value_days} d, "
                f"b {posterior.b_value:.3f}) updated on "
                f"{posterior.observation.n_events if posterior.observation else 0} sequence "
                f"events; {GENERIC_SOURCE}"
            )
            grid = rescaled_to_total(
                grid, target=target, above=region.target_min_magnitude, note=generic_note
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
            model_id=(
                model.model_id
                if self.rate_model is RateModel.ETAS
                else f"{model.model_id}+{self.rate_model.value}"
            ),
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
                + (f"; {generic_note}" if generic_note else "")
            ),
        )
        return Issuance(forecast=forecast, grid=grid, fit=fit, region=region, posterior=posterior)

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


def _generic_named(regime: str) -> GenericRJParameters:
    """Look a regime up in the generic table, listing the known ones when it is not there."""
    try:
        return GENERIC_RJ[regime]
    except KeyError:
        msg = f"unknown generic regime {regime!r}; known: {', '.join(sorted(GENERIC_RJ))}"
        raise KeyError(msg) from None


def _slug(text: str) -> str:
    """Lower-case, hyphen-safe form for a region/forecast id."""
    out = "".join(c if c.isalnum() else "-" for c in text.lower()).strip("-")
    return out or "unknown"
