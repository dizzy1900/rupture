"""``AvoidedLossRequestV1`` in, ``AvoidedLossResponseV1`` out — for real (ADR-0021, ADR-0025).

Avoided loss is the difference between the same portfolio, under the same rupture, in the same
ground-motion realisations, with and without a measure. Reusing one ground-motion field across
every branch is the whole point: a difference computed from two independent samples would be
dominated by sampling noise rather than by the measure.

Four measures are implemented, and each says whether its effect is published or assumed:

``structural_retrofit``
    Anchoring the vulnerable components. Not a factor someone chose: HAZUS publishes *paired*
    fragility curves for anchored and unanchored components of the same facility, and the retrofit
    is modelled as the swap between them. The implied median shift is reported, not assumed.
``automated_shutdown``
    Tripping the units and closing the intake gates on a strong-motion trigger. **Assumed**: no
    published fragility pair for shut-down versus running hydropower plant was found, so the
    measure is parameterised as a stated reduction of the powerhouse component's loss ratio, and
    every figure derived from it is labelled.
``land_use_exclusion``
    Not siting the named assets in the exposed corridor. Their loss is avoided in full; nothing
    is modelled about what is built instead.
``insurance_layer``
    A simple excess-of-loss layer: the portion of each realisation's loss between an attachment
    point and a limit is ceded. This does not reduce physical damage and the response says so;
    it moves loss off the balance sheet rather than out of the world.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import numpy as np

from rupture import __version__
from rupture.adapters.groundmotion import NativeGsimEngine
from rupture.adapters.storage.zarr_store import ZarrGridStore
from rupture.adapters.vulnerability import HydropowerVulnerability, money_range
from rupture.adapters.vulnerability.hydropower import VALUE_SHARES
from rupture.domain.avoided_loss_v1 import (
    AssetLoss,
    AvoidedLossRequestV1,
    AvoidedLossResponseV1,
    HazardComponent,
    Intervention,
    InterventionKind,
    InterventionOutcome,
    ResponseStatus,
)
from rupture.domain.common import Provenance, utc_now
from rupture.domain.forecast import ForecastGrid, parse_horizon
from rupture.domain.groundmotion import GroundMotionField
from rupture.domain.hazard import ScenarioRupture
from rupture.domain.loss import ExposurePortfolio, LossType, TriggerKind
from rupture.domain.money import ConfidenceTier, ModelProvenance, MoneyRange
from rupture.domain.region import Region
from rupture.domain.vulnerability import HydropowerComponent
from rupture.ports.ground_motion import GroundMotionEngine
from rupture.risk import damage as dmg
from rupture.risk import event_based as eb
from rupture.risk import event_set as es
from rupture.risk import loss as loss_module
from rupture.risk import scenarios as scenario_module
from rupture.risk.curves import AssetLossCurve, curve_for

ADAPTER_VERSION = __version__
SHUTDOWN_DEFAULT_AVOIDED_FRACTION = 0.15
"""ASSUMED. Fraction of the powerhouse component's loss avoided by an automated shutdown."""

