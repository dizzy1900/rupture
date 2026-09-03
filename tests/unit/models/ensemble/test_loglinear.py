"""The log-linear pool: algebra, the zero-rate floor, and the weight-fitting protocol."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

import numpy as np
import pytest

from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, ForecastGrid, Region
from rupture.models.ensemble import (
    DEFAULT_FLOOR_FRACTION,
    LogLinearEnsemble,
    combine,
    fit_weights,
    floored_log_rates,
    observed_counts,
    poisson_log_likelihood,
    simplex_grid,
)
from rupture.ports import ForecastModel
from tests.unit.models.ensemble.conftest import ETAS_MC, HORIZON, TEST_CUTOFF, WEIGHTS_CUTOFF

Provider = Callable[[Catalog, datetime, timedelta], ForecastGrid]


# ---------------------------------------------------------------------- algebra
def test_weight_one_reproduces_that_component_up_to_the_floor(
    catalog: Catalog, etas_component: Provider, gridded_component: Provider
) -> None:
    """At weight one the pool is that component with its own floor applied, and nothing else."""
    history = catalog.before(TEST_CUTOFF)
    a = etas_component(history, TEST_CUTOFF, HORIZON)
    b = gridded_component(history, TEST_CUTOFF, HORIZON)
    pooled = combine([a, b], [1.0, 0.0])
    floored = np.exp(floored_log_rates(a.counts(), DEFAULT_FLOOR_FRACTION)[0])
    assert np.allclose(pooled, floored * (a.total_expected() / floored.sum()), rtol=1e-9)


def test_the_floor_moves_at_most_floor_fraction_of_the_mass(
    catalog: Catalog, etas_component: Provider
) -> None:
    """The relative floor adds at most ``floor_fraction`` of the component's own total.

    That bound is the reason the floor is expressed as a fraction of the component's mean rate:
    whatever it does to the far tail of the spatial law, it cannot move the count forecast.
    """
    grid = etas_component(catalog.before(TEST_CUTOFF), TEST_CUTOFF, HORIZON)
    counts = grid.counts()
    floored = np.exp(floored_log_rates(counts, DEFAULT_FLOOR_FRACTION)[0])
    added = float(floored.sum() - counts.sum())
    assert 0.0 <= added <= DEFAULT_FLOOR_FRACTION * float(counts.sum()) * (1.0 + 1e-9)


def test_pool_is_a_geometric_mean_up_to_the_normalisation(
    catalog: Catalog, etas_component: Provider, gridded_component: Provider
) -> None:
    history = catalog.before(TEST_CUTOFF)
    a = etas_component(history, TEST_CUTOFF, HORIZON).counts()
    b = gridded_component(history, TEST_CUTOFF, HORIZON).counts()
    pooled = combine(
        [
            etas_component(history, TEST_CUTOFF, HORIZON),
            gridded_component(history, TEST_CUTOFF, HORIZON),
        ],
        [0.5, 0.5],
    )
    fa, _ = floored_log_rates(a, DEFAULT_FLOOR_FRACTION)
    fb, _ = floored_log_rates(b, DEFAULT_FLOOR_FRACTION)
    expected = np.exp(0.5 * fa + 0.5 * fb)
    ratio = pooled / expected
    assert np.allclose(ratio, ratio.flat[0], rtol=1e-9)


def test_total_is_the_weighted_geometric_mean_of_the_component_totals(
    catalog: Catalog, etas_component: Provider, gridded_component: Provider
) -> None:
    history = catalog.before(TEST_CUTOFF)
    a = etas_component(history, TEST_CUTOFF, HORIZON)
    b = gridded_component(history, TEST_CUTOFF, HORIZON)
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        pooled = combine([a, b], [w, 1.0 - w])
        expected = a.total_expected() ** w * b.total_expected() ** (1.0 - w)
        assert float(pooled.sum()) == pytest.approx(expected, rel=1e-9)


def test_weights_must_lie_on_the_simplex(
    catalog: Catalog, etas_component: Provider, gridded_component: Provider
) -> None:
    history = catalog.before(TEST_CUTOFF)
    grids = [
        etas_component(history, TEST_CUTOFF, HORIZON),
        gridded_component(history, TEST_CUTOFF, HORIZON),
    ]
    with pytest.raises(ValueError, match="sum to 1"):
        combine(grids, [0.5, 0.7])
    with pytest.raises(ValueError, match="non-negative"):
        combine(grids, [-0.5, 1.5])
    with pytest.raises(ValueError, match="one weight per component"):
        combine(grids, [1.0])


def test_simplex_grid_is_a_simplex() -> None:
    points = simplex_grid(3, 0.25)
    assert all(abs(sum(p) - 1.0) < 1e-9 for p in points)
    assert all(min(p) >= 0.0 for p in points)
    assert (1.0, 0.0, 0.0) in points
    assert len(points) == len({p for p in points})


# ---------------------------------------------------------------------- the floor
def test_floor_is_relative_to_the_component_s_own_mean_rate() -> None:
    counts = np.zeros((4, 3), dtype=np.float64)
    counts[0, 0] = 12.0
    logs, floor = floored_log_rates(counts, 1e-6)
    assert floor == pytest.approx(1e-6 * 12.0 / 12)
    assert np.isfinite(logs).all()
    assert logs[1, 1] == pytest.approx(np.log(floor))


def test_a_zero_rate_cell_does_not_take_the_pool_to_minus_infinity(
    catalog: Catalog, etas_component: Provider, gridded_component: Provider
) -> None:
    history = catalog.before(TEST_CUTOFF)
    a = etas_component(history, TEST_CUTOFF, HORIZON)
    b = gridded_component(history, TEST_CUTOFF, HORIZON)
    zeroed = b.model_copy(
        update={
            "expected_counts": tuple(tuple(0.0 for _ in row) for row in b.expected_counts[:1])
            + b.expected_counts[1:]
        }
    )
    pooled = combine([a, zeroed], [0.5, 0.5])
    assert np.all(np.isfinite(pooled))
    assert np.all(pooled >= 0.0)
    assert float(pooled[0].sum()) > 0.0


# ---------------------------------------------------------------------- weight fitting
def test_weight_fitting_prefers_the_component_that_scored_better(
    catalog: Catalog, region: Region, etas_component: Provider, gridded_component: Provider
) -> None:
    """A component that is simply the observed counts, smoothed, must win over one that is not."""
    history = catalog.before(WEIGHTS_CUTOFF)
    good = etas_component(history, WEIGHTS_CUTOFF, HORIZON)
    target = catalog.between(WEIGHTS_CUTOFF, WEIGHTS_CUTOFF + HORIZON)
    counts = observed_counts(target, good)
    if counts.sum() == 0:  # pragma: no cover - the fixture window holds Ridgecrest
        pytest.skip("no target events in the window")
    oracle_counts = counts + 1e-6
    oracle = good.model_copy(
        update={"expected_counts": tuple(tuple(float(v) for v in row) for row in oracle_counts)}
    )
    values, ll, _ = fit_weights([[oracle, good]], [counts], ["oracle", "etas"])
    assert values[0] > values[1]
    assert ll > poisson_log_likelihood(good.counts(), counts)


def test_single_component_weight_is_one(catalog: Catalog, etas_component: Provider) -> None:
    history = catalog.before(TEST_CUTOFF)
    grid = etas_component(history, TEST_CUTOFF, HORIZON)
    counts = observed_counts(catalog.between(TEST_CUTOFF, TEST_CUTOFF + HORIZON), grid)
    values, _, _ = fit_weights([[grid]], [counts], ["etas"])
    assert values == (1.0,)


def test_observed_counts_keep_only_the_evaluator_s_events(
    catalog: Catalog, etas_component: Provider
) -> None:
    history = catalog.before(TEST_CUTOFF)
    grid = etas_component(history, TEST_CUTOFF, HORIZON)
    target = catalog.between(TEST_CUTOFF, TEST_CUTOFF + HORIZON)
    counts = observed_counts(target, grid)
    threshold = grid.magnitude_bin_edges[0]
    eligible = [e for e in target.earthquakes().events if e.mw is not None and e.mw >= threshold]
    assert 0 < counts.sum() <= len(eligible)


# ---------------------------------------------------------------------- the model
def test_ensemble_satisfies_the_forecast_model_port(
    etas_component: Provider, gridded_component: Provider
) -> None:
    model = LogLinearEnsemble({"etas": etas_component, "gridded": gridded_component})
    assert isinstance(model, ForecastModel)


def test_fit_refuses_without_a_validation_window(
    catalog: Catalog, region: Region, etas_component: Provider, gridded_component: Provider
) -> None:
    model = LogLinearEnsemble({"etas": etas_component, "gridded": gridded_component})
    with pytest.raises(ValueError, match="no validation issue times"):
        model.fit(catalog, region, TEST_CUTOFF)


def test_fit_refuses_a_validation_window_that_reaches_the_test_cutoff(
    catalog: Catalog, region: Region, etas_component: Provider, gridded_component: Provider
) -> None:
    too_late = [TEST_CUTOFF - timedelta(days=29)]
    model = LogLinearEnsemble(
        {"etas": etas_component, "gridded": gridded_component},
        validation_issue_times=too_late,
        horizon=HORIZON,
    )
    with pytest.raises(ValueError, match="reaches past the test cutoff"):
        model.fit(catalog, region, TEST_CUTOFF)


def test_fitted_ensemble_issues_a_grid_on_the_component_lattice(
    catalog: Catalog,
    region: Region,
    etas_component: Provider,
    gridded_component: Provider,
    validation_times: list[datetime],
) -> None:
    model = LogLinearEnsemble(
        {"etas": etas_component, "gridded": gridded_component},
        validation_issue_times=validation_times,
        horizon=HORIZON,
    )
    fit = model.fit(catalog, region, TEST_CUTOFF)
    assert fit.model_id == "ensemble-loglinear"
    assert set(fit.parameters) == {"w_etas", "w_gridded", "floor_fraction"}
    assert fit.parameters["w_etas"] + fit.parameters["w_gridded"] == pytest.approx(1.0)
    weights = model.weights
    assert weights is not None
    assert weights.validation_windows == len(validation_times)

    grid = model.forecast(catalog.before(TEST_CUTOFF), TEST_CUTOFF, HORIZON)
    reference = etas_component(catalog.before(TEST_CUTOFF), TEST_CUTOFF, HORIZON)
    assert grid.cell_origins == reference.cell_origins
    assert grid.magnitude_bin_edges == reference.magnitude_bin_edges
    assert grid.parameter_snapshot_hash == fit.parameter_snapshot_hash
    assert grid.total_expected() > 0.0
    assert model.parameter_snapshot()["components"] == ["etas", "gridded"]


def test_unfitted_ensemble_refuses_to_issue(
    catalog: Catalog, etas_component: Provider, gridded_component: Provider
) -> None:
    model = LogLinearEnsemble({"etas": etas_component, "gridded": gridded_component})
    with pytest.raises(RuntimeError, match="no weights"):
        model.forecast(catalog.before(TEST_CUTOFF), TEST_CUTOFF, HORIZON)
    assert model.parameter_snapshot() == {}


def test_forecast_refuses_a_history_reaching_the_issue_time(
    catalog: Catalog,
    region: Region,
    etas_component: Provider,
    gridded_component: Provider,
    validation_times: list[datetime],
) -> None:
    model = LogLinearEnsemble(
        {"etas": etas_component, "gridded": gridded_component},
        validation_issue_times=validation_times,
        horizon=HORIZON,
    )
    model.fit(catalog, region, TEST_CUTOFF)
    with pytest.raises(LeakageError, match="ensemble forecast history"):
        model.forecast(catalog.before(TEST_CUTOFF + timedelta(days=10)), TEST_CUTOFF, HORIZON)


def test_components_on_different_lattices_are_refused(
    catalog: Catalog,
    region: Region,
    other_region: Region,
    etas_component: Provider,
    validation_times: list[datetime],
) -> None:
    """A component whose grid does not match the others is an error, not something to reconcile."""
    from rupture.models.challengers.gridded import GriddedChallenger  # noqa: PLC0415
    from tests.fixtures.models.gridded import small_config  # noqa: PLC0415

    other = GriddedChallenger(
        small_config(training_years=1.5, inner_validation_years=0.25), faults_path=None
    )
    other.fit(catalog, other_region, WEIGHTS_CUTOFF, mc=ETAS_MC)

    def other_provider(history: Catalog, issue_time: datetime, horizon: timedelta) -> ForecastGrid:
        return other.forecast(history, issue_time, horizon)

    model = LogLinearEnsemble(
        {"etas": etas_component, "other": other_provider},
        validation_issue_times=validation_times,
        horizon=HORIZON,
    )
    with pytest.raises(ValueError, match="disagree on cells"):
        model.fit(catalog, region, TEST_CUTOFF)


def test_load_weights_requires_the_same_component_names(
    catalog: Catalog,
    region: Region,
    etas_component: Provider,
    gridded_component: Provider,
    validation_times: list[datetime],
) -> None:
    source = LogLinearEnsemble(
        {"etas": etas_component, "gridded": gridded_component},
        validation_issue_times=validation_times,
        horizon=HORIZON,
    )
    fit = source.fit(catalog, region, TEST_CUTOFF)
    weights = source.weights
    assert weights is not None

    same = LogLinearEnsemble({"etas": etas_component, "gridded": gridded_component})
    same.load_weights(weights, fit)
    assert same.weights == weights

    different = LogLinearEnsemble({"etas": etas_component})
    with pytest.raises(ValueError, match="were fitted for components"):
        different.load_weights(weights, fit)


def test_the_component_list_is_configurable(
    catalog: Catalog, region: Region, etas_component: Provider, validation_times: list[datetime]
) -> None:
    """ETAS alone is a legal ensemble, which is what makes the component list configurable."""
    model = LogLinearEnsemble(
        {"etas": etas_component}, validation_issue_times=validation_times, horizon=HORIZON
    )
    fit = model.fit(catalog, region, TEST_CUTOFF)
    assert fit.parameters["w_etas"] == 1.0
    grid = model.forecast(catalog.before(TEST_CUTOFF), TEST_CUTOFF, HORIZON)
    reference = etas_component(catalog.before(TEST_CUTOFF), TEST_CUTOFF, HORIZON)
    assert grid.total_expected() == pytest.approx(reference.total_expected(), rel=1e-9)


def test_an_empty_component_list_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one component"):
        LogLinearEnsemble({})
