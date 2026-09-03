"""A schedule's refits must not destroy the fit that the fit_etas stage declares."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rupture.adapters.forecasting.etas_mizrahi import archive_dir, load_fit, save_fit
from rupture.domain import FitResult, snapshot_hash


def _fit(cutoff: datetime, mu: float) -> FitResult:
    params = {"log10_mu": mu, "beta": 2.3}
    return FitResult(
        model_id="etas-mizrahi",
        model_version="t",
        region_id="r",
        fit_cutoff=cutoff,
        training_start=datetime(1976, 1, 1, tzinfo=UTC),
        training_catalog_hash="h",
        n_events=10,
        mc=4.0,
        parameters=params,
        parameter_snapshot_hash=snapshot_hash(params),
        fitted_at=cutoff,
    )


def test_refit_archives_rather_than_destroys(tmp_path: Path) -> None:
    first = _fit(datetime(2022, 1, 1, tzinfo=UTC), -7.0)
    later = _fit(datetime(2026, 1, 1, tzinfo=UTC), -6.0)
    save_fit(first, tmp_path)
    save_fit(later, tmp_path)

    # the top level is the most recent fit, which is what load_fit reads
    assert load_fit(tmp_path, "r").fit_cutoff == later.fit_cutoff

    # and the declared-cutoff fit is still recoverable, byte for byte
    kept = archive_dir(tmp_path, "r", first.fit_cutoff) / "fit_result.json"
    assert kept.exists(), "a refit destroyed the baseline the fit_etas stage declares"
    recovered = FitResult.model_validate(json.loads(kept.read_text()))
    assert recovered.parameter_snapshot_hash == first.parameter_snapshot_hash
    assert recovered.parameters["log10_mu"] == -7.0