SHUTDOWN_ASSUMPTION = (
    "automated_shutdown is modelled as avoiding a stated fraction of the powerhouse component's "
    "loss (default 15 %). No published fragility pair for a tripped versus running hydropower "
    "unit was found; the fraction is an assumption (ADR-0025) and is a parameter of the request"
)
RETROFIT_NOTE = (
    "structural_retrofit is modelled as the swap from HAZUS's unanchored component fragility to "
    "its anchored counterpart for the same facility class, which is a published pair rather than "
    "a chosen median shift"
)
INSURANCE_NOTE = (
    "insurance_layer cedes loss between an attachment point and a limit; it changes who pays, not "
    "what breaks, and the physical damage figure is unchanged"
)
HAZARD_MESSAGE = (
    "a long-term hazard trigger asks for loss from a time-independent hazard model (F0), which "
    "needs either a classical PSHA disaggregation or an OpenQuake event_based run over a source "
    "model; rupture implements the engine-side job rendering and export parsing "
    "(rupture.adapters.groundmotion.openquake_event_based) and ships no long-term source model "
    "for the corridor, so there is nothing to run it on. A time-dependent forecast grid is "
    "answered: send trigger_kind=forecast with a ForecastGrid id"
)
FORECAST_GRID_MISSING = (
    "no ForecastGrid {trigger!r} was supplied and none was found in {store}. rupture fetches or "
    "fails: issue the forecast first (rupture forecast issue --model etas --region <r> --horizon "
    "<h> --issue <utc>) and point --forecast at its id"
)
FORECASTS_REL = "data/forecasts"
DEFAULT_ANNUAL_HORIZON = "1y"
SHUTDOWN_TRIGGER_PARAMETERS = ("trigger_g", "s_wave_km_s", "latency_s", "stopping_time_s")
OCCURRENCE_LAYER_NOTE = (
    "in the event-based path the insurance layer attaches per OCCURRENCE, not on the annual "
    "aggregate; an aggregate annual layer is a different product and would give a different "
    "answer"
)


class AvoidedLossError(ValueError):
    """The request cannot be answered as asked."""


@dataclass(frozen=True, slots=True)
class Branch:
    """One priced branch of the calculation: the baseline, or one intervention."""

    label: str
    totals: tuple[float, ...]
    by_asset: dict[str, list[float]]
    components: dict[HazardComponent, float]
    assumptions: tuple[str, ...] = ()


def respond(
    request: AvoidedLossRequestV1,
    *,
    repo_root: Path,
    ruptures: Mapping[str, ScenarioRupture] | None = None,
    engine: GroundMotionEngine | None = None,
    config: loss_module.RunConfig | None = None,
    grids: Mapping[str, ForecastGrid] | None = None,
    region: Region | None = None,
    sampling: es.SamplingConfig | None = None,
    n_gm_realisations: int = eb.DEFAULT_GM_REALISATIONS,
) -> AvoidedLossResponseV1:
    """Answer an avoided-loss request. Returns a ``not_implemented`` response, never a guess.

    A ``scenario`` trigger is priced against one rupture; a ``forecast`` trigger is priced
    against a stochastic event set sampled from the named :class:`ForecastGrid`, and its
    ``baseline_total`` is then an **expected loss per horizon window** (per year by default), not
    a per-event figure. The ``basis`` string on every money figure says which it is.
    """
    return respond_with_detail(
        request,
        repo_root=repo_root,
        ruptures=ruptures,
        engine=engine,
        config=config,
        grids=grids,
        region=region,
        sampling=sampling,
        n_gm_realisations=n_gm_realisations,
    )[0]


