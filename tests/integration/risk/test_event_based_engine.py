"""Run OpenQuake's ``event_based`` calculator on rupture's own rate model (ADR-0043).

The native route (:mod:`rupture.risk.event_set`) samples a stochastic event set from a promoted
F1 forecast in process. This test runs the **engine** over a source model built from the *same*
``ForecastGrid``, so the two routes can be compared on rates rather than on faith.

It **skips locally with a printed reason** for the same arm64/amd64 reason as
``test_engine_cross_check.py``, and ``RUPTURE_RISK_REQUIRE_ENGINE=1`` turns the skip into a
failure so CI cannot pass on a silent skip. Nothing here has been observed to run on the
development machine, and ``docs/RISK.md`` says so.

What is asserted is what an event-based run must get right for an annual loss to mean anything:
the engine returns events, every event carries the same occurrence rate, and the **total rate of
the returned set matches the source model's own rate** to within Poisson sampling error over the
investigation time. A mismatch there would silently scale every annual figure downstream.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

from rupture.adapters.groundmotion import logic_trees as lt
from rupture.adapters.groundmotion.openquake_event_based import (
    SECONDS_PER_YEAR,
    OpenQuakeEventBasedEngine,
    grid_source_model_nrml,
)
from rupture.domain.forecast import ForecastGrid
from rupture.domain.groundmotion import GroundMotionEngineId, Site

REQUIRE_ENV = "RUPTURE_RISK_REQUIRE_ENGINE"
REPO_ROOT = Path(__file__).resolve().parents[3]
SLICE_FILE = REPO_ROOT / "tests" / "fixtures" / "risk" / "forecast" / "trishuli-corridor-slice.json"
INVESTIGATION_TIME_YEARS = 500.0
SES = 1
LOGIC_TREE_SAMPLES = 3
MIN_MAGNITUDE = 5.0
RATE_TOLERANCE = 0.35
"""Poisson sampling error on a few hundred expected events, plus the engine's own rounding."""

SITES: tuple[Site, ...] = (
    Site(id="rasuwagadhi", longitude=85.3771, latitude=28.2736, vs30=760.0),
    Site(id="syabrubesi", longitude=85.3427, latitude=28.1646, vs30=600.0),
    Site(id="betrawati", longitude=85.1860, latitude=27.9731, vs30=400.0),
)


def _required() -> bool:
    return os.environ.get(REQUIRE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _expected_annual_rate(grid: ForecastGrid) -> float:
    years = grid.horizon.total_seconds() / SECONDS_PER_YEAR
    keep = [
        j
        for j, edge in enumerate(grid.magnitude_bin_edges)
        if edge + grid.magnitude_bin_width > MIN_MAGNITUDE
    ]
    return sum(row[j] for row in grid.expected_counts for j in keep) / years


@pytest.mark.integration
def test_the_engine_event_set_carries_the_source_models_own_rate(tmp_path: Path) -> None:
    engine = OpenQuakeEventBasedEngine()
    ok, reason = engine.available()
    if not ok:
        message = f"the OpenQuake container cannot run here: {reason}"
        if _required():
            pytest.fail(f"{REQUIRE_ENV} is set and {message}")
        pytest.skip(message)

    grid = ForecastGrid.model_validate(json.loads(SLICE_FILE.read_text(encoding="utf-8")))
    result = engine.event_based(
        grid_source_model_nrml(grid, min_magnitude=MIN_MAGNITUDE),
        SITES,
        tree=lt.ACTIVE_SHALLOW_CRUST_Q,
        investigation_time_years=INVESTIGATION_TIME_YEARS,
        ses_per_logic_tree_path=SES,
        n_logic_tree_samples=LOGIC_TREE_SAMPLES,
        minimum_magnitude=MIN_MAGNITUDE,
        seed=20260903,
        work_dir=tmp_path / "event_based",
    )
    assert result.fields
    assert all(f.engine is GroundMotionEngineId.OPENQUAKE_ENGINE for f in result.fields)
    assert all(f.n_realisations == 1 for f in result.fields)
    assert result.occurrence_rate_per_year == pytest.approx(
        1.0 / (INVESTIGATION_TIME_YEARS * SES * LOGIC_TREE_SAMPLES)
    )
    assert all(m >= MIN_MAGNITUDE - 0.05 for m in result.magnitudes)

    returned = len(result.fields) * result.occurrence_rate_per_year
    expected = _expected_annual_rate(grid)
    assert math.isclose(returned, expected, rel_tol=RATE_TOLERANCE), (
        f"the engine returned an event set whose rate is {returned:.4g}/yr against the source "
        f"model's own {expected:.4g}/yr; every annual figure downstream would be scaled by that"
    )
