"""The two ground-failure models: link, coverage transform, clips, masks and honesty flags."""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest

from rupture.cascade.coefficients import Covariate
from rupture.cascade.covariates import (
    PublishedStaticTerm,
    TabulatedCovariates,
    UnsourcedCovariates,
)
from rupture.cascade.models import NowickiJessee2018, Zhu2017General, build
from rupture.domain.cascade import CascadeKind
from rupture.domain.common import Provenance
from rupture.domain.groundmotion import GroundMotionEngineId, GroundMotionField, Site


def make_field(imt: str, values: list[float], *, vs30: float = 300.0) -> GroundMotionField:
    sites = tuple(
        Site(id=str(i), longitude=85.0 + i * 0.01, latitude=28.0, vs30=vs30)
        for i in range(len(values))
    )
    return GroundMotionField(
        id=f"test-{imt.lower()}",
        scenario_id="test-scenario",
        imt=imt,
        sites=sites,
        values=(tuple(values),),
        engine=GroundMotionEngineId.NATIVE_GSIM,
        engine_version="test",
        gsim="test",
        computed_at=datetime(2026, 9, 3, tzinfo=UTC),
        provenance=Provenance(
            source="test", retrieved_at=datetime(2026, 9, 3, tzinfo=UTC), adapter_version="0.0.0"
        ),
    )


# ------------------------------------------------------------------ coverage transforms
@pytest.mark.parametrize("model_factory", [NowickiJessee2018, Zhu2017General])
def test_coverage_is_monotone_and_bounded_by_the_published_maximum(model_factory: type) -> None:
    model = model_factory()
    p = np.linspace(0.0, 1.0, 501)
    coverage = model.coverage(p)
    assert np.all(np.diff(coverage) > 0), "the published coverage transform is monotone in P"
    assert coverage.min() > 0.0
    assert coverage.max() == pytest.approx(model.spec.maximum_probability, abs=5e-4)


@pytest.mark.parametrize("model_factory", [NowickiJessee2018, Zhu2017General])
def test_coverage_inverse_round_trips(model_factory: type) -> None:
    model = model_factory()
    p = np.linspace(0.01, 0.99, 199)
    assert model.invert_coverage(model.coverage(p)) == pytest.approx(p, abs=1e-4)


def test_zhu_magnitude_scaling_uses_the_usgs_literal() -> None:
    """The operational code writes 2.71828, not e. rupture reproduces the literal."""
    model = Zhu2017General()
    scaling = model.magnitude_scaling(6.0)
    assert scaling == pytest.approx(0.5, abs=1e-12)
    assert model.magnitude_scaling(7.8) == pytest.approx(1.0 / (1.0 + 2.71828**-3.6), abs=1e-15)
    assert model.magnitude_scaling(7.8) != 1.0 / (1.0 + np.exp(-3.6))


# ------------------------------------------------------------------ masks
def test_zhu_masks_zero_the_cells_the_published_model_declines_to_evaluate() -> None:
    model = Zhu2017General()
    evaluation = model.evaluate_arrays(
        longitudes=np.array([85.0, 85.1, 85.2, 85.3]),
        latitudes=np.array([28.0, 28.0, 28.0, 28.0]),
        pgv_cm_s=np.array([2.0, 50.0, 50.0, 50.0]),  # first below minpgv = 3 cm/s
        pga_g=np.array([0.5, 0.05, 0.5, 0.5]),  # second below minpga = 0.10 g
        vs30_m_s=np.array([300.0, 300.0, 700.0, 300.0]),  # third above vs30max = 620
        magnitude=7.0,
    )
    assert evaluation.coverage[0] == 0.0
    assert evaluation.coverage[1] == 0.0
    assert evaluation.coverage[2] == 0.0
    assert evaluation.coverage[3] > 0.0
    assert evaluation.mask_counts[Covariate.PGV_CM_S.value] == 1
    assert evaluation.mask_counts[Covariate.PGA_G.value] == 1
    assert evaluation.mask_counts[Covariate.VS30_M_S.value] == 1


def test_an_unavailable_mask_covariate_is_reported_not_skipped_silently() -> None:
    model = Zhu2017General()
    evaluation = model.evaluate_arrays(
        longitudes=np.array([85.0]),
        latitudes=np.array([28.0]),
        pgv_cm_s=np.array([50.0]),
        pga_g=None,
        vs30_m_s=np.array([300.0]),
        magnitude=7.0,
    )
    assert Covariate.PGA_G.value in evaluation.masks_not_applied
    assert Covariate.SLOPE_DEG.value in evaluation.masks_not_applied


