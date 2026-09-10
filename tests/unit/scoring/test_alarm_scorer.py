"""The scorer's refusals and its bookkeeping: what it will not publish, and what it must attach."""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pytest

from rupture.domain import Provenance
from rupture.domain.alarm import ReferenceKind
from rupture.scoring import reference as refmod
from rupture.scoring.alarm import score_alarm_set
from rupture.scoring.errors import (
    LeakyReferenceError,
    MissingReferenceError,
    UniformReferenceRefusedError,
)
from tests.unit.scoring.conftest import (
    GRID_SIDE,
    ISSUE,
    make_alarm,
    make_catalog,
    make_reference,
)

N_CELLS = GRID_SIDE * GRID_SIDE


@pytest.fixture
def hot_alarm(cell_origins: tuple[tuple[float, float], ...]) -> object:
    values = np.zeros(N_CELLS)
    values[:5] = 1.0
    return make_alarm(cell_origins, values)


@pytest.fixture
def flat_reference(cell_origins: tuple[tuple[float, float], ...]) -> object:
    return make_reference(cell_origins, np.ones(N_CELLS))


def test_a_uniform_reference_is_refused_as_the_reference_of_record(
    hot_alarm: object, cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]))
    uniform = refmod.uniform(cell_origins, 0.1)
    with pytest.raises(UniformReferenceRefusedError, match="spatially uniform"):
        score_alarm_set(hot_alarm, catalog, uniform, n_simulations=10)  # type: ignore[arg-type]


def test_a_uniform_reference_is_scored_when_it_is_asked_for_as_a_contrast(
    hot_alarm: object, cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]))
    result = score_alarm_set(
        hot_alarm,  # type: ignore[arg-type]
        catalog,
        refmod.uniform(cell_origins, 0.1),
        n_simulations=200,
        seed=1,
        as_contrast=True,
    )
    assert result.reference_kind is ReferenceKind.SPATIALLY_UNIFORM
    assert any("CONTRAST ONLY" in n for n in result.notes)


def test_a_reference_on_other_cells_is_refused(
    hot_alarm: object, cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]))
    wrong = make_reference(cell_origins[:-1], np.ones(N_CELLS - 1))
    with pytest.raises(MissingReferenceError, match="different cells"):
        score_alarm_set(hot_alarm, catalog, wrong, n_simulations=10)  # type: ignore[arg-type]


def test_a_reference_fitted_after_the_issue_time_is_refused_as_leakage(
    hot_alarm: object, cell_origins: tuple[tuple[float, float], ...], scoring_provenance: Provenance
) -> None:
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]))
    peeking = make_reference(
        cell_origins,
        np.ones(N_CELLS),
        fit_cutoff_iso=(ISSUE + timedelta(days=10)).isoformat(),
    )
    with pytest.raises(LeakyReferenceError, match="saw the window"):
        score_alarm_set(hot_alarm, catalog, peeking, n_simulations=10)  # type: ignore[arg-type]


def test_a_perfect_alarm_on_a_flat_reference_is_significant_and_carries_its_power(
    hot_alarm: object,
    flat_reference: object,
    cell_origins: tuple[tuple[float, float], ...],
    scoring_provenance: Provenance,
) -> None:
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]) * 8)
    result = score_alarm_set(
        hot_alarm,  # type: ignore[arg-type]
        catalog,
        flat_reference,  # type: ignore[arg-type]
        n_simulations=500,
        seed=2,
    )
    assert result.n_target_events == 40
    assert result.declared_hits == 40
    assert result.declared_tau == pytest.approx(0.05)
    assert result.declared_probability_gain == pytest.approx(20.0)
    assert result.significant is True
    assert result.power is not None
    assert result.minimum_detectable_gain is not None
    assert result.area_skill_score is not None
    assert result.area_skill_score > 0.9


