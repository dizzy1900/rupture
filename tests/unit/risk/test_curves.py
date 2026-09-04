"""The vectorised loss curve must be the scalar damage chain, not an approximation of it."""

from __future__ import annotations

import numpy as np
import pytest

from rupture.adapters.vulnerability import hydropower
from rupture.domain.loss import Asset
from rupture.risk import damage as dmg
from rupture.risk.curves import AssetLossCurve, curve_for

INTENSITIES = np.array([1e-4, 0.005, 0.02, 0.05, 0.1, 0.2, 0.35, 0.5, 0.8, 1.2, 2.0, 4.0])


def _specs(capacity_mw: float, *, anchored: bool = False) -> tuple[dmg.ComponentSpec, ...]:
    return tuple(
        dmg.ComponentSpec(
            name=spec.component.value,
            value_share=spec.value_share,
            fragility=spec.fragility,
            consequence=spec.consequence,
        )
        for spec in hydropower.components(capacity_mw, anchored=anchored)
    )


@pytest.mark.parametrize("capacity_mw", [24.0, 216.0])
@pytest.mark.parametrize("anchored", [False, True])
def test_vectorised_curve_matches_the_scalar_damage_chain(
    capacity_mw: float, anchored: bool
) -> None:
    """Every component, at every intensity, to floating-point noise. No tolerance for drift."""
    specs = _specs(capacity_mw, anchored=anchored)
    asset = Asset(id="a", longitude=85.0, latitude=28.0, taxonomy=hydropower.TAXONOMY, value=1.0e8)
    curve = AssetLossCurve(asset_id=asset.id, value=asset.value, specs=specs)
    vectorised = curve.component_losses(INTENSITIES)
    totals = curve.loss(INTENSITIES)
    for index, intensity in enumerate(INTENSITIES):
        scalar = dmg.asset_damage(asset, float(intensity), specs)
        assert scalar.loss == pytest.approx(float(totals[index]), rel=1e-12, abs=1e-6)
        for component in scalar.components:
            assert component.loss == pytest.approx(
                float(vectorised[component.name][index]), rel=1e-12, abs=1e-6
            )


def test_zero_intensity_is_zero_loss() -> None:
    curve = AssetLossCurve(asset_id="a", value=1.0e8, specs=_specs(24.0))
    assert float(curve.loss(np.array([0.0]))[0]) == 0.0


def test_curve_for_refuses_an_asset_with_no_model_or_no_value() -> None:
    asset = Asset(id="a", longitude=85.0, latitude=28.0, taxonomy="settlement", value=1.0)
    assert curve_for(asset, None) is None
    valued = Asset(id="b", longitude=85.0, latitude=28.0, taxonomy=hydropower.TAXONOMY, value=0.0)
    assert curve_for(valued, _specs(24.0)) is None


def test_the_published_anchored_pair_crosses_at_low_intensity() -> None:
    """A recorded finding, not a defect: below ~0.05 g the anchored curve is fractionally worse.

    HAZUS publishes the anchored and unanchored generation-facility curves for plants under
    100 MW as a pair, and they cross. docs/RISK.md and ADR-0038 say what that does to an
    avoided-loss figure computed over an event set full of small earthquakes; this test pins the
    crossing so it cannot silently move or disappear.
    """
    intensities = np.linspace(0.001, 0.3, 2000)
    unanchored = AssetLossCurve("a", 1.0, _specs(24.0)).loss(intensities)
    anchored = AssetLossCurve("a", 1.0, _specs(24.0, anchored=True)).loss(intensities)
    worse = intensities[anchored > unanchored]
    assert worse.size > 0
    assert 0.004 < float(worse.min()) < 0.010
    assert 0.045 < float(worse.max()) < 0.060
    assert float((anchored - unanchored).max()) < 1.0e-3

    large_unanchored = AssetLossCurve("a", 1.0, _specs(216.0)).loss(intensities)
    large_anchored = AssetLossCurve("a", 1.0, _specs(216.0, anchored=True)).loss(intensities)
    assert float((large_anchored - large_unanchored).max()) <= 1e-12
