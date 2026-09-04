"""Expected **annual** loss and loss exceedance curves from a stochastic event set (ADR-0042).

A scenario answers "what does this rupture cost?". An underwriter prices against a different
question: "what does a year cost, and how bad is the bad year?". That needs every event that
could happen in a year, each with the rate it occurs at — a stochastic event set
(:mod:`rupture.risk.event_set`) — and the same exposure, ground-motion and vulnerability chain
the scenario path uses, run once per event.

What comes out:

``annual_expected_loss``
    The AAL: ``sum over events of rate * E[loss]``, where the expectation is over the GSIM's
    aleatory realisations. Its interval is a **percentile bootstrap on that mean over the
    synthetic catalogue-years**, i.e. how well the event set pins the number down. It is *not*
    the spread of annual loss, which is a far wider and differently shaped thing; that is what
    the exceedance curves are for, and the ``basis`` string on the figure says so.

``aggregate_exceedance`` (AEP)
    Rate at which the **total loss in a year** exceeds a level, from the catalogue-year totals.

``occurrence_exceedance`` (OEP)
    Rate at which a **single event** causes a loss exceeding a level, from every
    (event, realisation) pair weighted by its rate.

Both curves are reported only out to the return period the event set can resolve
(``n_catalogues * catalogue_duration_years``); a longer return period is left out rather than
extrapolated.

Every branch — baseline and each intervention — is priced on the **same** per-event
ground-motion realisations, in the same order, and the catalogue aggregation draws the **same**
realisation index for every branch. That is ADR-0025's shared-realisation rule carried into the
event-based path: a difference between two independent samples would be sampling noise, not a
measurement.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from rupture.adapters.groundmotion import NativeGsimEngine
from rupture.adapters.vulnerability import HydropowerVulnerability
from rupture.adapters.vulnerability.hydropower import VALUE_SHARE_ASSUMPTION
from rupture.domain.avoided_loss_v1 import AssetLoss, HazardComponent
from rupture.domain.groundmotion import Site
from rupture.domain.loss import ExposurePortfolio, LossType
from rupture.domain.money import ConfidenceTier, ModelProvenance, MoneyRange
from rupture.ports.ground_motion import GroundMotionEngine
from rupture.risk import loss as loss_module
from rupture.risk.curves import AssetLossCurve, curve_for
from rupture.risk.event_set import StochasticEvent, StochasticEventSet

FloatArray = npt.NDArray[np.float64]

DEFAULT_GM_REALISATIONS = 40
"""Aleatory GSIM realisations per sampled event.

