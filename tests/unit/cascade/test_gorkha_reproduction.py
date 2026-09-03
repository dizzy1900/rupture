"""The Gorkha reproduction against the real published USGS product, offline.

These tests pin the numbers ``docs/CASCADE.md`` quotes, so the documentation cannot drift away
from what the code actually achieves.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.cascade import gorkha
from rupture.adapters.cascade.reproduction import Comparison, ReproductionReport
from rupture.adapters.cascade.shakemap import read_slice_csv


@pytest.fixture(scope="module")
def reports(repo_root: Path) -> dict[str, ReproductionReport]:
    return gorkha.run_all(repo_root)


def test_the_shakemap_slice_is_the_grid_the_product_was_computed_from(
    gorkha_fixtures: Path,
) -> None:
    grid = read_slice_csv(gorkha_fixtures / "shakemap_grid_slice.csv", event_id="us20002926")
    assert set(grid.bands) == {"PGA", "PGV", "SVEL"}
    assert grid.longitudes[0] < grid.longitudes[-1]
    assert grid.latitudes[0] > grid.latitudes[-1], "ShakeMap rows run north to south"
    # Gorkha shook the Kathmandu region hard: the slice must contain real, large values.
    assert grid.bands["PGV"].max() > 50.0
    assert 0.0 < grid.bands["PGA"].max() < 200.0  # %g
    assert grid.bands["SVEL"].min() > 0.0


def test_the_shakemap_slice_covers_the_serac_langtang_aoi(gorkha_fixtures: Path) -> None:
    """The Langtang 2015 mechanism is the point of the exposure overlay; it must be inside."""
    grid = read_slice_csv(gorkha_fixtures / "shakemap_grid_slice.csv", event_id="us20002926")
    lon0, lat0, lon1, lat1 = grid.bounds
    assert lon0 <= 85.51
    assert lon1 >= 85.53
    assert lat0 <= 28.27
    assert lat1 >= 28.29


def test_sampling_outside_the_grid_is_refused_not_extrapolated(gorkha_fixtures: Path) -> None:
    grid = read_slice_csv(gorkha_fixtures / "shakemap_grid_slice.csv", event_id="us20002926")
    with pytest.raises(ValueError, match="does not"):
        grid.sample("PGV", np.array([0.0]), np.array([0.0]))


@pytest.mark.parametrize("model_id", ["zhu_2017_general", "nowicki_jessee_2018"])
def test_the_link_round_trip_is_exact(
    reports: dict[str, ReproductionReport], model_id: str
) -> None:
    """rupture's coverage transform and its inverse must agree with the published raster exactly."""
    link = reports[model_id].agreement(Comparison.LINK)
    assert link.n_cells > 1000
    assert link.max_absolute_difference == 0.0


def test_the_zhu_shaking_reproduction_is_close_but_not_perfect(
    reports: dict[str, ReproductionReport],
) -> None:
    """With the static term taken from the product, only shaking, clips and masks are tested.

    It is not exact: the ShakeMap SVEL band is not the Wald and Allen (2007) Vs30 raster the
    USGS product used, so a small number of cells fall on the other side of a mask.
    """
    shaking = reports["zhu_2017_general"].agreement(Comparison.SHAKING)
    assert shaking.pearson_r > 0.99
    assert shaking.mean_absolute_difference < 0.005
    assert shaking.max_absolute_difference > 0.0, "the Vs30 source difference must be visible"
    assert shaking.fraction_within_tolerance > 0.98


def test_the_jessee_shaking_comparison_is_flagged_degenerate(
    reports: dict[str, ReproductionReport],
) -> None:
    """It scores perfectly for an uninteresting reason, and the report must say so."""
    report = reports["nowicki_jessee_2018"]
    assert report.agreement(Comparison.SHAKING).max_absolute_difference == 0.0
    assert any(note.startswith("DEGENERATE") for note in report.notes)


@pytest.mark.parametrize(
    ("model_id", "max_r", "min_mad"),
    [("zhu_2017_general", 0.6, 0.05), ("nowicki_jessee_2018", 0.3, 0.02)],
)
def test_the_unconditioned_reproduction_is_poor_and_says_so(
    reports: dict[str, ReproductionReport], model_id: str, max_r: float, min_mad: float
) -> None:
    """What rupture can compute today, with no static covariate sourced, is not close.

    This test asserts the agreement is *bad*. If it ever becomes good, either someone sourced the
    covariates (in which case update this test and the docs) or something is wrong.
    """
    item = reports[model_id].agreement(Comparison.UNCONDITIONED)
    assert item.pearson_r < max_r
    assert item.mean_absolute_difference > min_mad
    assert item.bias < 0.0, "with the static term set to zero rupture must under-call, not over"


def test_the_recovered_static_term_is_admissible_under_the_published_coefficients(
    reports: dict[str, ReproductionReport],
) -> None:
    """A falsifiable check: a wrong coefficient or unit would push it outside the published band."""
    admissibility = reports["zhu_2017_general"].admissibility
    assert admissibility is not None
    assert admissibility.upper_bound == pytest.approx(0.0005408 * 2500.0)
    assert admissibility.fraction_within > 0.95
    assert admissibility.median > 0.0, "the Ganges plain is wet; the precipitation term is positive"


def test_no_admissibility_bound_is_claimed_for_the_landslide_model(
    reports: dict[str, ReproductionReport],
) -> None:
    """Its lithology and land-cover coefficients are unbounded above and rupture lacks them."""
    assert reports["nowicki_jessee_2018"].admissibility is None


def test_the_report_names_the_covariates_that_were_not_sourced(
    reports: dict[str, ReproductionReport],
) -> None:
    assert set(reports["zhu_2017_general"].covariates_not_sourced) == {
        "precipitation_mm",
        "distance_to_water_km",
        "water_table_depth_m",
    }
    assert set(reports["nowicki_jessee_2018"].covariates_not_sourced) == {
        "slope_deg",
        "lithology_coefficient",
        "cti",
        "landcover_coefficient",
    }
    for report in reports.values():
        assert "susceptibility" in str(report.as_dict()["label"])