def respond_with_detail(
    request: AvoidedLossRequestV1,
    *,
    repo_root: Path,
    ruptures: Mapping[str, ScenarioRupture] | None = None,
    engine: GroundMotionEngine | None = None,
    config: loss_module.RunConfig | None = None,
    grids: Mapping[str, ForecastGrid] | None = None,
    region: Region | None = None,
    sampling: es.SamplingConfig | None = None,
    n_gm_realisations: int = eb.DEFAULT_GM_REALISATIONS,
) -> tuple[AvoidedLossResponseV1, eb.EventBasedLoss | None]:
    """As :func:`respond`, and also the full event-based result when there is one.

    The v1 contract has one money figure per intervention and no field for a loss exceedance
    curve, so the curve, the per-catalogue losses and the occurrence-exceedance table are
    returned alongside rather than squeezed into ``message``. The architect is asked in
    ``docs/RISK.md`` to add them to a v1.1 of the contract.
    """
    now = utc_now()
    price_year = request.portfolio.valuation_date.year
    if request.trigger_kind is TriggerKind.HAZARD:
        return (
            AvoidedLossResponseV1(
                request_id=request.request_id,
                status=ResponseStatus.NOT_IMPLEMENTED,
                computed_at=now,
                baseline_total=loss_module.stub_money(
                    request.portfolio.currency, price_year, HAZARD_MESSAGE
                ),
                provenance_kind=ModelProvenance.STUB,
                confidence=ConfidenceTier.UNQUALIFIED,
                message=HAZARD_MESSAGE,
            ),
            None,
        )
    if request.trigger_kind is TriggerKind.FORECAST:
        return _forecast_response(
            request,
            repo_root=repo_root,
            engine=engine,
            config=config,
            grids=grids,
            region=region,
            sampling=sampling,
            n_gm_realisations=n_gm_realisations,
            now=now,
        )

    catalogue = dict(ruptures) if ruptures else scenario_module.builtin(repo_root)
    rupture = catalogue.get(request.trigger_id)
    if rupture is None:
        known = ", ".join(sorted(catalogue))
        message = f"unknown scenario {request.trigger_id!r}; rupture knows {known}"
        return (
            AvoidedLossResponseV1(
                request_id=request.request_id,
                status=ResponseStatus.ERROR,
                computed_at=now,
                provenance_kind=ModelProvenance.STUB,
                message=message,
            ),
            None,
        )

    cfg = config or loss_module.RunConfig(interval_level=request.interval_level)
    eng = engine or NativeGsimEngine(strict_tectonic_region=not cfg.allow_tectonic_mismatch)
    sites = loss_module.sites_for(request.portfolio, default_vs30=cfg.default_vs30)
    gmf = loss_module.ground_motion(eng, rupture, sites, cfg)

    baseline_model = HydropowerVulnerability()
    baseline = _branch("baseline", request.portfolio, gmf, baseline_model)
    outcomes = []
    assumptions: list[str] = [
        loss_module.CASCADE_NOT_MODELLED,
        loss_module.NO_SPATIAL_CORRELATION,
    ]
    for intervention in request.interventions:
        branch = _apply(intervention, request.portfolio, gmf, baseline, rupture)
        assumptions.extend(a for a in branch.assumptions if a not in assumptions)
        outcomes.append(
            _outcome(
                intervention,
                baseline,
                branch,
                currency=request.portfolio.currency,
                price_year=price_year,
                interval_level=request.interval_level,
                loss_types=request.loss_types,
            )
        )

    basis = (
        f"scenario {rupture.id}; {gmf.gsim} {gmf.imt} via {gmf.engine.value}; "
        f"{gmf.n_realisations} realisations"
    )
    return (
        AvoidedLossResponseV1(
            request_id=request.request_id,
            status=ResponseStatus.OK,
            computed_at=now,
            baseline=_asset_losses(
                baseline,
                currency=request.portfolio.currency,
                price_year=price_year,
                interval_level=request.interval_level,
                basis=basis,
                loss_types=request.loss_types,
            ),
            baseline_total=money_range(
                list(baseline.totals),
                currency=request.portfolio.currency,
                price_year=price_year,
                basis=basis,
                interval_level=request.interval_level,
            ),
            interventions=tuple(outcomes),
            model_ids=(baseline_model.model_id, gmf.gsim, gmf.engine.value, rupture.id),
            provenance_kind=ModelProvenance.ASSUMED,
            confidence=ConfidenceTier.LOW,
            n_realisations=gmf.n_realisations,
            provenance=Provenance(
                source="rupture.risk.avoided_loss",
                source_url=None,
                retrieved_at=now,
                sha256=gmf.provenance.sha256,
                licence="Apache-2.0 (rupture)",
                adapter_version=ADAPTER_VERSION,
                notes=basis,
            ),
            assumptions=tuple(assumptions),
            message=(
                "loss figures rest on assumed component value shares and, in part, on assumed "
                "fragility functions; see docs/RISK.md and ADR-0024"
            ),
        ),
        None,
    )


