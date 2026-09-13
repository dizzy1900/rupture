"""Distance-plus-slip: missing field is an error; a real finite-fault table is usable."""

from __future__ import annotations

from datetime import timedelta

import pytest
from tests.unit.models.comparators.conftest import (
    GORKHA_CUTOFF,
    GORKHA_M_MAIN,
    GORKHA_MC,
    load_gorkha_subfaults,
)

from rupture.adapters.forecasting.grid import build_lattice
from rupture.domain import Catalog, Region
from rupture.models.comparators.distance_slip import MODEL_ID, DistanceSlipAftershockModel
from rupture.models.comparators.errors import MissingSlipFieldError
from rupture.models.comparators.logistic import OneNeuronAftershockModel
from rupture.models.comparators.slip import SlipField, slip_field_from_subfaults


def test_constructing_without_a_slip_field_names_what_is_missing() -> None:
    with pytest.raises(MissingSlipFieldError, match="finite-fault / slip field"):
        DistanceSlipAftershockModel(slip_field=None)


def test_a_constant_slip_field_is_refused_rather_than_dropped(
    gorkha_catalog: Catalog, gorkha_region: Region
) -> None:
    lattice = build_lattice(gorkha_region)
    constant = SlipField(
        cell_origins=lattice.origins,
        mean_slip_m=tuple(1.0 for _ in lattice.origins),
    )
    model = DistanceSlipAftershockModel(slip_field=constant, m_main=GORKHA_M_MAIN, mc=GORKHA_MC)
    with pytest.raises(MissingSlipFieldError, match="spatially constant"):
        model.fit(gorkha_catalog, gorkha_region, GORKHA_CUTOFF)


def test_misaligned_slip_field_is_refused(gorkha_catalog: Catalog, gorkha_region: Region) -> None:
    field = SlipField(cell_origins=((-1.0, 0.0),), mean_slip_m=(0.5,))
    model = DistanceSlipAftershockModel(slip_field=field, m_main=GORKHA_M_MAIN, mc=GORKHA_MC)
    with pytest.raises(MissingSlipFieldError, match="not on this region's lattice"):
        model.fit(gorkha_catalog, gorkha_region, GORKHA_CUTOFF)


def test_gorkha_finite_fault_identifies_the_third_parameter(
    gorkha_catalog: Catalog, gorkha_region: Region
) -> None:
    lattice = build_lattice(gorkha_region)
    lons, lats, slips = load_gorkha_subfaults()
    assert any(s > 0.0 for s in slips), "the committed FSP table carries positive slip"
    field = slip_field_from_subfaults(
        lattice.origins, gorkha_region.cell_size_deg, lons, lats, slips
    )
    model = DistanceSlipAftershockModel(slip_field=field, m_main=GORKHA_M_MAIN, mc=GORKHA_MC)
    fit = model.fit(gorkha_catalog, gorkha_region, GORKHA_CUTOFF)
    assert model.model_id == MODEL_ID
    assert fit.parameters["used_slip"] == 1.0
    assert "c" in fit.parameters
    assert "three-parameter logistic" in (fit.notes or "")
    assert "log mean slip" in (fit.notes or "")
    history = gorkha_catalog.earthquakes().before(GORKHA_CUTOFF).at_least(GORKHA_MC)
    grid = model.forecast(history, GORKHA_CUTOFF, timedelta(days=30))
    assert grid.total_expected() > 0.0
    assert "expected COUNTS" in (grid.notes or "")
    assert "three-parameter logistic" in (grid.notes or "")


def test_one_neuron_with_slip_says_it_is_three_parameter(
    gorkha_catalog: Catalog, gorkha_region: Region
) -> None:
    lattice = build_lattice(gorkha_region)
    lons, lats, slips = load_gorkha_subfaults()
    field = slip_field_from_subfaults(
        lattice.origins, gorkha_region.cell_size_deg, lons, lats, slips
    )
    model = OneNeuronAftershockModel(m_main=GORKHA_M_MAIN, mc=GORKHA_MC, slip_field=field)
    fit = model.fit(gorkha_catalog, gorkha_region, GORKHA_CUTOFF)
    assert fit.parameters["used_slip"] == 1.0
    assert "three-parameter logistic" in (fit.notes or "")