The AAL is a mean over these, so it converges quickly; the exceedance curves need the tail, and
the resolvable tail is set by the number of catalogue-years, not by this number.
"""

RETURN_PERIODS_YEARS: tuple[float, ...] = (2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0, 1000.0)

BOOTSTRAP_REPLICATES = 2000

AAL_BASIS_NOTE = (
    "expected annual loss (AAL) = sum over sampled events of occurrence rate x expected loss; "
    "the interval is a percentile bootstrap of that mean over the synthetic catalogue-years, so "
    "it is the sampling uncertainty of the estimate, NOT the spread of annual loss. The spread "
    "of annual loss is the aggregate exceedance curve"
)


class EventBasedError(ValueError):
    """The event-based calculation cannot be made."""


@dataclass(frozen=True, slots=True)
class ExceedancePoint:
    """One point of a loss exceedance curve."""

    return_period_years: float
    annual_exceedance_rate: float
    exceedance_probability_1y: float
    loss: float


@dataclass(frozen=True, slots=True)
class BranchSpec:
    """One priced variant of the portfolio, evaluated on the same ground motion as the others.

    ``curves`` already carries whatever the measure changes about a fragility (the retrofit swaps
    HAZUS's unanchored curves for its anchored ones); ``excluded`` removes assets entirely;
    ``component_reduction`` scales one named component's loss, and when
    ``trigger`` is set it applies only where the trigger fires.
    """

    label: str
    curves: Mapping[str, AssetLossCurve]
    excluded: frozenset[str] = frozenset()
    component_reduction: tuple[str, float] | None = None
    trigger: ShutdownTrigger | None = None
    layer: tuple[float, float] | None = None
    """``(attachment, limit)`` of a per-occurrence excess-of-loss layer, ceded off the total.

    Applied per *event*, which is what a catastrophe excess-of-loss layer normally attaches on;
    an aggregate annual layer would attach on the year total and is a different product. The
    response says which.
    """
    assumptions: tuple[str, ...] = ()

    def asset_losses(
        self,
        intensities: FloatArray,
        columns: Mapping[str, int],
        distances_km: Mapping[str, float],
    ) -> dict[str, FloatArray]:
        """Loss per asset, shape ``(n_realisations,)`` each, for one event's ground-motion field."""
        out: dict[str, FloatArray] = {}
        for asset_id, curve in self.curves.items():
            if asset_id in self.excluded:
                out[asset_id] = np.zeros(intensities.shape[0], dtype=np.float64)
                continue
            im = intensities[:, columns[asset_id]]
            components = curve.component_losses(im)
            if self.component_reduction is not None:
                name, fraction = self.component_reduction
                if name in components:
                    if self.trigger is None:
                        components[name] = components[name] * (1.0 - fraction)
                    else:
                        fires = self.trigger.fires(im, distances_km[asset_id])
                        components[name] = components[name] * np.where(fires, 1.0 - fraction, 1.0)
            out[asset_id] = np.sum(np.stack(list(components.values())), axis=0)
        return out


@dataclass(frozen=True, slots=True)
class ShutdownTrigger:
    """When an on-site strong-motion trip actually gets there first.

    An automated shutdown is worth something at a site only if the trip fires *and* the units are
    off before the damaging shaking arrives. Two conditions, both evaluated per site per
    realisation:

    * **the trip fires** — the realised ground motion at the site exceeds ``threshold_g``;
    * **there is time** — the S-wave travel time from the hypocentre to the site, minus the
      stated detection-plus-dissemination latency and the machinery's own stopping time, is
      positive.

    Every parameter here is ASSUMED and is a request parameter; none is a published figure. The
    S-wave speed is a standard crustal value; the latency and stopping time are stated defaults a
    consumer is expected to replace with their own plant's numbers.
    """

    threshold_g: float = 0.05
    s_wave_km_s: float = 3.5
    latency_s: float = 5.0
    stopping_time_s: float = 10.0

    @property
    def required_seconds(self) -> float:
        return self.latency_s + self.stopping_time_s

    def warning_seconds(self, hypocentral_distance_km: float) -> float:
        """Seconds between the trip being actionable and the S wave arriving. May be negative."""
        return hypocentral_distance_km / self.s_wave_km_s - self.required_seconds

    def fires(
        self, intensities: FloatArray, hypocentral_distance_km: float
    ) -> npt.NDArray[np.bool_]:
        """Boolean per realisation: the trip fired and there was time to act on it."""
        in_time = self.warning_seconds(hypocentral_distance_km) > 0.0
        fired: npt.NDArray[np.bool_] = intensities >= self.threshold_g
        return fired & in_time

    def describe(self) -> str:
        return (
            f"ASSUMED shutdown trigger: fires at {self.threshold_g:g} g and needs "
            f"{self.required_seconds:g} s (detection and dissemination {self.latency_s:g} s plus "
            f"{self.stopping_time_s:g} s to stop the machine) before the S wave arrives at "
            f"{self.s_wave_km_s:g} km/s. None of these four numbers is a published figure"
        )


@dataclass(frozen=True, slots=True)
class BranchResult:
    """One branch's annual loss, its exceedance curves and its per-asset decomposition."""

    label: str
    annual_expected_loss: MoneyRange
    per_asset_annual: dict[str, MoneyRange]
    per_catalogue_annual: tuple[float, ...]
    """Each synthetic catalogue's own annualised expected loss.

    This is what an avoided-loss difference is taken over: the branches share the catalogues and
    the ground-motion realisations, so the difference is the measure and not sampling noise.
    """
    catalogue_year_losses: tuple[float, ...]
    aggregate_exceedance: tuple[ExceedancePoint, ...]
    occurrence_exceedance: tuple[ExceedancePoint, ...]
    assumptions: tuple[str, ...] = ()

    def asset_losses(self) -> tuple[AssetLoss, ...]:
        """The per-asset annual figures in the contract's ``AssetLoss`` shape."""
        return tuple(
            AssetLoss(
                asset_id=asset_id,
                loss_type=LossType.STRUCTURAL,
                expected_loss=money,
                by_component={
                    HazardComponent.GROUND_SHAKING: money.best or 0.0,
                    HazardComponent.LANDSLIDE: 0.0,
                    HazardComponent.LIQUEFACTION: 0.0,
                    HazardComponent.ICE_ROCK_AVALANCHE: 0.0,
                },
            )
            for asset_id, money in sorted(self.per_asset_annual.items())
        )


@dataclass(frozen=True, slots=True)
class EventBasedLoss:
    """The answer of an event-based run, baseline plus every branch."""

    portfolio_id: str
    event_set_id: str
    source_id: str
    gsim: str
    imt: str
    engine_id: str
    n_events: int
    n_catalogues: int
    catalogue_duration_years: float
    n_gm_realisations: int
    resolvable_return_period_years: float
    baseline: BranchResult
    branches: tuple[BranchResult, ...] = ()
    modelled_asset_ids: tuple[str, ...] = ()
    unmodelled: tuple[tuple[str, str], ...] = ()
    assumed_share: float = 0.0
    assumptions: tuple[str, ...] = ()
    model_ids: tuple[str, ...] = ()
    zero_loss_year_fraction: float = 0.0

    def annual_expected_loss_money(self) -> MoneyRange:
        """The headline figure: the baseline branch's expected annual loss."""
        return self.baseline.annual_expected_loss

    def branch(self, label: str) -> BranchResult:
        for result in self.branches:
            if result.label == label:
                return result
        msg = f"no branch {label!r}; this run priced {[b.label for b in self.branches]}"
        raise EventBasedError(msg)

    def lines(self) -> list[str]:
        aal = self.baseline.annual_expected_loss
        out = [
            f"portfolio: {self.portfolio_id}",
            f"event set: {self.event_set_id} from {self.source_id}",
            (
                f"{self.n_events} events over {self.n_catalogues} catalogue-year(s) of "
                f"{self.catalogue_duration_years:g} yr, {self.n_gm_realisations} ground-motion "
                f"realisations each ({self.gsim} {self.imt}, {self.engine_id})"
            ),
            (
                f"expected annual loss: {aal.best:,.0f} {aal.currency} "
                f"[{aal.low:,.0f}, {aal.high:,.0f}] "
                f"({aal.provenance.value}, {aal.confidence.value})"
            ),
            f"years with no modelled loss: {self.zero_loss_year_fraction:.1%}",
            (
                "aggregate exceedance (annual total), resolvable to a "
                f"{self.resolvable_return_period_years:,.0f}-year return period:"
            ),
        ]
        out.extend(
            f"  {p.return_period_years:>6,.0f} yr   {p.loss:>16,.0f}"
            for p in self.baseline.aggregate_exceedance
        )
        if self.branches:
            out.append("avoided annual loss by intervention:")
            base = self.baseline.annual_expected_loss.best or 0.0
            for result in self.branches:
                best = result.annual_expected_loss.best or 0.0
                out.append(f"  {result.label:24s} {base - best:>16,.0f}")
        out.extend(f"not modelled: {a} ({why})" for a, why in self.unmodelled)
        out.extend(f"assumption: {a}" for a in self.assumptions)
        return out


# --------------------------------------------------------------------- the calculation
def run_event_based(
    portfolio: ExposurePortfolio,
    event_set: StochasticEventSet,
    *,
    engine: GroundMotionEngine | None = None,
    vulnerability: HydropowerVulnerability | None = None,
    config: loss_module.RunConfig | None = None,
    branches: Sequence[BranchSpec] = (),
    n_gm_realisations: int = DEFAULT_GM_REALISATIONS,
    interval_level: float = 0.9,
    return_periods_years: tuple[float, ...] = RETURN_PERIODS_YEARS,
) -> EventBasedLoss:
    """Price ``portfolio`` against every event of ``event_set`` and reduce to annual figures."""
    cfg = config or loss_module.RunConfig()
    eng = engine or NativeGsimEngine(strict_tectonic_region=not cfg.allow_tectonic_mismatch)
    model = vulnerability or HydropowerVulnerability()
    coverage = model.coverage(portfolio)
    if not coverage.modelled:
        msg = "no asset in the portfolio has a damage model and a replacement value"
        raise EventBasedError(msg)

    modelled = [a for a in portfolio.assets if a.id in set(coverage.modelled)]
    baseline_curves = {
        a.id: curve
        for a in modelled
        if (curve := curve_for(a, model.components_for(a))) is not None
    }
    sites = tuple(
        Site(
            id=a.id,
            longitude=a.longitude,
            latitude=a.latitude,
            vs30=_vs30(a.attributes.get("vs30"), cfg.default_vs30),
        )
        for a in modelled
    )
    columns = {site.id: index for index, site in enumerate(sites)}
    all_branches = [
        BranchSpec(label="baseline", curves=baseline_curves),
        *branches,
    ]

    n_events = len(event_set.events)
    labels = [b.label for b in all_branches]
    event_mean: dict[str, FloatArray] = {k: np.zeros(n_events) for k in labels}
    event_samples: dict[str, list[FloatArray]] = {k: [] for k in labels}
    asset_mean: dict[str, dict[str, FloatArray]] = {
        k: {a: np.zeros(n_events) for a in baseline_curves} for k in labels
    }
    assumed_running = 0.0
    total_running = 0.0

    for index, event in enumerate(event_set.events):
        rupture = event.rupture()
        gmf = loss_module.ground_motion(
            eng,
            rupture,
            sites,
            cfg,
            n_realisations=n_gm_realisations,
            seed=None if cfg.seed is None else cfg.seed + index,
        )
        intensities = gmf.array()
        distances = {
            site.id: _hypocentral_km(event, site.longitude, site.latitude) for site in sites
        }
        for spec in all_branches:
            per_asset = spec.asset_losses(intensities, columns, distances)
            total = np.sum(np.stack(list(per_asset.values())), axis=0)
            if spec.layer is not None:
                attachment, limit = spec.layer
                ceded = np.clip(total - attachment, 0.0, limit)
                scale = np.divide(total - ceded, total, out=np.ones_like(total), where=total > 0.0)
                per_asset = {k: v * scale for k, v in per_asset.items()}
                total = total - ceded
            event_mean[spec.label][index] = float(total.mean())
            event_samples[spec.label].append(total)
            for asset_id, values in per_asset.items():
                asset_mean[spec.label][asset_id][index] = float(values.mean())
        for asset_id, curve in baseline_curves.items():
            components = curve.component_losses(intensities[:, columns[asset_id]])
            assumed_names = set(curve.assumed_component_names)
            assumed_running += (
                float(sum(v.mean() for name, v in components.items() if name in assumed_names))
                * event.annual_rate
            )
            total_running += float(sum(v.mean() for v in components.values())) * event.annual_rate

    rng = np.random.default_rng(None if cfg.seed is None else cfg.seed + 7_919)
    pick = rng.integers(0, n_gm_realisations, size=n_events) if n_events else np.zeros(0, dtype=int)
    catalogue_of = np.array([e.catalogue for e in event_set.events], dtype=np.int64)
    rates = np.array([e.annual_rate for e in event_set.events], dtype=np.float64)
    duration = event_set.catalogue_duration_years
    resolvable = event_set.n_catalogues * duration

    price_year = portfolio.valuation_date.year
    results: list[BranchResult] = []
    for spec in all_branches:
        results.append(
            _branch_result(
                spec,
                event_mean=event_mean[spec.label],
                event_samples=event_samples[spec.label],
                asset_mean=asset_mean[spec.label],
                pick=pick,
                catalogue_of=catalogue_of,
                rates=rates,
                event_set=event_set,
                currency=portfolio.currency,
                price_year=price_year,
                interval_level=interval_level,
                return_periods_years=return_periods_years,
                seed=cfg.seed,
                gsim=(
                    cfg.gsim
                    if cfg.gsim_logic_tree is None
                    else f"logic-tree:{cfg.gsim_logic_tree.id}"
                ),
                imt=cfg.imt,
                n_gm_realisations=n_gm_realisations,
            )
        )

    baseline_result = results[0]
    zero_years = (
        float(np.mean(np.asarray(baseline_result.catalogue_year_losses) <= 0.0))
        if baseline_result.catalogue_year_losses
        else 1.0
    )
    return EventBasedLoss(
        portfolio_id=portfolio.id,
        event_set_id=event_set.id,
        source_id=event_set.source_id,
        gsim=(cfg.gsim if cfg.gsim_logic_tree is None else f"logic-tree:{cfg.gsim_logic_tree.id}"),
        imt=cfg.imt,
        engine_id=str(eng.engine_id),
        n_events=n_events,
        n_catalogues=event_set.n_catalogues,
        catalogue_duration_years=duration,
        n_gm_realisations=n_gm_realisations,
        resolvable_return_period_years=resolvable,
        baseline=baseline_result,
        branches=tuple(results[1:]),
        modelled_asset_ids=coverage.modelled,
        unmodelled=coverage.unmodelled,
        assumed_share=(assumed_running / total_running) if total_running > 0.0 else 0.0,
        assumptions=(
            *event_set.assumptions,
            VALUE_SHARE_ASSUMPTION,
            loss_module.CASCADE_NOT_MODELLED,
            loss_module.NO_SPATIAL_CORRELATION,
            AAL_BASIS_NOTE,
            (
                f"the event set resolves return periods out to {resolvable:,.0f} years; nothing "
                "longer is reported, and no exceedance level is extrapolated"
            ),
        ),
        model_ids=(
            model.model_id,
            cfg.gsim if cfg.gsim_logic_tree is None else cfg.gsim_logic_tree.id,
            str(eng.engine_id),
            event_set.id,
        ),
        zero_loss_year_fraction=zero_years,
    )


def _branch_result(
    spec: BranchSpec,
    *,
    event_mean: FloatArray,
    event_samples: list[FloatArray],
    asset_mean: dict[str, FloatArray],
    pick: npt.NDArray[np.int64],
    catalogue_of: npt.NDArray[np.int64],
    rates: FloatArray,
    event_set: StochasticEventSet,
    currency: str,
    price_year: int,
    interval_level: float,
    return_periods_years: tuple[float, ...],
    seed: int | None,
    gsim: str,
    imt: str,
    n_gm_realisations: int,
) -> BranchResult:
    duration = event_set.catalogue_duration_years
    n_catalogues = event_set.n_catalogues

    per_catalogue_mean = np.zeros(n_catalogues, dtype=np.float64)
    np.add.at(per_catalogue_mean, catalogue_of, event_mean)
    per_catalogue_mean /= duration

    year_losses = np.zeros(n_catalogues, dtype=np.float64)
    if len(event_samples):
        sampled = np.array(
            [values[pick[i]] for i, values in enumerate(event_samples)], dtype=np.float64
        )
        np.add.at(year_losses, catalogue_of, sampled)
    year_losses /= duration

    basis = (
        f"{gsim} {imt}, {len(event_mean)} sampled events x {n_gm_realisations} realisations over "
        f"{n_catalogues} catalogue(s) of {duration:g} year(s) from {event_set.source_id}; "
        f"{AAL_BASIS_NOTE}"
    )
    aal = _bootstrap_money(
        per_catalogue_mean,
        currency=currency,
        price_year=price_year,
        basis=basis,
        interval_level=interval_level,
        seed=seed,
    )
    per_asset = {
        asset_id: _bootstrap_money(
            _per_catalogue(values, catalogue_of, n_catalogues) / duration,
            currency=currency,
            price_year=price_year,
            basis=basis,
            interval_level=interval_level,
            seed=seed,
        )
        for asset_id, values in asset_mean.items()
    }
    return BranchResult(
        label=spec.label,
        annual_expected_loss=aal,
        per_asset_annual=per_asset,
        per_catalogue_annual=tuple(float(v) for v in per_catalogue_mean),
        catalogue_year_losses=tuple(float(v) for v in year_losses),
        aggregate_exceedance=aggregate_exceedance(
            year_losses, duration=duration, return_periods_years=return_periods_years
        ),
        occurrence_exceedance=occurrence_exceedance(
            event_samples,
            rates,
            return_periods_years=return_periods_years,
            resolvable_return_period_years=n_catalogues * duration,
        ),
        assumptions=spec.assumptions,
    )


def _per_catalogue(
    values: FloatArray, catalogue_of: npt.NDArray[np.int64], n_catalogues: int
) -> FloatArray:
    out = np.zeros(n_catalogues, dtype=np.float64)
    np.add.at(out, catalogue_of, values)
    return out


def _bootstrap_money(
    per_catalogue: FloatArray,
    *,
    currency: str,
    price_year: int,
    basis: str,
    interval_level: float,
    seed: int | None,
) -> MoneyRange:
    """AAL with a percentile-bootstrap interval on the mean over catalogue-years."""
    best = float(per_catalogue.mean()) if per_catalogue.size else 0.0
    if per_catalogue.size < 2:
        return MoneyRange(
            low=max(best, 0.0),
            high=max(best, 0.0),
            best=max(best, 0.0),
            currency=currency,
            price_year=price_year,
            basis=basis + "; a single catalogue, so the interval has zero width",
            confidence=ConfidenceTier.LOW,
            provenance=ModelProvenance.ASSUMED,
        )
    rng = np.random.default_rng(None if seed is None else seed + 104_729)
    draws = rng.integers(0, per_catalogue.size, size=(BOOTSTRAP_REPLICATES, per_catalogue.size))
    means = per_catalogue[draws].mean(axis=1)
    tail = (1.0 - interval_level) / 2.0
    low = float(np.quantile(means, tail))
    high = float(np.quantile(means, 1.0 - tail))
    return MoneyRange(
        low=max(min(low, best), 0.0),
        high=max(high, best, 0.0),
        best=max(best, 0.0),
        currency=currency,
        price_year=price_year,
        basis=basis,
        confidence=ConfidenceTier.LOW,
        provenance=ModelProvenance.ASSUMED,
    )


def aggregate_exceedance(
    year_losses: FloatArray, *, duration: float, return_periods_years: tuple[float, ...]
) -> tuple[ExceedancePoint, ...]:
    """AEP: the annual total loss at each resolvable return period."""
    if year_losses.size == 0:
        return ()
    resolvable = year_losses.size * duration
    ordered = np.sort(year_losses)
    out: list[ExceedancePoint] = []
    for period in return_periods_years:
        if period > resolvable or period <= 0.0:
            continue
        rate = 1.0 / period
        quantile = 1.0 - rate * duration
        if not 0.0 <= quantile <= 1.0:
            continue
        out.append(
            ExceedancePoint(
                return_period_years=period,
                annual_exceedance_rate=rate,
                exceedance_probability_1y=1.0 - math.exp(-rate),
                loss=float(np.quantile(ordered, quantile)),
            )
        )
    return tuple(out)


def occurrence_exceedance(
    event_samples: Sequence[FloatArray],
    rates: FloatArray,
    *,
    return_periods_years: tuple[float, ...],
    resolvable_return_period_years: float,
) -> tuple[ExceedancePoint, ...]:
    """OEP: the single-event loss whose exceedance rate matches each return period.

    Capped at the same return period the aggregate curve is capped at. The rarest exceedance rate
    an event set can resolve is the rate one of its events carries, which is exactly
    ``1 / (n_catalogues * duration)``; anything longer would be read off the single most damaging
    sample and is not reported.
    """
    if not len(event_samples):
        return ()
    losses = np.concatenate([np.asarray(v, dtype=np.float64) for v in event_samples])
    weights = np.repeat(rates / len(event_samples[0]), [len(v) for v in event_samples])
    order = np.argsort(losses)[::-1]
    losses = losses[order]
    cumulative = np.cumsum(weights[order])
    out: list[ExceedancePoint] = []
    for period in return_periods_years:
        if period <= 0.0 or period > resolvable_return_period_years:
            continue
        target = 1.0 / period
        if target > cumulative[-1]:
            continue
        index = int(np.searchsorted(cumulative, target, side="left"))
        index = min(index, losses.size - 1)
        out.append(
            ExceedancePoint(
                return_period_years=period,
                annual_exceedance_rate=target,
                exceedance_probability_1y=1.0 - math.exp(-target),
                loss=float(losses[index]),
            )
        )
    return tuple(out)


def _vs30(raw: object, default: float) -> float:
    return float(raw) if isinstance(raw, int | float) else default


def hypocentral_km(
    source_longitude: float,
    source_latitude: float,
    depth_km: float,
    longitude: float,
    latitude: float,
) -> float:
    """Great-circle epicentral distance combined with depth. Plain trigonometry, no adapter."""
    earth_km = 6371.0
    lat1, lat2 = math.radians(source_latitude), math.radians(latitude)
    dlat = lat2 - lat1
    dlon = math.radians(longitude - source_longitude)
    a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
    epicentral = 2.0 * earth_km * math.asin(min(1.0, math.sqrt(a)))
    return math.hypot(epicentral, depth_km)


def _hypocentral_km(event: StochasticEvent, longitude: float, latitude: float) -> float:
    return hypocentral_km(event.longitude, event.latitude, event.depth_km, longitude, latitude)


@dataclass(frozen=True, slots=True)
class AvoidedAnnual:
    """Annual loss avoided by one branch, and how often the measure did not help."""

    money: MoneyRange
    negative_catalogue_fraction: float
    """Share of synthetic catalogues in which the measure left the portfolio slightly worse off."""
    worst_negative: float
    """The largest such shortfall, in the portfolio currency per year. Zero when there is none."""

    def note(self) -> str | None:
        """The sentence a response must carry when the measure is not beneficial everywhere."""
        if self.negative_catalogue_fraction <= 0.0:
            return None
        return (
            f"this measure left the portfolio worse off in "
            f"{self.negative_catalogue_fraction:.1%} of the synthetic catalogues, by at most "
            f"{self.worst_negative:,.0f} per year. That is a real property of the published "
            "fragility pair, not a defect: HAZUS's anchored generation-facility curve for plants "
            "under 100 MW is fractionally worse than its unanchored counterpart between about "
            "0.006 g and 0.051 g, so a year containing only very small events does not benefit. "
            "MoneyRange cannot express a negative figure, so the reported interval is truncated "
            "at zero and this note carries what the truncation hid"
        )


def avoided_annual_loss(
    baseline: BranchResult,
    branch: BranchResult,
    *,
    currency: str,
    price_year: int,
    interval_level: float,
    seed: int | None,
    basis: str,
) -> AvoidedAnnual:
    """Annual loss avoided by ``branch``, taken catalogue by catalogue against ``baseline``.

    The two branches were priced on the same events and the same ground-motion realisations
    (ADR-0025), so the difference is the measure rather than sampling noise.

    A **negative** difference in an individual catalogue is not treated as a bug. It happens, and
    for a documented reason: a published anchored/unanchored fragility pair can cross at low
    intensity, so a synthetic year containing only very small events can come out fractionally
    worse with the retrofit in place. What is refused is a negative *expected* annual figure,
    because that is a measure that does not work and the contract's ``MoneyRange`` cannot state
    it; the caller gets an error rather than a zero.
    """
    base = np.asarray(baseline.per_catalogue_annual, dtype=np.float64)
    other = np.asarray(branch.per_catalogue_annual, dtype=np.float64)
    if base.shape != other.shape:
        msg = "branches were priced over different catalogues; the difference is not a measurement"
        raise EventBasedError(msg)
    difference = base - other
    mean = float(difference.mean()) if difference.size else 0.0
    if mean < 0.0:
        msg = (
            f"branch {branch.label!r} raises the expected annual loss by {-mean:,.0f} "
            f"{currency}/yr. rupture will not report that as an avoided loss of zero"
        )
        raise EventBasedError(msg)
    negative = difference < 0.0
    return AvoidedAnnual(
        money=_bootstrap_money(
            difference,
            currency=currency,
            price_year=price_year,
            basis=basis,
            interval_level=interval_level,
            seed=seed,
        ),
        negative_catalogue_fraction=float(negative.mean()) if difference.size else 0.0,
        worst_negative=float(-difference.min()) if negative.any() else 0.0,
    )
