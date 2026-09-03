"""Shaking to damage to loss, for one asset at one intensity. Pure: no I/O, no adapters.

The chain is the standard one: a fragility model turns an intensity measure level into a discrete
damage distribution, a consequence model turns that distribution into an expected loss ratio, and
the ratio times the replacement value is the loss. What rupture adds is that a decomposed asset —
a hydropower plant — is evaluated **per component**, each with its own fragility, its own
consequence function and its own share of the value, so the answer can say which part of the plant
the loss came from.

Every result also carries a decomposition by :class:`HazardComponent`. Today that is entirely
``ground_shaking``; the landslide, liquefaction and ice-rock-avalanche shares are the seam C3
fills, and they are reported as an explicit zero rather than omitted, so a reader can see that
the cascade contribution is *not modelled* rather than *modelled as small*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rupture.domain.avoided_loss_v1 import HazardComponent
from rupture.domain.loss import Asset
from rupture.domain.vulnerability import ConsequenceModel, DamageState, FragilityModel

UNMODELLED_COMPONENTS: tuple[HazardComponent, ...] = (
    HazardComponent.LANDSLIDE,
    HazardComponent.LIQUEFACTION,
    HazardComponent.ICE_ROCK_AVALANCHE,
)
"""Reported as zero, and documented as not modelled. The C3 seam."""


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    """A part of an asset with its own share of value and its own damage model."""

    name: str
    value_share: float
    fragility: FragilityModel
    consequence: ConsequenceModel


@dataclass(frozen=True, slots=True)
class ComponentDamage:
    """What happened to one component at one intensity."""

    name: str
    value_share: float
    distribution: dict[DamageState, float]
    loss_ratio: float
    loss: float
    assumption: bool
    """True when either the fragility or the consequence function for this component is assumed."""


@dataclass(frozen=True, slots=True)
class AssetDamage:
    """What happened to one asset at one intensity."""

    asset_id: str
    intensity: float
    value: float
    loss: float
    components: tuple[ComponentDamage, ...] = ()
    by_hazard_component: dict[HazardComponent, float] = field(default_factory=dict)

    @property
    def loss_ratio(self) -> float:
        return self.loss / self.value if self.value > 0.0 else 0.0

    @property
    def assumed_loss(self) -> float:
        """The part of the loss that rests on an assumed fragility or consequence function."""
        return sum(c.loss for c in self.components if c.assumption)


class DamageError(ValueError):
    """The asset cannot be evaluated: no fragility, or a decomposition that does not add up."""


def check_shares(specs: tuple[ComponentSpec, ...], *, tolerance: float = 1e-9) -> None:
    """A decomposition whose shares do not sum to one would silently lose or invent value."""
    total = sum(s.value_share for s in specs)
    if abs(total - 1.0) > tolerance:
        names = ", ".join(s.name for s in specs)
        msg = f"component value shares sum to {total:.6f}, not 1.0 ({names})"
        raise DamageError(msg)


def component_damage(spec: ComponentSpec, asset_value: float, intensity: float) -> ComponentDamage:
    """Damage and loss for one component at one intensity measure level."""
    distribution = spec.fragility.damage_distribution(intensity)
    ratio = spec.consequence.loss_ratio(distribution)
    component_value = asset_value * spec.value_share
    return ComponentDamage(
        name=spec.name,
        value_share=spec.value_share,
        distribution=distribution,
        loss_ratio=ratio,
        loss=component_value * ratio,
        assumption=spec.fragility.assumption or spec.consequence.assumption,
    )


def asset_damage(asset: Asset, intensity: float, specs: tuple[ComponentSpec, ...]) -> AssetDamage:
    """Damage and loss for one asset, decomposed by component and by hazard component."""
    if not specs:
        msg = f"no damage model for asset {asset.id!r} (taxonomy {asset.taxonomy!r})"
        raise DamageError(msg)
    check_shares(specs)
    damages = tuple(component_damage(spec, asset.value, intensity) for spec in specs)
    total = sum(d.loss for d in damages)
    by_component = {HazardComponent.GROUND_SHAKING: total}
    for component in UNMODELLED_COMPONENTS:
        by_component[component] = 0.0
    return AssetDamage(
        asset_id=asset.id,
        intensity=intensity,
        value=asset.value,
        loss=total,
        components=damages,
        by_hazard_component=by_component,
    )


def single_component_spec(
    fragility: FragilityModel, consequence: ConsequenceModel, *, name: str = "whole"
) -> tuple[ComponentSpec, ...]:
    """An undecomposed asset class: one component holding all of the value."""
    return (
        ComponentSpec(name=name, value_share=1.0, fragility=fragility, consequence=consequence),
    )
