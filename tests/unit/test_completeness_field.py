"""CompletenessField invariants (ADR-0060): unknown is null, intervals contain the estimate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from rupture.domain import Catalog, CompletenessCell, CompletenessField, McMethod

START = datetime(2019, 1, 1, tzinfo=UTC)
END = datetime(2019, 7, 1, tzinfo=UTC)


def _cell(**overrides: Any) -> CompletenessCell:
    kwargs: dict[str, Any] = {
        "lon": -117.6,
        "lat": 35.7,
        "mc": 2.3,
        "n_events": 40,
        "method": McMethod.MAXIMUM_CURVATURE,
    }
    kwargs.update(overrides)
    return CompletenessCell(**kwargs)


def _field(cells: tuple[CompletenessCell, ...] = (), **overrides: Any) -> CompletenessField:
    kwargs: dict[str, Any] = {
        "region_id": "california",
        "cell_size_deg": 0.5,
        "cells": cells,
        "estimator": "maximum_curvature",
        "window_start": START,
        "window_end": END,
        "computed_at": END,
    }
    kwargs.update(overrides)
    return CompletenessField(**kwargs)


def test_unknown_cell_is_null_not_guessed() -> None:
    cell = _cell(mc=None, n_events=3)
    assert cell.mc is None
    with pytest.raises(ValueError, match="no events cannot have an Mc"):
        _cell(n_events=0)


def test_interval_rules() -> None:
    assert _cell(mc_low=2.1, mc_high=2.6).mc_high == 2.6
    with pytest.raises(ValueError, match="unknown Mc cannot carry an interval"):
        _cell(mc=None, mc_low=2.0, mc_high=2.5)
    with pytest.raises(ValueError, match="both be set"):
        _cell(mc_low=2.0)
    with pytest.raises(ValueError, match="mc_low must be <= mc_high"):
        _cell(mc_low=2.6, mc_high=2.1)
    with pytest.raises(ValueError, match="must contain mc"):
        _cell(mc=3.0, mc_low=2.1, mc_high=2.6)


def test_window_is_half_open_and_non_empty() -> None:
    with pytest.raises(ValueError, match="strictly before"):
        _field(window_end=START)
    with pytest.raises(ValueError, match="strictly before"):
        _field(window_start=END, window_end=START)


def test_one_mc_per_cell() -> None:
    field = _field((_cell(), _cell(lon=-117.1)))
    assert len(field.cells) == 2
    with pytest.raises(ValueError, match="share an origin"):
        _field((_cell(), _cell(mc=2.8)))


def test_catalog_without_a_field_is_labelled_scalar_only(catalog: Catalog) -> None:
    assert catalog.completeness_field is None
    assert catalog.labelled_scalar_only()


def test_catalog_field_label(catalog: Catalog) -> None:
    spatial = catalog.model_copy(update={"completeness_field": _field((_cell(),))})
    assert not spatial.labelled_scalar_only()
    stand_in = catalog.model_copy(
        update={"completeness_field": _field((_cell(),), is_scalar_only=True)}
    )
    assert stand_in.labelled_scalar_only()


def test_field_round_trips_through_json() -> None:
    field = _field((_cell(mc_low=2.1, mc_high=2.6), _cell(lon=-117.1, mc=None, n_events=2)))
    assert CompletenessField.model_validate_json(field.model_dump_json()) == field