def test_a_null_result_states_the_gain_it_could_have_seen(
    flat_reference: object,
    cell_origins: tuple[tuple[float, float], ...],
    scoring_provenance: Provenance,
) -> None:
    """ADR-0055 decision 5: not 'we saw nothing' but 'we could have seen this much'."""
    values = np.zeros(N_CELLS)
    values[:50] = 1.0
    alarm = make_alarm(cell_origins, values)
    catalog = make_catalog(scoring_provenance, list(cell_origins[50:60]) * 6)
    result = score_alarm_set(
        alarm,
        catalog,
        flat_reference,
        n_simulations=500,
        seed=3,  # type: ignore[arg-type]
    )
    assert result.significant is False
    assert result.minimum_detectable_gain is not None
    assert any("null result" in n and "80% power" in n for n in result.notes)


def test_an_alarm_with_no_declared_operating_point_quotes_no_single_gain(
    flat_reference: object,
    cell_origins: tuple[tuple[float, float], ...],
    scoring_provenance: Provenance,
) -> None:
    values = np.linspace(0.0, 1.0, N_CELLS)
    alarm = make_alarm(cell_origins, values, declared_threshold=None)
    catalog = make_catalog(scoring_provenance, list(cell_origins[-5:]))
    result = score_alarm_set(
        alarm,
        catalog,
        flat_reference,
        n_simulations=200,
        seed=4,  # type: ignore[arg-type]
    )
    assert result.declared_probability_gain is None
    assert result.significant is None
    assert result.area_skill_score is not None
    assert any("no operating point was declared" in n for n in result.notes)
    assert any("biased upward" in n for n in result.notes)


def test_events_outside_the_lattice_are_dropped_and_counted(
    hot_alarm: object,
    flat_reference: object,
    cell_origins: tuple[tuple[float, float], ...],
    scoring_provenance: Provenance,
) -> None:
    catalog = make_catalog(scoring_provenance, [(0.0, 0.0), *cell_origins[:2]])
    result = score_alarm_set(
        hot_alarm,
        catalog,
        flat_reference,
        n_simulations=100,
        seed=5,  # type: ignore[arg-type]
    )
    assert result.n_target_events == 2
    assert any("outside every cell" in n for n in result.notes)


def test_a_window_with_no_target_is_undecidable_not_passed(
    hot_alarm: object,
    flat_reference: object,
    cell_origins: tuple[tuple[float, float], ...],
    scoring_provenance: Provenance,
) -> None:
    catalog = make_catalog(scoring_provenance, list(cell_origins[:3]), inside_window=False)
    result = score_alarm_set(
        hot_alarm,
        catalog,
        flat_reference,
        n_simulations=100,
        seed=6,  # type: ignore[arg-type]
    )
    assert result.n_target_events == 0
    assert result.significant is None
    assert result.area_skill_score is None
    assert any("undecidable, not passed" in n for n in result.notes)


def test_every_score_names_the_reference_it_beat(
    hot_alarm: object,
    flat_reference: object,
    cell_origins: tuple[tuple[float, float], ...],
    scoring_provenance: Provenance,
) -> None:
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]))
    result = score_alarm_set(
        hot_alarm,
        catalog,
        flat_reference,
        n_simulations=100,
        seed=7,  # type: ignore[arg-type]
    )
    assert result.reference_id
    assert result.reference_model_id
    assert result.reference_kind
    assert result.scorer_version
    assert any("vintage is not enforced" in n for n in result.notes)


def test_events_below_the_target_magnitude_are_not_targets(
    hot_alarm: object,
    flat_reference: object,
    cell_origins: tuple[tuple[float, float], ...],
    scoring_provenance: Provenance,
) -> None:
    catalog = make_catalog(scoring_provenance, list(cell_origins[:5]), mw=3.0)
    result = score_alarm_set(
        hot_alarm,
        catalog,
        flat_reference,
        n_simulations=50,
        seed=8,  # type: ignore[arg-type]
    )
    assert result.n_target_events == 0
