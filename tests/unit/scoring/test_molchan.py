"""The alarm mathematics: trajectory construction, the calibration identity, and the edges."""

from __future__ import annotations

import numpy as np
import pytest

from rupture.scoring import molchan


def _flat(k: int) -> np.ndarray:
    return np.full(k, 1.0 / k, dtype=np.float64)


def test_an_oracle_alarm_covering_one_percent_catches_everything() -> None:
    k, n = 1000, 200
    counts = np.zeros(k, dtype=np.int64)
    counts[:10] = n // 10
    alarm = np.zeros(k)
    alarm[:10] = 1.0
    traj = molchan.trajectory(molchan.group_by_threshold(alarm, _flat(k), counts), n)
    assert molchan.area_skill_score(traj.tau, traj.hit_rate) == pytest.approx(0.995, abs=1e-6)
    assert traj.tau[0] == pytest.approx(0.01)
    assert traj.nu[0] == pytest.approx(0.0)
    assert traj.probability_gain()[0] == pytest.approx(100.0)
    assert traj.p_values()[0] < 1e-9


def test_an_alarm_that_avoids_the_events_scores_below_a_half() -> None:
    k, n = 1000, 200
    counts = np.zeros(k, dtype=np.int64)
    counts[:10] = n // 10
    alarm = np.ones(k)
    alarm[:10] = 0.0
    traj = molchan.trajectory(molchan.group_by_threshold(alarm, _flat(k), counts), n)
    assert molchan.area_skill_score(traj.tau, traj.hit_rate) == pytest.approx(0.005, abs=1e-6)


@pytest.mark.parametrize("n_cells", [500, 4000])
def test_the_calibration_identity_an_alarm_that_is_its_reference_scores_one_half(
    n_cells: int,
) -> None:
    """The one identity everything else rests on. If this drifts, no score can be read."""
    rng = np.random.default_rng(11)
    reference = rng.random(n_cells) ** 4
    reference /= reference.sum()
    scores = []
    for _ in range(60):
        counts = rng.multinomial(130, reference).astype(np.int64)
        traj = molchan.trajectory(molchan.group_by_threshold(reference, reference, counts), 130)
        scores.append(molchan.area_skill_score(traj.tau, traj.hit_rate))
    assert float(np.mean(scores)) == pytest.approx(0.5, abs=0.02)


def test_the_null_distribution_is_centred_on_a_half() -> None:
    rng = np.random.default_rng(3)
    k, n = 800, 150
    reference = rng.random(k)
    reference /= reference.sum()
    alarm = rng.random(k)
    counts = rng.multinomial(n, reference).astype(np.int64)
    groups = molchan.group_by_threshold(alarm, reference, counts)
    null = molchan.area_skill_null(groups, n, n_simulations=3000, rng=np.random.default_rng(4))
    assert float(null.mean()) == pytest.approx(0.5, abs=0.01)
    assert 0.0 < float(null.std()) < 0.1


def test_ties_are_never_broken_by_array_order() -> None:
    """Two cells with the same alarm value must enter the trajectory together."""
    reference = _flat(4)
    counts = np.array([1, 0, 0, 0], dtype=np.int64)
    alarm = np.array([1.0, 1.0, 0.0, 0.0])
    groups = molchan.group_by_threshold(alarm, reference, counts)
    assert len(groups) == 2
    assert groups[0].n_cells == 2
    assert groups[0].reference_mass == pytest.approx(0.5)
    reordered = molchan.group_by_threshold(alarm[::-1], reference, counts[::-1].copy())
    assert [g.n_cells for g in reordered] == [g.n_cells for g in groups]


def test_a_constant_alarm_declares_everything_and_gains_nothing() -> None:
    k, n = 100, 20
    counts = np.zeros(k, dtype=np.int64)
    counts[0] = n
    traj = molchan.trajectory(molchan.group_by_threshold(np.ones(k), _flat(k), counts), n)
    assert traj.tau.size == 1
    assert traj.tau[0] == pytest.approx(1.0)
    assert traj.probability_gain()[0] == pytest.approx(1.0)
    assert traj.p_values()[0] == pytest.approx(1.0)


def test_no_targets_leaves_the_miss_rate_at_one_and_the_p_values_undefined() -> None:
    k = 50
    traj = molchan.trajectory(
        molchan.group_by_threshold(
            np.arange(k, dtype=float), _flat(k), np.zeros(k, dtype=np.int64)
        ),
        0,
    )
    assert np.all(traj.nu == 1.0)
    assert np.all(np.isnan(traj.p_values()))


def test_mismatched_shapes_are_refused() -> None:
    with pytest.raises(ValueError, match="one value per cell"):
        molchan.group_by_threshold(np.ones(3), np.ones(4) / 4, np.zeros(3, dtype=np.int64))


def test_matched_random_relocation_matches_the_footprint_size() -> None:
    rng = np.random.default_rng(5)
    counts = np.zeros(100, dtype=np.int64)
    counts[:5] = 4
    hits = molchan.matched_random_hits(counts, n_alarm_cells=5, n_simulations=500, rng=rng)
    assert hits.size == 500
    assert 0 <= int(hits.max()) <= int(counts.sum())
    assert float(hits.mean()) == pytest.approx(counts.sum() * 5 / 100, rel=0.3)


def test_relocating_more_cells_than_exist_is_refused() -> None:
    with pytest.raises(ValueError, match="within"):
        molchan.matched_random_hits(
            np.zeros(10, dtype=np.int64),
            n_alarm_cells=11,
            n_simulations=1,
            rng=np.random.default_rng(0),
        )