# ------------------------------------------------------------------ branches
def _branch(
    label: str,
    portfolio: ExposurePortfolio,
    gmf: GroundMotionField,
    model: HydropowerVulnerability,
    *,
    excluded: frozenset[str] = frozenset(),
    powerhouse_reduction: float = 0.0,
    trigger: eb.ShutdownTrigger | None = None,
    hypocentral_km: Mapping[str, float] | None = None,
    assumptions: tuple[str, ...] = (),
) -> Branch:
    """Price one branch over the field's realisations, reusing the same ground motion.

    When ``trigger`` is given, the powerhouse reduction is applied only in the realisations and at
    the sites where the trip both fires and leaves time to act (see
    :class:`rupture.risk.event_based.ShutdownTrigger`), rather than everywhere unconditionally.
    """
    realisations = model.realisations(portfolio, gmf)
    totals: list[float] = []
    by_asset: dict[str, list[float]] = {}
    components: dict[HazardComponent, float] = {}
    distances = dict(hypocentral_km or {})
    for _, damages in realisations:
        running = 0.0
        for d in damages:
            if d.asset_id in excluded:
                value = 0.0
            elif powerhouse_reduction and _shutdown_helps(trigger, d, distances):
                saved = (
                    sum(
                        c.loss
                        for c in d.components
                        if c.name == HydropowerComponent.POWERHOUSE.value
                    )
                    * powerhouse_reduction
                )
                value = d.loss - saved
            else:
                value = d.loss
            by_asset.setdefault(d.asset_id, []).append(value)
            running += value
        totals.append(running)
    components[HazardComponent.GROUND_SHAKING] = sum(totals) / len(totals) if totals else 0.0
    for component in (
        HazardComponent.LANDSLIDE,
        HazardComponent.LIQUEFACTION,
        HazardComponent.ICE_ROCK_AVALANCHE,
    ):
        components[component] = 0.0
    return Branch(label, tuple(totals), by_asset, components, assumptions)


def _shutdown_helps(
    trigger: eb.ShutdownTrigger | None,
    damage: dmg.AssetDamage,
    distances: Mapping[str, float],
) -> bool:
    """Whether the shutdown is worth anything at this site in this realisation."""
    if trigger is None:
        return True
    distance = distances.get(damage.asset_id)
    if distance is None:
        return True
    return bool(trigger.fires(np.array([damage.intensity]), distance)[0])


