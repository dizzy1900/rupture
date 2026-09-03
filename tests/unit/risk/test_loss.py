"""Damage and portfolio loss: the arithmetic, the intervals, and what the result refuses to hide."""

from __future__ import annotations

import math

import jsonschema
import pytest

from rupture.adapters.exposure import SeracExposureSource
from rupture.adapters.exposure.serac_export import FALLBACK_REL
from rupture.adapters.groundmotion import NativeGsimEngine
from rupture.adapters.vulnerability import HydropowerVulnerability, hydropower
from rupture.adapters.vulnerability.library import VulnerabilityError, money_range
from rupture.domain import contracts
from rupture.domain.avoided_loss_v1 import HazardComponent
from rupture.domain.loss import Asset, ExposurePortfolio
from rupture.domain.money import ModelProvenance
from rupture.ports.vulnerability import VulnerabilityModel
from rupture.risk import damage as dmg
from rupture.risk import loss as loss_module
from rupture.risk import scenarios
from tests.unit.risk.conftest import REPO_ROOT

AOI = "lhende-khola-trishuli"
FALLBACK = REPO_ROOT / FALLBACK_REL / AOI / "exposed_assets.geojson"
REALISATIONS = 200


@pytest.fixture(scope="module")
def portfolio() -> ExposurePortfolio:
    return SeracExposureSource(repo_root=REPO_ROOT).load(FALLBACK, portfolio_id="trishuli-corridor")


@pytest.fixture(scope="module")
def result(portfolio: ExposurePortfolio) -> loss_module.PortfolioLoss:
    rupture = scenarios.gorkha_2015_repeat(REPO_ROOT)
    config = loss_module.RunConfig(n_realisations=REALISATIONS, seed=1234)
    return loss_module.run_scenario(portfolio, rupture, engine=NativeGsimEngine(), config=config)


def test_the_model_satisfies_the_port() -> None:
    assert isinstance(HydropowerVulnerability(), VulnerabilityModel)


def test_component_shares_that_do_not_add_up_are_refused() -> None:
    specs = [
        dmg.ComponentSpec(s.component.value, s.value_share, s.fragility, s.consequence)
        for s in hydropower.components(60.0)
    ]
    specs[0] = dmg.ComponentSpec(specs[0].name, 0.5, specs[0].fragility, specs[0].consequence)
    with pytest.raises(dmg.DamageError, match="sum to"):
        dmg.check_shares(tuple(specs))


def test_damage_scales_with_value_and_intensity(portfolio: ExposurePortfolio) -> None:
    model = HydropowerVulnerability()
    asset = next(a for a in portfolio.assets if a.value > 0.0)
    specs = model.components_for(asset)
    assert specs is not None
    low = dmg.asset_damage(asset, 0.05, specs)
    high = dmg.asset_damage(asset, 0.8, specs)
    assert 0.0 < low.loss < high.loss <= asset.value
    doubled = asset.model_copy(update={"value": asset.value * 2.0})
    assert dmg.asset_damage(doubled, 0.8, specs).loss == pytest.approx(high.loss * 2.0)


def test_zero_intensity_causes_no_loss(portfolio: ExposurePortfolio) -> None:
    model = HydropowerVulnerability()
    asset = next(a for a in portfolio.assets if a.value > 0.0)
    specs = model.components_for(asset)
    assert specs is not None
    assert dmg.asset_damage(asset, 0.0, specs).loss == 0.0


def test_the_result_reports_every_asset_it_could_not_model(
    result: loss_module.PortfolioLoss,
) -> None:
    unmodelled = dict(result.unmodelled)
    assert set(unmodelled) == {
        "rasuwagadhi-kerung-border-post",
        "miteri-bridge",
        "timure",
        "syabrubesi",
        "betrawati",
    }
    assert all(reason for reason in unmodelled.values())
    assert len(result.modelled_asset_ids) == 9


def test_intervals_are_finite_and_ordered(result: loss_module.PortfolioLoss) -> None:
    for money in [result.total, *[al.expected_loss for al in result.by_asset]]:
        assert math.isfinite(money.low)
        assert math.isfinite(money.high)
        assert money.best is not None
        assert money.low <= money.best <= money.high
        assert money.basis


def test_the_total_is_the_mean_of_the_realisation_totals(
    result: loss_module.PortfolioLoss,
) -> None:
    assert result.total.best == pytest.approx(
        sum(result.realisation_totals) / len(result.realisation_totals)
    )
    assert len(result.realisation_totals) == REALISATIONS


def test_the_cascade_components_are_reported_as_an_explicit_zero(
    result: loss_module.PortfolioLoss,
) -> None:
    """Not omitted: a reader must be able to see that they are not modelled."""
    for asset_loss in result.by_asset:
        assert set(asset_loss.by_component) == set(HazardComponent)
        assert asset_loss.by_component[HazardComponent.GROUND_SHAKING] > 0.0
        for component in dmg.UNMODELLED_COMPONENTS:
            assert asset_loss.by_component[component] == 0.0
    assert any("cascade" in a for a in result.assumptions)


def test_the_result_says_how_much_of_the_loss_is_assumed(
    result: loss_module.PortfolioLoss,
) -> None:
    """The intake and penstock fragilities are assumed and they carry real money."""
    assert 0.0 < result.assumed_share < 1.0
    assert any("value shares" in a for a in result.assumptions)


def test_the_loss_figure_never_claims_published_provenance(
    result: loss_module.PortfolioLoss,
) -> None:
    assert result.total.provenance is ModelProvenance.ASSUMED


def test_asset_losses_validate_against_the_avoided_loss_contract(
    result: loss_module.PortfolioLoss,
) -> None:
    schema = contracts.schema_for("avoided-loss.v1.json")
    definitions = schema["$defs"]["AssetLoss"]
    for asset_loss in result.by_asset:
        jsonschema.validate(
            asset_loss.model_dump(mode="json"), {**definitions, "$defs": schema["$defs"]}
        )


def test_a_field_without_the_portfolios_sites_is_an_error(portfolio: ExposurePortfolio) -> None:
    rupture = scenarios.gorkha_2015_repeat(REPO_ROOT)
    other = ExposurePortfolio(
        id="one",
        currency="USD",
        valuation_date=portfolio.valuation_date,
        assets=(
            Asset(
                id="not-in-the-field",
                longitude=85.0,
                latitude=28.0,
                taxonomy="hydropower_plant",
                value=1.0e6,
            ),
        ),
        provenance=portfolio.provenance,
    )
    field = NativeGsimEngine().scenario(
        rupture, loss_module.sites_for(portfolio), gsim="BooreEtAl2014"
    )
    with pytest.raises(VulnerabilityError, match="no site for asset"):
        HydropowerVulnerability().realisations(other, field)


def test_a_single_realisation_has_a_zero_width_interval() -> None:
    money = money_range([1.0e6], currency="USD", price_year=2026, basis="one")
    assert money.low == money.high == money.best
    assert "single realisation" in money.basis


def test_more_realisations_widen_the_interval(portfolio: ExposurePortfolio) -> None:
    rupture = scenarios.gorkha_2015_repeat(REPO_ROOT)
    engine = NativeGsimEngine()
    one = loss_module.run_scenario(
        portfolio, rupture, engine=engine, config=loss_module.RunConfig(n_realisations=1)
    )
    many = loss_module.run_scenario(
        portfolio,
        rupture,
        engine=engine,
        config=loss_module.RunConfig(n_realisations=REALISATIONS, seed=7),
    )
    assert one.total.width == 0.0
    assert many.total.width > 0.0
