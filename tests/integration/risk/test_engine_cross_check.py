"""Cross-check ``native_gsim`` against the OpenQuake engine on the same rupture and sites.

This is the test that makes the native path trustworthy (ADR-0020). The GSIM verification tests
prove that rupture reproduces OpenQuake's *published expected values*; this one proves that the
whole path — distances derived from a ``ScenarioRupture``, site parameters, the GSIM itself —
agrees with the engine actually running the same scenario.

It **skips locally with a printed reason**: the ``openquake/engine`` image is ``linux/amd64``-only
and this project's development machine is arm64 (ADR-0011 addendum). CI runs on amd64 and executes
it for real. Set ``RUPTURE_RISK_REQUIRE_ENGINE=1`` to turn a skip into a failure, which is what the
CI job does so that a silently skipped cross-check cannot pass for a green one.

Nothing here has been observed to run on the development machine. If the engine and the native
path disagree, that is a finding to report, not a bug to hide: the tolerance below is deliberately
tight enough to surface a real disagreement.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.groundmotion import NativeGsimEngine
from rupture.adapters.groundmotion.openquake_scenario import OpenQuakeScenarioEngine
from rupture.domain.groundmotion import GroundMotionEngineId, Site
from rupture.risk import scenarios

REQUIRE_ENV = "RUPTURE_RISK_REQUIRE_ENGINE"
REPO_ROOT = Path(__file__).resolve().parents[3]
MEDIAN_TOLERANCE_PERCENT = 5.0
"""Median ground motion, per site. The engine meshes the rupture surface and rupture computes the
distances analytically, so a few per cent is expected; more than that is a real disagreement."""

SITES: tuple[Site, ...] = (
    Site(id="rasuwagadhi", longitude=85.3771, latitude=28.2736, vs30=760.0),
    Site(id="syabrubesi", longitude=85.3427, latitude=28.1646, vs30=600.0),
    Site(id="betrawati", longitude=85.1860, latitude=27.9731, vs30=400.0),
)


def _required() -> bool:
    return os.environ.get(REQUIRE_ENV, "").strip().lower() in {"1", "true", "yes"}


@pytest.mark.integration
def test_native_gsim_agrees_with_the_openquake_engine(tmp_path: Path) -> None:
    engine = OpenQuakeScenarioEngine()
    ok, reason = engine.available()
    if not ok:
        message = f"the OpenQuake container cannot run here: {reason}"
        if _required():
            pytest.fail(f"{REQUIRE_ENV} is set and {message}")
        pytest.skip(message)

    rupture = scenarios.gorkha_2015_repeat(REPO_ROOT)
    engine_field = engine.scenario(
        rupture,
        SITES,
        imt="PGA",
        gsim="BooreEtAl2014",
        n_realisations=1,
        truncation_level=0.0,
        seed=42,
        work_dir=tmp_path / "oq",
    )
    native_field = NativeGsimEngine().scenario(
        rupture,
        SITES,
        imt="PGA",
        gsim="BooreEtAl2014",
        n_realisations=1,
        truncation_level=0.0,
        seed=42,
    )
    assert engine_field.engine is GroundMotionEngineId.OPENQUAKE_ENGINE
    assert native_field.engine is GroundMotionEngineId.NATIVE_GSIM

    engine_median = engine_field.median()
    native_median = native_field.median()
    discrepancy = 100.0 * np.abs(native_median - engine_median) / engine_median
    assert discrepancy.max() <= MEDIAN_TOLERANCE_PERCENT, (
        "native_gsim and the OpenQuake engine disagree on the same rupture and sites: "
        f"engine {engine_median}, native {native_median}, worst {discrepancy.max():.2f} %"
    )


@pytest.mark.integration
def test_the_engine_path_reports_why_it_cannot_run_here() -> None:
    """A skip must always carry a reason; a silent skip is the failure mode this guards."""
    ok, reason = OpenQuakeScenarioEngine().available()
    if ok:
        pytest.skip("the container is available here, so there is no reason to print")
    assert reason, "the engine reported itself unavailable without saying why"
