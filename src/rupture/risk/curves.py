"""The damage chain of :mod:`rupture.risk.damage`, evaluated over an array of intensities.

A scenario prices one rupture at a few hundred intensities and Python loops are free. An
event-based calculation prices tens of thousands of (event, realisation, site) triples, and the
same loops are not. This module is the vectorised form of exactly the same arithmetic: lognormal
fragility to a discrete damage distribution, a consequence function to a loss ratio, the ratio
times the component's share of the asset's value.

It is a **restatement, not an approximation**. There is no interpolation, no lookup table and no
tolerance: ``tests/unit/risk/test_curves.py`` asserts that
:meth:`AssetLossCurve.component_losses` reproduces :func:`rupture.risk.damage.asset_damage` to
within floating-point noise at every intensity it is given. If the two ever disagree the tests
fail rather than the event-based number quietly drifting from the scenario number.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from scipy import stats

from rupture.domain.loss import Asset
from rupture.domain.vulnerability import DamageState
from rupture.risk.damage import ComponentSpec, check_shares

FloatArray = npt.NDArray[np.float64]


def component_loss_ratio(spec: ComponentSpec, intensities: FloatArray) -> FloatArray:
    """Expected loss ratio for one component at each intensity in ``intensities``.

    Mirrors :meth:`rupture.domain.vulnerability.FragilityModel.damage_distribution` followed by
    :meth:`ConsequenceModel.loss_ratio`: the probability of *exactly* each damage state is the
    difference between successive exceedance probabilities, and the loss ratio is their
    consequence-weighted sum. Intensities at or below zero give a ratio of zero, as the scalar
    path does.
    """
    im = np.asarray(intensities, dtype=np.float64)
    positive = im > 0.0
    log_im = np.zeros_like(im)
    np.log(im, out=log_im, where=positive)

    ratios = np.zeros_like(im)
    previous = np.where(positive, 1.0, 0.0)
    functions = spec.fragility.functions
    for index, function in enumerate(functions):
        z = (log_im - np.log(function.median)) / function.beta
        exceed = np.where(positive, stats.norm.cdf(z), 0.0)
        state_below = DamageState.NONE if index == 0 else functions[index - 1].damage_state
        ratios += spec.consequence.loss_ratios.get(state_below, 0.0) * np.maximum(
            previous - exceed, 0.0
        )
        previous = exceed
    ratios += spec.consequence.loss_ratios.get(functions[-1].damage_state, 0.0) * previous
    return ratios


@dataclass(frozen=True, slots=True)
class AssetLossCurve:
    """One asset's loss as a function of intensity, decomposed by component.

    Built once per asset and then called for every event, which is what makes an event set of
    thousands of ruptures tractable in process.
    """

    asset_id: str
    value: float
    specs: tuple[ComponentSpec, ...]

    def __post_init__(self) -> None:
        check_shares(self.specs)

    @property
    def assumed_component_names(self) -> tuple[str, ...]:
        """Components whose fragility or consequence function is assumed, not published."""
        return tuple(
            s.name for s in self.specs if s.fragility.assumption or s.consequence.assumption
        )

    def component_losses(self, intensities: FloatArray) -> dict[str, FloatArray]:
        """Loss per component, same shape as ``intensities``, in the portfolio currency."""
        return {
            spec.name: self.value * spec.value_share * component_loss_ratio(spec, intensities)
            for spec in self.specs
        }

    def loss(self, intensities: FloatArray) -> FloatArray:
        """Total loss for this asset at each intensity."""
        losses = self.component_losses(intensities)
        if not losses:
            return np.zeros_like(np.asarray(intensities, dtype=np.float64))
        return np.sum(np.stack(list(losses.values())), axis=0)


def curve_for(asset: Asset, specs: tuple[ComponentSpec, ...] | None) -> AssetLossCurve | None:
    """An :class:`AssetLossCurve` for ``asset``, or ``None`` when it has no damage model or value.

    The ``None`` is the same honesty rule the scenario path keeps: an asset with no model is
    reported as unmodelled, never priced with a default curve.
    """
    if specs is None or asset.value <= 0.0:
        return None
    return AssetLossCurve(asset_id=asset.id, value=asset.value, specs=specs)
