"""The ``native_gsim`` adapter: what it produces, what it records, and what it refuses."""

from __future__ import annotations

import jsonschema
import numpy as np
import pytest

from rupture.adapters.groundmotion import NativeGsimEngine, NativeGsimError, registry
from rupture.adapters.groundmotion.imt import PGA
from rupture.adapters.groundmotion.openquake_scenario import (
    OpenQuakeScenarioEngine,
    ScenarioExportError,
    parse_gmf_export,
    rupture_nrml,
    site_model_csv,
)
from rupture.domain import contracts
from rupture.domain.groundmotion import GroundMotionEngineId
from rupture.domain.hazard import ScenarioRupture
from rupture.ports.ground_motion import GroundMotionEngine
from tests.unit.risk.conftest import site

SITES = (site("a", 85.05, 28.0), site("b", 85.30, 28.0, vs30=350.0), site("c", 84.6, 27.9))


def test_the_adapter_satisfies_the_port() -> None:
    assert isinstance(NativeGsimEngine(), GroundMotionEngine)
    assert isinstance(OpenQuakeScenarioEngine(), GroundMotionEngine)


def test_a_single_realisation_is_the_median_field(crustal_rupture: ScenarioRupture) -> None:
    engine = NativeGsimEngine()
    field = engine.scenario(crustal_rupture, SITES, gsim="BooreEtAl2014", imt="PGA")
    assert field.n_realisations == 1
    assert field.engine is GroundMotionEngineId.NATIVE_GSIM
    assert field.gsim == "BooreEtAl2014"
    assert field.provenance.licence
    assert field.provenance.sha256

    ctx = engine.context(crustal_rupture, SITES)
    expected = np.exp(registry.build("BooreEtAl2014").compute(ctx, PGA).mean_ln)
    assert field.values[0] == pytest.approx(tuple(expected))
    # nearer site shakes harder than the far one
    assert field.values[0][0] > field.values[0][2]


def test_realisations_are_seeded_and_bounded(crustal_rupture: ScenarioRupture) -> None:
    engine = NativeGsimEngine()
    kwargs = {"gsim": "BooreEtAl2014", "imt": "PGA", "n_realisations": 400, "truncation_level": 3.0}
    first = engine.scenario(crustal_rupture, SITES, seed=7, **kwargs)  # type: ignore[arg-type]
    again = engine.scenario(crustal_rupture, SITES, seed=7, **kwargs)  # type: ignore[arg-type]
    other = engine.scenario(crustal_rupture, SITES, seed=8, **kwargs)  # type: ignore[arg-type]
    assert first.values == again.values
    assert first.values != other.values

    median_field = engine.scenario(crustal_rupture, SITES, gsim="BooreEtAl2014", imt="PGA")
    sampled = first.array()
    median = np.median(sampled, axis=0)
    reference = np.asarray(median_field.values[0])
    # the sample median of a truncated-lognormal is the median field, to sampling error
    assert median == pytest.approx(reference, rel=0.15)
    # every value lies inside exp(mean +- truncation*(tau+phi))
    ctx = engine.context(crustal_rupture, SITES)
    result = registry.build("BooreEtAl2014").compute(ctx, PGA)
    upper = np.exp(result.mean_ln + 3.0 * (result.tau + result.phi))
    lower = np.exp(result.mean_ln - 3.0 * (result.tau + result.phi))
    assert (sampled <= upper[None, :] + 1e-12).all()
    assert (sampled >= lower[None, :] - 1e-12).all()


def test_zero_truncation_switches_variability_off(crustal_rupture: ScenarioRupture) -> None:
    field = NativeGsimEngine().scenario(
        crustal_rupture,
        SITES,
        gsim="BooreEtAl2014",
        n_realisations=5,
        truncation_level=0.0,
        seed=1,
    )
    assert len(set(field.values)) == 1


def test_spectral_acceleration_is_supported(crustal_rupture: ScenarioRupture) -> None:
    field = NativeGsimEngine().scenario(crustal_rupture, SITES, gsim="BooreEtAl2014", imt="SA(0.3)")
    assert field.imt == "SA(0.3)"
    assert all(v > 0.0 for v in field.values[0])


def test_applying_a_subduction_gsim_to_a_crustal_rupture_must_be_deliberate(
    crustal_rupture: ScenarioRupture,
) -> None:
    with pytest.raises(NativeGsimError, match="defined for 'Subduction Interface'"):
        NativeGsimEngine().scenario(crustal_rupture, SITES, gsim="AbrahamsonEtAl2015SInter")
    field = NativeGsimEngine(strict_tectonic_region=False).scenario(
        crustal_rupture, SITES, gsim="AbrahamsonEtAl2015SInter"
    )
    assert field.notes is not None
    assert "allowed deliberately" in field.notes


def test_an_unknown_gsim_is_refused(crustal_rupture: ScenarioRupture) -> None:
    with pytest.raises(KeyError, match="unknown GSIM"):
        NativeGsimEngine().scenario(crustal_rupture, SITES, gsim="NotAGsim2099")


def test_the_field_validates_against_its_published_contract(
    crustal_rupture: ScenarioRupture,
) -> None:
    field = NativeGsimEngine().scenario(
        crustal_rupture, SITES, gsim="BooreEtAl2014", n_realisations=3, seed=3
    )
    jsonschema.validate(
        field.model_dump(mode="json"), contracts.schema_for("ground-motion-field.v0.json")
    )


def test_the_openquake_rupture_document_carries_the_geometry(
    crustal_rupture: ScenarioRupture,
) -> None:
    xml = rupture_nrml(crustal_rupture)
    assert "singlePlaneRupture" in xml
    assert '<planarSurface strike="0.0" dip="90.0">' in xml
    assert xml.index("topLeft") < xml.index("topRight") < xml.index("bottomLeft")


def test_a_point_rupture_is_refused_on_the_engine_path() -> None:
    point = ScenarioRupture(
        id="point",
        magnitude=6.0,
        hypocentre_longitude=85.0,
        hypocentre_latitude=28.0,
        hypocentre_depth_km=10.0,
        strike=0.0,
        dip=90.0,
        rake=0.0,
        hypothetical=True,
    )
    with pytest.raises(ValueError, match="four corners"):
        rupture_nrml(point)


def test_the_site_model_keeps_each_sites_own_vs30() -> None:
    text = site_model_csv(SITES)
    rows = text.strip().splitlines()
    assert rows[0].startswith("lon,lat,vs30")
    assert rows[2].split(",")[2] == "350"


def test_the_ground_motion_export_parser_maps_sites_and_events() -> None:
    sitemesh = (
        "site_id,lon,lat\n0,85.050000,28.000000\n1,85.300000,28.000000\n2,84.600000,27.900000\n"
    )
    gmf = "event_id,site_id,gmv_PGA\n0,0,0.30\n0,1,0.20\n0,2,0.10\n1,0,0.31\n1,1,0.21\n1,2,0.11\n"
    values = parse_gmf_export(gmf, sitemesh, SITES, "PGA")
    assert values == ((0.30, 0.20, 0.10), (0.31, 0.21, 0.11))


def test_a_missing_site_in_the_export_is_an_error_not_a_zero() -> None:
    sitemesh = (
        "site_id,lon,lat\n0,85.050000,28.000000\n1,85.300000,28.000000\n2,84.600000,27.900000\n"
    )
    gmf = "event_id,site_id,gmv_PGA\n0,0,0.30\n0,1,0.20\n"
    with pytest.raises(ScenarioExportError, match="no ground motion at site index"):
        parse_gmf_export(gmf, sitemesh, SITES, "PGA")
