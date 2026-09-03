"""Training the challenger end to end on the committed fixture. Offline, but slow.

Marked ``integration`` because it optimises a real model on real data (tens of seconds), which
does not belong in the unit suite. It needs no network and no Docker: everything it reads is
committed. Run it with ``uv run pytest tests/integration -m integration -k ntpp``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rupture.adapters.forecasting.leakage import LeakageError
from rupture.models.challengers.ntpp import NeuralTPPForecaster, NTPPConfig
from rupture.models.challengers.ntpp.train import (
    candidate_configs,
    freeze,
    load_frozen,
    select_config,
)
from rupture.models.data import build_sequence
from tests.fixtures.forecasting.loader import fixture_region, load_fixture_catalog
from tests.fixtures.models.loader import FIT_CUTOFF, FIXTURE_CONFIG, MC, load_ntpp_fit

pytestmark = pytest.mark.integration

TRAIN_START = datetime(2018, 1, 1, tzinfo=UTC)
AUX_YEARS = 0.25


def test_the_committed_fixture_fit_is_reproducible() -> None:
    """A fixed seed and the frozen configuration must reproduce the published snapshot hash.

    This is the determinism claim the model card makes, checked against the artefact rather than
    against itself. If torch or the fixture changes, this fails and the fixture is regenerated
    with ``tests/fixtures/models/make_ntpp_fixture.py`` — never edited by hand.
    """
    model = NeuralTPPForecaster(NTPPConfig(**FIXTURE_CONFIG), auxiliary_years=AUX_YEARS)
    fit = model.fit(load_fixture_catalog(), fixture_region(), FIT_CUTOFF, mc=MC)
    committed = load_ntpp_fit()
    assert fit.parameter_snapshot_hash == committed.parameter_snapshot_hash
    assert fit.training_catalog_hash == committed.training_catalog_hash
    assert fit.converged is True


def test_training_improves_the_likelihood_and_learns_a_plausible_b_value() -> None:
    model = NeuralTPPForecaster(NTPPConfig(**FIXTURE_CONFIG), auxiliary_years=AUX_YEARS)
    fit = model.fit(load_fixture_catalog(), fixture_region(), FIT_CUTOFF, mc=MC)
    diagnostics = fit.diagnostics
    assert diagnostics["final_nll"] < diagnostics["initial_nll"]
    # The Gutenberg-Richter b-value is fitted, not assumed; California sits near 1.
    assert 0.7 < diagnostics["b_value"] < 1.4
    assert diagnostics["log_likelihood"]["n_events"] > 0


def test_a_fit_never_sees_an_event_at_or_after_its_cutoff() -> None:
    catalog = load_fixture_catalog()
    region = fixture_region()
    clean = catalog.earthquakes().before(FIT_CUTOFF).at_least(MC)
    late = clean.events[-1].model_copy(update={"id": "late", "origin_time": FIT_CUTOFF})
    model = NeuralTPPForecaster(NTPPConfig(**FIXTURE_CONFIG), auxiliary_years=AUX_YEARS)
    # The explicit slice removes it; nothing else does, and the builder proves the slice ran.
    fit = model.fit(catalog, region, FIT_CUTOFF, mc=MC)
    assert datetime.fromisoformat(fit.diagnostics["training_max_origin_time"]) < FIT_CUTOFF
    dirty = clean.model_copy(update={"events": (*clean.events, late)})
    with pytest.raises(LeakageError):
        build_sequence(dirty, region, FIT_CUTOFF, mc=MC)


def test_hyperparameter_selection_freezes_a_configuration_and_refuses_to_peek(
    tmp_path: Path,
) -> None:
    catalog = load_fixture_catalog()
    region = fixture_region()
    # A two-candidate grid keeps this test to a minute; the real run uses the full grid.
    candidates = candidate_configs(grid={"hidden": (8, 16)})
    selection = select_config(
        catalog,
        region,
        mc=MC,
        train_start=TRAIN_START,
        validation_end=FIT_CUTOFF,
        hard_cutoff=FIT_CUTOFF,
        candidates=candidates,
        n_folds=2,
        auxiliary_years=AUX_YEARS,
    )
    assert len(selection.trials) == len(candidates)
    assert all(s.val_end <= FIT_CUTOFF for s in selection.splits)
    assert all(s.train_end <= s.val_start for s in selection.splits)
    path = freeze(selection, tmp_path)
    config, record = load_frozen(path)
    assert config == selection.chosen
    assert record["chosen_config_hash"] == selection.chosen_hash
    assert record["hard_cutoff"] == FIT_CUTOFF.isoformat()

    with pytest.raises(LeakageError, match="after the hard cutoff"):
        select_config(
            catalog,
            region,
            mc=MC,
            train_start=TRAIN_START,
            validation_end=FIT_CUTOFF + timedelta(days=30),
            hard_cutoff=FIT_CUTOFF,
            candidates=candidates[:1],
            n_folds=1,
            auxiliary_years=AUX_YEARS,
        )
