"""Portfolio loss for a scenario: the orchestration between exposure, ground motion and damage.

One run is: build the sites from the portfolio, ask a ``GroundMotionEngine`` for a field, evaluate
every asset in every realisation, and aggregate to a :class:`MoneyRange` whose interval is the
spread across realisations rather than a number someone chose.

Three things this module refuses to hide:

* **assets it could not model.** They are counted and named, never dropped silently.
* **the share of the loss that rests on an assumption.** ADR-0024's assumed intake and penstock
  fragilities and the assumed component value shares carry real money; the result reports how
  much.
* **the cascade contribution.** ``by_component`` always carries ``landslide``, ``liquefaction``
  and ``ice_rock_avalanche`` as an explicit ``0.0`` with a note saying they are not modelled, so a
  reader cannot mistake "not modelled" for "modelled and small". That is the C3 seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from types import EllipsisType

from rupture.adapters.groundmotion import NativeGsimEngine
from rupture.adapters.vulnerability import HydropowerVulnerability, money_range
from rupture.adapters.vulnerability.hydropower import VALUE_SHARE_ASSUMPTION
from rupture.domain.avoided_loss_v1 import AssetLoss, HazardComponent
from rupture.domain.groundmotion import GroundMotionField, GsimLogicTree, Site
from rupture.domain.hazard import ScenarioRupture
from rupture.domain.loss import ExposurePortfolio, LossType, TriggerKind
from rupture.domain.money import ConfidenceTier, ModelProvenance, MoneyRange
from rupture.ports.ground_motion import GroundMotionEngine, LogicTreeGroundMotionEngine
from rupture.risk import damage as dmg

DEFAULT_VS30 = 760.0
DEFAULT_GSIM = "BooreEtAl2014"
DEFAULT_IMT = "PGA"
DEFAULT_REALISATIONS = 500
DEFAULT_TRUNCATION = 3.0

CASCADE_NOT_MODELLED = (
    "cascade components (landslide, liquefaction, ice-rock avalanche) are reported as zero because "
    "they are not modelled here, not because they are small; they are delivered by C3"
)
NO_SPATIAL_CORRELATION = (
    "intra-event residuals are drawn independently per site (no spatial correlation model), which "
    "narrows the portfolio interval relative to a correlated field"
)


class LossError(ValueError):
    """The run cannot be made."""


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Everything about a run that is a choice rather than data."""

    gsim: str = DEFAULT_GSIM
    imt: str = DEFAULT_IMT
    n_realisations: int = DEFAULT_REALISATIONS
    truncation_level: float = DEFAULT_TRUNCATION
    seed: int | None = 20260903
    interval_level: float = 0.9
    default_vs30: float = DEFAULT_VS30
    allow_tectonic_mismatch: bool = False
    gsim_logic_tree: GsimLogicTree | None = None
    """When set, every field is a weighted mixture over the tree's branches, not one GSIM.

    ``gsim`` is then ignored for the calculation and the resulting field's own ``gsim`` field
    names the tree. ``docs/RISK.md`` and ADR-0037 record what the shipped tree does and does not
    represent.
    """


