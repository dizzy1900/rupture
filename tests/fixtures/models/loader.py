"""Test-only loader for the committed NTPP fit of the real ComCat fixture slice.

The fit is a genuine maximum-likelihood fit of ``tests/fixtures/forecasting/
comcat-california-2018-2019-m3.geojson`` at the 2019-07-01 cutoff, produced by
``tests/fixtures/models/make_ntpp_fixture.py`` and never hand-edited. Unit tests load it so they
can exercise forecasting, persistence and the leakage guards without training; training itself is
exercised in ``tests/integration``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rupture.domain import FitResult
from rupture.models.challengers.ntpp import NeuralTPPForecaster, NTPPConfig
from tests.fixtures.forecasting.loader import fixture_region

FIXTURE_DIR = Path(__file__).resolve().parent
NTPP_FIT_DIR = FIXTURE_DIR / "ntpp-fit-2019-07-01"
FIT_CUTOFF = datetime(2019, 7, 1, tzinfo=UTC)
MC = 3.0

#: The configuration frozen by hyperparameter selection on the validation window ending at the
#: cutoff (``hyperparameters.json``, config hash 92c04f36…). Duplicated here so the fixture can be
#: rebuilt from a clean checkout; the frozen record remains authoritative.
FIXTURE_CONFIG: dict[str, Any] = {
    "n_time_basis": 8,
    "n_space_basis": 5,
    "hidden": 8,
    "background_sigma_km": 15.0,
    "weight_decay": 1e-3,
}


def load_ntpp_fit() -> FitResult:
    return FitResult.model_validate_json(
        (NTPP_FIT_DIR / "fit_result.json").read_text(encoding="utf-8")
    )


def load_ntpp_weights() -> dict[str, list[float]]:
    raw: dict[str, list[float]] = json.loads(
        (NTPP_FIT_DIR / "weights.json").read_text(encoding="utf-8")
    )
    return raw


def loaded_model() -> NeuralTPPForecaster:
    """A forecaster with the committed fit loaded and ready to issue."""
    model = NeuralTPPForecaster(NTPPConfig(**FIXTURE_CONFIG), auxiliary_years=0.25)
    model.load_fit(load_ntpp_fit(), fixture_region(), load_ntpp_weights())
    return model


def fit_provenance() -> dict[str, Any]:
    raw: dict[str, Any] = json.loads((NTPP_FIT_DIR / "provenance.json").read_text(encoding="utf-8"))
    return raw