def _apply(
    intervention: Intervention,
    portfolio: ExposurePortfolio,
    gmf: GroundMotionField,
    baseline: Branch,
    rupture: ScenarioRupture | None = None,
) -> Branch:
    """The portfolio's loss with one intervention in place, on the same realisations."""
    targets = frozenset(intervention.applies_to_asset_ids) or frozenset(
        a.id for a in portfolio.assets
    )
    kind = intervention.kind
    if kind is InterventionKind.STRUCTURAL_RETROFIT:
        model = HydropowerVulnerability(retrofitted_asset_ids=targets)
        return _branch(intervention.id, portfolio, gmf, model, assumptions=(RETROFIT_NOTE,))
    if kind is InterventionKind.AUTOMATED_SHUTDOWN:
        fraction = _fraction(intervention, "avoided_fraction", SHUTDOWN_DEFAULT_AVOIDED_FRACTION)
        model = HydropowerVulnerability()
        trigger = _shutdown_trigger(intervention)
        distances = _hypocentral_distances(rupture, portfolio)
        in_time = [
            asset_id
            for asset_id, distance in distances.items()
            if trigger.warning_seconds(distance) > 0.0
        ]
        reach = (
            f"the trip leaves time to act at {len(in_time)} of {len(distances)} sites for this "
            "rupture"
            if distances
            else "no rupture geometry was supplied, so the timing condition was not evaluated"
        )
        return _branch(
            intervention.id,
            portfolio,
            gmf,
            model,
            excluded=frozenset(),
            powerhouse_reduction=fraction,
            trigger=trigger if distances else None,
            hypocentral_km=distances,
            assumptions=(
                f"{SHUTDOWN_ASSUMPTION}; this run used {fraction:.0%}, applied to "
                f"{VALUE_SHARES[HydropowerComponent.POWERHOUSE]:.0%} of each plant's value",
                f"{trigger.describe()}; {reach}",
            ),
        )
    if kind is InterventionKind.LAND_USE_EXCLUSION:
        model = HydropowerVulnerability()
        return _branch(
            intervention.id,
            portfolio,
            gmf,
            model,
            excluded=targets,
            assumptions=(
                "land_use_exclusion removes the named assets from the exposure entirely; nothing "
                "is modelled about what replaces them or where",
            ),
        )
    if kind is InterventionKind.INSURANCE_LAYER:
        attachment = _amount(intervention, "attachment")
        limit = _amount(intervention, "limit")
        retained = tuple(
            total - min(max(total - attachment, 0.0), limit) for total in baseline.totals
        )
        return Branch(
            intervention.id,
            retained,
            {k: list(v) for k, v in baseline.by_asset.items()},
            dict(baseline.components),
            (f"{INSURANCE_NOTE}; attachment {attachment:,.0f}, limit {limit:,.0f}",),
        )
    msg = (
        f"intervention kind {kind.value!r} is not implemented for a seismic portfolio request; "
        "the warning and evacuation kinds are serac's, not rupture's"
    )
    raise AvoidedLossError(msg)


def _hypocentral_distances(
    rupture: ScenarioRupture | None, portfolio: ExposurePortfolio
) -> dict[str, float]:
    """Hypocentre-to-site distance for every asset, km. Empty when there is no rupture."""
    if rupture is None:
        return {}
    return {
        asset.id: eb.hypocentral_km(
            rupture.hypocentre_longitude,
            rupture.hypocentre_latitude,
            rupture.hypocentre_depth_km,
            asset.longitude,
            asset.latitude,
        )
        for asset in portfolio.assets
    }


def _fraction(intervention: Intervention, name: str, default: float) -> float:
    raw = intervention.parameters.get(name, default)
    if not isinstance(raw, int | float):
        msg = f"{intervention.id}: parameter {name!r} must be a number"
        raise AvoidedLossError(msg)
    value = float(raw)
    if not 0.0 <= value <= 1.0:
        msg = f"{intervention.id}: {name} must be in [0, 1], got {value}"
        raise AvoidedLossError(msg)
    return value


def _amount(intervention: Intervention, name: str) -> float:
    raw = intervention.parameters.get(name)
    if not isinstance(raw, int | float):
        msg = f"{intervention.id}: an insurance layer needs a numeric {name!r} parameter"
        raise AvoidedLossError(msg)
    value = float(raw)
    if value < 0.0:
        msg = f"{intervention.id}: {name} must not be negative"
        raise AvoidedLossError(msg)
    return value


# ------------------------------------------------------------------ assembly
def _asset_losses(
    branch: Branch,
    *,
    currency: str,
    price_year: int,
    interval_level: float,
    basis: str,
    loss_types: tuple[LossType, ...],
) -> tuple[AssetLoss, ...]:
    loss_type = loss_types[0] if loss_types else LossType.STRUCTURAL
    out = []
    for asset_id, values in sorted(branch.by_asset.items()):
        mean = sum(values) / len(values)
        out.append(
            AssetLoss(
                asset_id=asset_id,
                loss_type=loss_type,
                expected_loss=money_range(
                    values,
                    currency=currency,
                    price_year=price_year,
                    basis=basis,
                    interval_level=interval_level,
                ),
                by_component={
                    HazardComponent.GROUND_SHAKING: mean,
                    HazardComponent.LANDSLIDE: 0.0,
                    HazardComponent.LIQUEFACTION: 0.0,
                    HazardComponent.ICE_ROCK_AVALANCHE: 0.0,
                },
            )
        )
    return tuple(out)