def test_the_slope_mask_applies_when_slope_is_sourced() -> None:
    lons = np.array([85.0, 85.1])
    lats = np.array([28.0, 28.0])
    covariates = TabulatedCovariates(
        {
            Covariate.SLOPE_DEG: np.array([1.0, 20.0]),  # first below jessee slopemin = 2 deg
            Covariate.LITHOLOGY_COEFFICIENT: np.array([0.0, 0.0]),
            Covariate.LANDCOVER_COEFFICIENT: np.array([0.0, 0.0]),
            Covariate.CTI: np.array([10.0, 10.0]),
        },
        source_id="test-covariates",
    )
    evaluation = NowickiJessee2018(covariates=covariates).evaluate_arrays(
        longitudes=lons,
        latitudes=lats,
        pgv_cm_s=np.array([80.0, 80.0]),
        pga_g=np.array([0.5, 0.5]),
        vs30_m_s=np.array([300.0, 300.0]),
        magnitude=7.8,
    )
    assert evaluation.coverage[0] == 0.0
    assert evaluation.coverage[1] > 0.0
    assert evaluation.static_term.complete
    assert Covariate.SLOPE_DEG.value not in evaluation.masks_not_applied


# ------------------------------------------------------------------ clips
def test_pgv_is_clipped_exactly_as_the_published_code_clips_it() -> None:
    model = Zhu2017General()
    at_clip = model.evaluate_arrays(
        longitudes=np.array([85.0]),
        latitudes=np.array([28.0]),
        pgv_cm_s=np.array([150.0]),
        pga_g=np.array([0.5]),
        vs30_m_s=np.array([300.0]),
        magnitude=7.0,
    )
    beyond = model.evaluate_arrays(
        longitudes=np.array([85.0]),
        latitudes=np.array([28.0]),
        pgv_cm_s=np.array([900.0]),
        pga_g=np.array([0.5]),
        vs30_m_s=np.array([300.0]),
        magnitude=7.0,
    )
    assert at_clip.coverage[0] == beyond.coverage[0]


# ------------------------------------------------------------------ honesty
def test_an_unsourced_run_says_so_in_the_output() -> None:
    model = NowickiJessee2018()
    field = model.evaluate(
        make_field("PGV", [40.0, 60.0]),
        scenario_id="s",
        pga_field=make_field("PGA", [0.3, 0.4]),
    )
    assert field.kind is CascadeKind.LANDSLIDE
    assert field.notes is not None
    assert "INCOMPLETE" in field.notes
    for name in ("slope_deg", "lithology_coefficient", "cti", "landcover_coefficient"):
        assert name in field.notes
    assert "susceptibility" in field.notes


def test_a_fully_sourced_run_does_not_claim_to_be_incomplete() -> None:
    lons = np.array([85.0, 85.01])
    covariates = TabulatedCovariates(
        {
            Covariate.PRECIPITATION_MM: np.array([1000.0, 1000.0]),
            Covariate.DISTANCE_TO_WATER_KM: np.array([1.0, 1.0]),
            Covariate.WATER_TABLE_DEPTH_M: np.array([5.0, 5.0]),
        },
        source_id="test-covariates",
    )
    term = covariates.static_term(Zhu2017General().spec, lons, lons)
    assert term.complete
    assert "INCOMPLETE" not in term.label()


def test_the_published_static_term_still_declares_every_covariate_missing() -> None:
    """It is a stand-in recovered from an answer, not a covariate set. It must never say sourced."""
    spec = Zhu2017General().spec
    term = PublishedStaticTerm(np.zeros(3), product="test").static_term(
        spec, np.zeros(3), np.zeros(3)
    )
    assert not term.complete
    assert set(term.missing) == {Covariate(t) for t in spec.static_terms}
    assert term.sourced == ()
    assert "recovered-from-published-usgs-product" in term.label()


def test_zhu_refuses_to_assume_a_magnitude() -> None:
    with pytest.raises(ValueError, match="magnitude"):
        Zhu2017General().evaluate(make_field("PGV", [40.0]), scenario_id="s")


def test_a_pgv_model_refuses_a_pga_field() -> None:
    with pytest.raises(ValueError, match="PGV field"):
        NowickiJessee2018().evaluate(make_field("PGA", [0.4]), scenario_id="s")


def test_probabilities_stay_in_range_over_absurd_shaking() -> None:
    model = Zhu2017General(covariates=UnsourcedCovariates())
    evaluation = model.evaluate_arrays(
        longitudes=np.linspace(84.0, 86.0, 50),
        latitudes=np.full(50, 28.0),
        pgv_cm_s=np.linspace(0.0, 5000.0, 50),
        pga_g=np.full(50, 2.0),
        vs30_m_s=np.linspace(80.0, 2000.0, 50),
        magnitude=9.0,
    )
    assert np.all(np.isfinite(evaluation.coverage))
    assert evaluation.coverage.min() >= 0.0
    assert evaluation.coverage.max() <= 1.0


def test_build_accepts_the_cli_aliases() -> None:
    assert build("landslide").model_id == "nowicki_jessee_2018"
    assert build("liquefaction").model_id == "zhu_2017_general"
    assert build("zhu_2017_general").model_id == "zhu_2017_general"
    with pytest.raises(KeyError):
        build("no_such_model")