@dataclass(frozen=True, slots=True)
class PortfolioLoss:
    """The answer, with everything a reader needs to judge it."""

    portfolio_id: str
    trigger_kind: TriggerKind
    trigger_id: str
    field: GroundMotionField
    """The ground-motion field the loss came from."""
    total: MoneyRange
    by_asset: tuple[AssetLoss, ...]
    realisation_totals: tuple[float, ...]
    modelled_asset_ids: tuple[str, ...]
    unmodelled: tuple[tuple[str, str], ...]
    assumed_share: float
    """Fraction of the best-estimate loss resting on an assumed fragility or consequence model."""
    assumptions: tuple[str, ...] = ()
    model_ids: tuple[str, ...] = ()
    component_totals: dict[HazardComponent, float] = dataclass_field(default_factory=dict)

    def lines(self) -> list[str]:
        out = [
            f"portfolio: {self.portfolio_id}",
            f"trigger: {self.trigger_kind.value} {self.trigger_id}",
            (
                f"ground motion: {self.field.gsim} {self.field.imt} via "
                f"{self.field.engine.value} ({self.field.n_realisations} realisations)"
            ),
            (
                f"expected loss: {self.total.best:,.0f} {self.total.currency} "
                f"[{self.total.low:,.0f}, {self.total.high:,.0f}] "
                f"({self.total.provenance.value}, {self.total.confidence.value})"
            ),
            f"assumption-dependent share of the loss: {self.assumed_share:.0%}",
            f"assets modelled: {len(self.modelled_asset_ids)}",
        ]
        out.extend(f"not modelled: {a} ({why})" for a, why in self.unmodelled)
        out.extend(f"assumption: {a}" for a in self.assumptions)
        return out


def sites_for(
    portfolio: ExposurePortfolio, *, default_vs30: float = DEFAULT_VS30
) -> tuple[Site, ...]:
    """One site per asset, taking Vs30 from the asset's attributes when the loader recorded one."""
    out = []
    for asset in portfolio.assets:
        raw = asset.attributes.get("vs30")
        vs30 = float(raw) if isinstance(raw, int | float) else default_vs30
        out.append(Site(id=asset.id, longitude=asset.longitude, latitude=asset.latitude, vs30=vs30))
    return tuple(out)


LOGIC_TREE_UNSUPPORTED = (
    "a GSIM logic tree was requested but this ground-motion engine cannot evaluate one; "
    "use NativeGsimEngine or the OpenQuake adapter"
)


def ground_motion(
    engine: GroundMotionEngine,
    rupture: ScenarioRupture,
    sites: tuple[Site, ...],
    cfg: RunConfig,
    *,
    n_realisations: int | None = None,
    seed: int | EllipsisType | None = ...,
) -> GroundMotionField:
    """One field for ``rupture``, from a single GSIM or from ``cfg.gsim_logic_tree``.

    Every path in the risk layer goes through here, so a run configured with a logic tree gets
    one everywhere rather than in whichever module remembered to ask.
    """
    n = cfg.n_realisations if n_realisations is None else n_realisations
    use_seed = cfg.seed if isinstance(seed, EllipsisType) else seed
    if cfg.gsim_logic_tree is None:
        return engine.scenario(
            rupture,
            sites,
            imt=cfg.imt,
            gsim=cfg.gsim,
            n_realisations=n,
            truncation_level=cfg.truncation_level,
            seed=use_seed,
        )
    if not isinstance(engine, LogicTreeGroundMotionEngine):
        raise LossError(LOGIC_TREE_UNSUPPORTED)
    return engine.scenario_logic_tree(
        rupture,
        sites,
        tree=cfg.gsim_logic_tree,
        imt=cfg.imt,
        n_realisations=n,
        truncation_level=cfg.truncation_level,
        seed=use_seed,
    )


def run_scenario(
    portfolio: ExposurePortfolio,
    rupture: ScenarioRupture,
    *,
    engine: GroundMotionEngine | None = None,
    vulnerability: HydropowerVulnerability | None = None,
    config: RunConfig | None = None,
) -> PortfolioLoss:
    """Price ``portfolio`` against ``rupture``."""
    cfg = config or RunConfig()
    eng = engine or NativeGsimEngine(strict_tectonic_region=not cfg.allow_tectonic_mismatch)
    model = vulnerability or HydropowerVulnerability()
    sites = sites_for(portfolio, default_vs30=cfg.default_vs30)
    gmf = ground_motion(eng, rupture, sites, cfg)
    return aggregate(
        portfolio,
        gmf,
        model,
        trigger_kind=TriggerKind.SCENARIO,
        trigger_id=rupture.id,
        interval_level=cfg.interval_level,
        extra_assumptions=(rupture.notes,) if rupture.notes else (),
    )


