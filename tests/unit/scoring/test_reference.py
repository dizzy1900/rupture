"""Reference measures: how they are built, what they refuse, and how windows pool."""

from __future__ import annotations

import numpy as np
import pytest

from rupture.domain.alarm import ReferenceKind
from rupture.scoring import reference as refmod
from rupture.scoring.errors import MissingReferenceError
from tests.unit.scoring.conftest import GRID_SIDE, make_reference

N_CELLS = GRID_SIDE * GRID_SIDE


def test_probabilities_must_sum_to_one(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        refmod.ReferenceMeasure(
            id="bad",
            kind=ReferenceKind.CLUSTERING_AWARE,
            model_id="x",
            cell_size_deg=0.1,
            cell_origins=cell_origins,
            probabilities=np.full(N_CELLS, 0.5),
        )


def test_a_reference_with_no_mass_is_refused(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    with pytest.raises(MissingReferenceError, match="carries no mass"):
        refmod.smoothed_seismicity(cell_origins, 0.1, np.zeros(N_CELLS), floor=0.0)


def test_the_uniform_reference_is_weighted_by_area_not_by_cell(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    """A degree square at 35 N is not a degree square at 44 N, and a contrast that got that
    wrong would understate its own point."""
    tall = tuple((-120.0, 35.0 + 5.0 * j) for j in range(8))
    ref = refmod.uniform(tall, 5.0)
    p = ref.probabilities
    assert p[0] > p[-1], "cells nearer the pole must carry less mass"
    assert float(p.sum()) == pytest.approx(1.0)


def test_the_uniform_contrast_keeps_the_expectation_of_what_it_contrasts(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    real = make_reference(cell_origins, np.arange(1.0, N_CELLS + 1.0), expected_events=7.5)
    contrast = refmod.uniform_like(real)
    assert contrast.expected_events == 7.5
    assert contrast.kind is ReferenceKind.SPATIALLY_UNIFORM
    assert contrast.cell_origins == real.cell_origins


def test_smoothing_moves_mass_towards_a_lone_event(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    counts = np.zeros(N_CELLS)
    counts[N_CELLS // 2] = 10.0
    ref = refmod.smoothed_seismicity(cell_origins, 0.1, counts, smoothing_cells=1.0)
    assert ref.kind is ReferenceKind.SPATIALLY_VARYING_POISSON
    assert int(np.argmax(ref.probabilities)) == N_CELLS // 2
    assert float(ref.probabilities.min()) > 0.0, "the floor keeps a quiet cell finite"


def test_pooling_weights_windows_by_what_the_reference_expects_there(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    """A month expecting ten events must outweigh one expecting one."""
    busy = make_reference(cell_origins, np.ones(N_CELLS), expected_events=10.0)
    quiet = make_reference(cell_origins, np.ones(N_CELLS), expected_events=1.0)
    pooled, offsets = refmod.pool([busy, quiet])
    assert pooled.n_cells == 2 * N_CELLS
    assert offsets.tolist() == [0, N_CELLS]
    assert pooled.expected_events == pytest.approx(11.0)
    first = float(pooled.probabilities[:N_CELLS].sum())
    assert first == pytest.approx(10.0 / 11.0)


def test_pooling_refuses_a_window_that_declares_no_expectation(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    good = make_reference(cell_origins, np.ones(N_CELLS), expected_events=1.0)
    bare = make_reference(cell_origins, np.ones(N_CELLS), expected_events=None)
    with pytest.raises(MissingReferenceError, match="expected_events"):
        refmod.pool([good, bare])


def test_pooling_refuses_to_mix_reference_kinds(
    cell_origins: tuple[tuple[float, float], ...],
) -> None:
    honest = make_reference(cell_origins, np.ones(N_CELLS))
    contrast = refmod.uniform(cell_origins, 0.1, expected_events=1.0)
    with pytest.raises(MissingReferenceError, match="different kinds"):
        refmod.pool([honest, contrast])


def test_pooling_nothing_is_refused() -> None:
    with pytest.raises(MissingReferenceError, match="no references"):
        refmod.pool([])