def _outcome(
    intervention: Intervention,
    baseline: Branch,
    branch: Branch,
    *,
    currency: str,
    price_year: int,
    interval_level: float,
    loss_types: tuple[LossType, ...],
) -> InterventionOutcome:
    avoided = [b - a for b, a in zip(baseline.totals, branch.totals, strict=True)]
    basis = f"{intervention.kind.value} on {len(baseline.totals)} shared realisations"
    return InterventionOutcome(
        intervention_id=intervention.id,
        expected_loss=money_range(
            list(branch.totals),
            currency=currency,
            price_year=price_year,
            basis=basis,
            interval_level=interval_level,
        ),
        avoided_vs_baseline=_avoided_money(
            avoided,
            currency=currency,
            price_year=price_year,
            basis=f"baseline minus {intervention.kind.value}, realisation by realisation",
            interval_level=interval_level,
        ),
        by_asset=_asset_losses(
            branch,
            currency=currency,
            price_year=price_year,
            interval_level=interval_level,
            basis=basis,
            loss_types=loss_types,
        ),
        assumptions=(*intervention.assumptions, *branch.assumptions),
    )


def _avoided_money(
    values: list[float],
    *,
    currency: str,
    price_year: int,
    basis: str,
    interval_level: float,
) -> MoneyRange:
    """Avoided loss cannot be negative in any implemented measure; a negative is a bug, not news."""
    if any(v < -1e-6 for v in values):
        msg = "an intervention increased the loss, which no implemented measure can do"
        raise AvoidedLossError(msg)
    return money_range(
        [max(v, 0.0) for v in values],
        currency=currency,
        price_year=price_year,
        basis=basis,
        interval_level=interval_level,
    )


# ------------------------------------------------------------------ forecast trigger
def load_forecast_grid(
    trigger_id: str, *, repo_root: Path, grids: Mapping[str, ForecastGrid] | None = None
) -> ForecastGrid:
    """The named grid, from the caller's mapping or from ``data/forecasts/``. Fetch or fail."""
    if grids is not None and trigger_id in grids:
        return grids[trigger_id]
    store_root = repo_root / FORECASTS_REL
    if store_root.is_dir():
        try:
            return ZarrGridStore(store_root).load(trigger_id)
        except (KeyError, FileNotFoundError, ValueError):
            pass
    raise AvoidedLossError(FORECAST_GRID_MISSING.format(trigger=trigger_id, store=store_root))


def _catalogue_duration_years(horizon: str | None) -> tuple[float, str]:
    """The window an event-based figure is reported over, and how to name it."""
    text = horizon or DEFAULT_ANNUAL_HORIZON
    years = es.horizon_years(parse_horizon(text))
    return years, text