def aggregate(
    portfolio: ExposurePortfolio,
    gmf: GroundMotionField,
    model: HydropowerVulnerability,
    *,
    trigger_kind: TriggerKind,
    trigger_id: str,
    interval_level: float = 0.9,
    extra_assumptions: tuple[str, ...] = (),
) -> PortfolioLoss:
    """Aggregate one ground-motion field into a portfolio loss with an interval."""
    realisations = model.realisations(portfolio, gmf)
    if not realisations:
        msg = "the ground-motion field has no realisations"
        raise LossError(msg)
    totals = [total for total, _ in realisations]
    coverage = model.coverage(portfolio)

    per_asset: dict[str, list[dmg.AssetDamage]] = {}
    for _, damages in realisations:
        for d in damages:
            per_asset.setdefault(d.asset_id, []).append(d)

    price_year = portfolio.valuation_date.year
    basis = (
        f"{gmf.gsim} {gmf.imt} from {gmf.engine.value}, {gmf.n_realisations} realisation(s); "
        "HAZUS component fragility with the assumed parameters of ADR-0024"
    )
    total = money_range(
        totals,
        currency=portfolio.currency,
        price_year=price_year,
        basis=basis,
        interval_level=interval_level,
    )
    asset_losses = tuple(
        AssetLoss(
            asset_id=asset_id,
            loss_type=LossType.STRUCTURAL,
            expected_loss=money_range(
                [d.loss for d in damages],
                currency=portfolio.currency,
                price_year=price_year,
                basis=basis,
                interval_level=interval_level,
            ),
            by_component=_mean_components(damages),
        )
        for asset_id, damages in sorted(per_asset.items())
    )
    assumed = sum(d.assumed_loss for _, damages in realisations for d in damages)
    modelled_total = sum(totals)
    return PortfolioLoss(
        portfolio_id=portfolio.id,
        trigger_kind=trigger_kind,
        trigger_id=trigger_id,
        field=gmf,
        total=total,
        by_asset=asset_losses,
        realisation_totals=tuple(totals),
        modelled_asset_ids=coverage.modelled,
        unmodelled=coverage.unmodelled,
        assumed_share=(assumed / modelled_total) if modelled_total > 0.0 else 0.0,
        assumptions=(
            VALUE_SHARE_ASSUMPTION,
            CASCADE_NOT_MODELLED,
            NO_SPATIAL_CORRELATION,
            *extra_assumptions,
        ),
        model_ids=(model.model_id, gmf.gsim, gmf.engine.value),
        component_totals=_portfolio_components(realisations),
    )


def _mean_components(damages: list[dmg.AssetDamage]) -> dict[HazardComponent, float]:
    out: dict[HazardComponent, float] = {}
    for component in (HazardComponent.GROUND_SHAKING, *dmg.UNMODELLED_COMPONENTS):
        out[component] = sum(d.by_hazard_component.get(component, 0.0) for d in damages) / len(
            damages
        )
    return out


def _portfolio_components(
    realisations: list[tuple[float, tuple[dmg.AssetDamage, ...]]],
) -> dict[HazardComponent, float]:
    out: dict[HazardComponent, float] = {}
    n = len(realisations)
    for component in (HazardComponent.GROUND_SHAKING, *dmg.UNMODELLED_COMPONENTS):
        out[component] = (
            sum(
                d.by_hazard_component.get(component, 0.0)
                for _, damages in realisations
                for d in damages
            )
            / n
        )
    return out


def stub_money(currency: str, price_year: int, basis: str) -> MoneyRange:
    """A zero figure that is honest about being a stub, for a request rupture cannot answer."""
    return MoneyRange(
        low=0.0,
        high=0.0,
        best=0.0,
        currency=currency,
        price_year=price_year,
        basis=basis,
        confidence=ConfidenceTier.UNQUALIFIED,
        provenance=ModelProvenance.STUB,
    )
