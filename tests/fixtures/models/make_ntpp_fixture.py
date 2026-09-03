"""Regenerate the committed NTPP fit of the fixture catalogue (a real fit of real data).

Run from the repository root::

    uv run python -m tests.fixtures.models.make_ntpp_fixture

Writes ``tests/fixtures/models/ntpp-fit-2019-07-01/`` (``fit_result.json``, ``parameters.json``,
``diagnostics.json``, ``weights.json``) plus ``provenance.json``. The fit is deterministic — torch
and numpy are both seeded from the configuration — so a rerun reproduces the snapshot hash unless
the fixture catalogue, the configuration or the model code changes.

The configuration written here is the one frozen by ``rupture challenger ntpp select`` on the
validation window; it is duplicated as :data:`FIXTURE_CONFIG` so the fixture can be rebuilt from a
clean checkout without rerunning the selection. If the two ever disagree, the frozen
``hyperparameters.json`` is authoritative and this constant is stale.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime

from rupture.domain import utc_now
from rupture.models.challengers.ntpp import NeuralTPPForecaster, NTPPConfig
from rupture.models.challengers.ntpp.adapter import fit_dir, save_fit
from tests.fixtures.forecasting.loader import PROVENANCE, fixture_region, load_fixture_catalog
from tests.fixtures.models.loader import FIT_CUTOFF, FIXTURE_CONFIG, MC, NTPP_FIT_DIR

AUXILIARY_YEARS = 0.25


def main() -> None:
    catalog = load_fixture_catalog()
    region = fixture_region()
    model = NeuralTPPForecaster(NTPPConfig(**FIXTURE_CONFIG), auxiliary_years=AUXILIARY_YEARS)
    fit = model.fit(catalog, region, FIT_CUTOFF, mc=MC)
    shutil.rmtree(NTPP_FIT_DIR, ignore_errors=True)
    NTPP_FIT_DIR.mkdir(parents=True, exist_ok=True)
    written = save_fit(fit, model.state_dict_json(), NTPP_FIT_DIR)
    # save_fit nests under ntpp/<region>/; flatten into the fixture directory.
    for path in written.iterdir():
        if path.is_file():
            shutil.move(str(path), NTPP_FIT_DIR / path.name)
    shutil.rmtree(fit_dir(NTPP_FIT_DIR, region.id).parent, ignore_errors=True)
    source = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    (NTPP_FIT_DIR / "provenance.json").write_text(
        json.dumps(
            {
                "derived_from": source["file"],
                "source_sha256": source["sha256"],
                "command": "uv run python -m tests.fixtures.models.make_ntpp_fixture",
                "created_at": utc_now().isoformat(),
                "model_id": fit.model_id,
                "model_version": fit.model_version,
                "fit_cutoff": FIT_CUTOFF.isoformat(),
                "auxiliary_years": AUXILIARY_YEARS,
                "mc": MC,
                "mc_note": "3.0 is the fixture's ComCat query floor, passed explicitly",
                "magnitudes": "reported ComCat magnitudes used as mw (loader reported_as_mw=True)",
                "config_hash": fit.diagnostics["config_hash"],
                "parameter_snapshot_hash": fit.parameter_snapshot_hash,
                "training_catalog_hash": fit.training_catalog_hash,
                "n_events": fit.n_events,
                "converged": fit.converged,
                "licence": source["licence"],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(  # noqa: T201 - a script, not library code
        f"wrote {NTPP_FIT_DIR} snapshot={fit.parameter_snapshot_hash[:12]} "
        f"converged={fit.converged}"
    )


if __name__ == "__main__":
    assert datetime(2019, 7, 1, tzinfo=UTC) == FIT_CUTOFF
    main()
