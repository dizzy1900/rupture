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
from dataclasses import dataclass
from pathlib import Path

from rupture import __version__
from rupture.adapters.groundmotion import NativeGsimEngine
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
from rupture.domain.groundmotion import GroundMotionField
from rupture.domain.hazard import ScenarioRupture
from rupture.domain.loss import ExposurePortfolio, LossType, TriggerKind
from rupture.domain.money import ConfidenceTier, ModelProvenance, MoneyRange
from rupture.domain.vulnerability import HydropowerComponent
from rupture.ports.ground_motion import GroundMotionEngine
from rupture.risk import loss as loss_module
from rupture.risk import scenarios as scenario_module

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
FORECAST_MESSAGE = (
    "a forecast trigger needs an event-set loss calculation over a ForecastGrid, which C2 does "
    "not implement: rupture.risk.scenarios.from_stochastic_event is the hook, and the event sets "
    "come from the forecasting layer"
)
HAZARD_MESSAGE = (
    "a long-term hazard trigger needs a classical PSHA loss calculation, which runs through the "
    "OpenQuake engine and is not implemented in C2"
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
) -> AvoidedLossResponseV1:
    """Answer an avoided-loss request. Returns a ``not_implemented`` response, never a guess."""
    now = utc_now()
    price_year = request.portfolio.valuation_date.year
    if request.trigger_kind is not TriggerKind.SCENARIO:
        message = (
            FORECAST_MESSAGE if request.trigger_kind is TriggerKind.FORECAST else HAZARD_MESSAGE
        )
        return AvoidedLossResponseV1(
            request_id=request.request_id,
            status=ResponseStatus.NOT_IMPLEMENTED,
            computed_at=now,
            baseline_total=loss_module.stub_money(request.portfolio.currency, price_year, message),
            provenance_kind=ModelProvenance.STUB,
            confidence=ConfidenceTier.UNQUALIFIED,
            message=message,
        )

    catalogue = dict(ruptures) if ruptures else scenario_module.builtin(repo_root)
    rupture = catalogue.get(request.trigger_id)
    if rupture is None:
        known = ", ".join(sorted(catalogue))
        message = f"unknown scenario {request.trigger_id!r}; rupture knows {known}"
        return AvoidedLossResponseV1(
            request_id=request.request_id,
            status=ResponseStatus.ERROR,
            computed_at=now,
            provenance_kind=ModelProvenance.STUB,
            message=message,
        )

    cfg = config or loss_module.RunConfig(interval_level=request.interval_level)
    eng = engine or NativeGsimEngine(strict_tectonic_region=not cfg.allow_tectonic_mismatch)
    sites = loss_module.sites_for(request.portfolio, default_vs30=cfg.default_vs30)
    gmf = eng.scenario(
        rupture,
        sites,
        imt=cfg.imt,
        gsim=cfg.gsim,
        n_realisations=cfg.n_realisations,
        truncation_level=cfg.truncation_level,
        seed=cfg.seed,
    )

    baseline_model = HydropowerVulnerability()
    baseline = _branch("baseline", request.portfolio, gmf, baseline_model)
    outcomes = []
    assumptions: list[str] = [
        loss_module.CASCADE_NOT_MODELLED,
        loss_module.NO_SPATIAL_CORRELATION,
    ]
    for intervention in request.interventions:
        branch = _apply(intervention, request.portfolio, gmf, baseline)
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
    return AvoidedLossResponseV1(
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
    assumptions: tuple[str, ...] = (),
) -> Branch:
    """Price one branch over the field's realisations, reusing the same ground motion."""
    realisations = model.realisations(portfolio, gmf)
    totals: list[float] = []
    by_asset: dict[str, list[float]] = {}
    components: dict[HazardComponent, float] = {}
    for _, damages in realisations:
        running = 0.0
        for d in damages:
            if d.asset_id in excluded:
                value = 0.0
            elif powerhouse_reduction:
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


def _apply(
    intervention: Intervention,
    portfolio: ExposurePortfolio,
    gmf: GroundMotionField,
    baseline: Branch,
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
        branch = _branch(
            intervention.id,
            portfolio,
            gmf,
            model,
            excluded=frozenset(),
            powerhouse_reduction=fraction,
            assumptions=(
                f"{SHUTDOWN_ASSUMPTION}; this run used {fraction:.0%}, applied to "
                f"{VALUE_SHARES[HydropowerComponent.POWERHOUSE]:.0%} of each plant's value",
            ),
        )
        return branch
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