def branches_for(
    interventions: tuple[Intervention, ...],
    portfolio: ExposurePortfolio,
    model: HydropowerVulnerability,
) -> list[eb.BranchSpec]:
    """Translate each intervention into an event-based branch priced on the same ground motion."""
    baseline_curves = _curves(portfolio, model)
    out: list[eb.BranchSpec] = []
    for intervention in interventions:
        targets = frozenset(intervention.applies_to_asset_ids) or frozenset(
            a.id for a in portfolio.assets
        )
        kind = intervention.kind
        if kind is InterventionKind.STRUCTURAL_RETROFIT:
            out.append(
                eb.BranchSpec(
                    label=intervention.id,
                    curves=_curves(
                        portfolio, HydropowerVulnerability(retrofitted_asset_ids=targets)
                    ),
                    assumptions=(RETROFIT_NOTE,),
                )
            )
        elif kind is InterventionKind.AUTOMATED_SHUTDOWN:
            fraction = _fraction(
                intervention, "avoided_fraction", SHUTDOWN_DEFAULT_AVOIDED_FRACTION
            )
            trigger = _shutdown_trigger(intervention)
            out.append(
                eb.BranchSpec(
                    label=intervention.id,
                    curves=baseline_curves,
                    component_reduction=(HydropowerComponent.POWERHOUSE.value, fraction),
                    trigger=trigger,
                    assumptions=(
                        f"{SHUTDOWN_ASSUMPTION}; this run used {fraction:.0%}, applied to "
                        f"{VALUE_SHARES[HydropowerComponent.POWERHOUSE]:.0%} of each plant's value",
                        trigger.describe(),
                    ),
                )
            )
        elif kind is InterventionKind.LAND_USE_EXCLUSION:
            out.append(
                eb.BranchSpec(
                    label=intervention.id,
                    curves=baseline_curves,
                    excluded=targets,
                    assumptions=(
                        "land_use_exclusion removes the named assets from the exposure entirely; "
                        "nothing is modelled about what replaces them or where",
                    ),
                )
            )
        elif kind is InterventionKind.INSURANCE_LAYER:
            attachment = _amount(intervention, "attachment")
            limit = _amount(intervention, "limit")
            out.append(
                eb.BranchSpec(
                    label=intervention.id,
                    curves=baseline_curves,
                    layer=(attachment, limit),
                    assumptions=(
                        f"{INSURANCE_NOTE}; attachment {attachment:,.0f}, limit {limit:,.0f}",
                        OCCURRENCE_LAYER_NOTE,
                    ),
                )
            )
        else:
            msg = (
                f"intervention kind {kind.value!r} is not implemented for a seismic portfolio "
                "request; the warning and evacuation kinds are serac's, not rupture's"
            )
            raise AvoidedLossError(msg)
    return out


def _curves(
    portfolio: ExposurePortfolio, model: HydropowerVulnerability
) -> dict[str, AssetLossCurve]:
    coverage = model.coverage(portfolio)
    modelled = set(coverage.modelled)
    out: dict[str, AssetLossCurve] = {}
    for asset in portfolio.assets:
        if asset.id not in modelled:
            continue
        curve = curve_for(asset, model.components_for(asset))
        if curve is not None:
            out[asset.id] = curve
    return out


def _shutdown_trigger(intervention: Intervention) -> eb.ShutdownTrigger:
    """Build the shutdown trigger from the request's parameters, with the stated defaults."""
    defaults = eb.ShutdownTrigger()
    values: dict[str, float] = {
        "threshold_g": defaults.threshold_g,
        "s_wave_km_s": defaults.s_wave_km_s,
        "latency_s": defaults.latency_s,
        "stopping_time_s": defaults.stopping_time_s,
    }
    mapping = {
        "trigger_g": "threshold_g",
        "s_wave_km_s": "s_wave_km_s",
        "latency_s": "latency_s",
        "stopping_time_s": "stopping_time_s",
    }
    for name, attribute in mapping.items():
        raw = intervention.parameters.get(name)
        if raw is None:
            continue
        if not isinstance(raw, int | float) or float(raw) <= 0.0:
            msg = f"{intervention.id}: parameter {name!r} must be a positive number"
            raise AvoidedLossError(msg)
        values[attribute] = float(raw)
    return eb.ShutdownTrigger(**values)


def _forecast_response(
    request: AvoidedLossRequestV1,
    *,
    repo_root: Path,
    engine: GroundMotionEngine | None,
    config: loss_module.RunConfig | None,
    grids: Mapping[str, ForecastGrid] | None,
    region: Region | None,
    sampling: es.SamplingConfig | None,
    n_gm_realisations: int,
    now: datetime,
) -> tuple[AvoidedLossResponseV1, eb.EventBasedLoss | None]:
    """Price a forecast trigger through a stochastic event set and an event-based calculation."""
    price_year = request.portfolio.valuation_date.year
    try:
        grid = load_forecast_grid(request.trigger_id, repo_root=repo_root, grids=grids)
    except AvoidedLossError as exc:
        return (
            AvoidedLossResponseV1(
                request_id=request.request_id,
                status=ResponseStatus.ERROR,
                computed_at=now,
                provenance_kind=ModelProvenance.STUB,
                message=str(exc),
            ),
            None,
        )

    duration_years, horizon_text = _catalogue_duration_years(request.horizon)
    cfg = config or loss_module.RunConfig(interval_level=request.interval_level)
    sampling_cfg = sampling or es.SamplingConfig(
        catalogue_duration_years=duration_years, seed=cfg.seed
    )
    if sampling_cfg.catalogue_duration_years != duration_years:
        sampling_cfg = replace(sampling_cfg, catalogue_duration_years=duration_years)
    event_set = es.sample_from_forecast_grid(grid, config=sampling_cfg, region=region)

    model = HydropowerVulnerability()
    result = eb.run_event_based(
        request.portfolio,
        event_set,
        engine=engine,
        vulnerability=model,
        config=cfg,
        branches=branches_for(request.interventions, request.portfolio, model),
        n_gm_realisations=n_gm_realisations,
        interval_level=request.interval_level,
    )

    window = "year" if abs(duration_years - 1.0) < 1e-9 else horizon_text
    basis = (
        f"expected loss per {window} from a stochastic event set of "
        f"{event_set.n_catalogues} synthetic catalogue(s) sampled from ForecastGrid {grid.id}"
    )
    outcomes = []
    for branch in result.branches:
        avoided = eb.avoided_annual_loss(
            result.baseline,
            branch,
            currency=request.portfolio.currency,
            price_year=price_year,
            interval_level=request.interval_level,
            seed=cfg.seed,
            basis=f"baseline minus {branch.label}, catalogue by catalogue; {basis}",
        )
        note = avoided.note()
        outcomes.append(
            InterventionOutcome(
                intervention_id=branch.label,
                expected_loss=branch.annual_expected_loss,
                avoided_vs_baseline=avoided.money,
                by_asset=branch.asset_losses(),
                assumptions=(
                    *_intervention_assumptions(request, branch.label),
                    *branch.assumptions,
                    *((note,) if note else ()),
                ),
            )
        )
    exceedance = "; ".join(
        f"{p.return_period_years:,.0f} yr: {p.loss:,.0f}"
        for p in result.baseline.aggregate_exceedance
    )
    return (
        AvoidedLossResponseV1(
            request_id=request.request_id,
            status=ResponseStatus.OK,
            computed_at=now,
            baseline=result.baseline.asset_losses(),
            baseline_total=result.baseline.annual_expected_loss,
            interventions=tuple(outcomes),
            model_ids=result.model_ids,
            provenance_kind=ModelProvenance.ASSUMED,
            confidence=ConfidenceTier.LOW,
            n_realisations=result.n_events * result.n_gm_realisations,
            provenance=Provenance(
                source="rupture.risk.event_based",
                source_url=None,
                retrieved_at=now,
                sha256=event_set.provenance.sha256,
                licence="Apache-2.0 (rupture)",
                adapter_version=ADAPTER_VERSION,
                notes=f"{basis}; {event_set.provenance.notes}",
            ),
            assumptions=result.assumptions,
            message=(
                f"expected loss per {window}, not per event. Aggregate exceedance (annual total "
                f"loss by return period, resolvable to "
                f"{result.resolvable_return_period_years:,.0f} years): {exceedance}. "
                "The v1 contract has no field for a loss exceedance curve; "
                "rupture.risk.avoided_loss.respond_with_detail returns the full curve."
            ),
        ),
        result,
    )


def _intervention_assumptions(request: AvoidedLossRequestV1, label: str) -> tuple[str, ...]:
    for intervention in request.interventions:
        if intervention.id == label:
            return intervention.assumptions
    return ()
