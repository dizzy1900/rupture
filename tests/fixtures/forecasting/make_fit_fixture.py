"""Regenerate the committed ETAS fit of the fixture (a real fit of real data; never hand-edited).

Run from the repository root::

    uv run python -m tests.fixtures.forecasting.make_fit_fixture

Writes ``tests/fixtures/forecasting/fit-2019-07-01/`` (``fit_result.json``, ``parameters.json``,
``diagnostics.json``) plus ``provenance.json`` recording the fixture digest, the configuration and
the etas commit. The fit is deterministic (fixed EM start), so a rerun reproduces the hash unless
the fixture or the pinned package changes.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime

from rupture.adapters.forecasting.etas_mizrahi import ETAS_COMMIT, MizrahiETAS, save_fit
from rupture.domain import utc_now
from tests.fixtures.forecasting.loader import (
    FIXTURE_DIR,
    PROVENANCE,
    fixture_region,
    load_fixture_catalog,
)

FIT_CUTOFF = datetime(2019, 7, 1, tzinfo=UTC)
AUXILIARY_YEARS = 0.5
MC = 3.0
OUT_DIR = FIXTURE_DIR / "fit-2019-07-01"


def main() -> None:
    catalog = load_fixture_catalog()
    region = fixture_region()
    model = MizrahiETAS(auxiliary_years=AUXILIARY_YEARS)
    fit = model.fit(catalog, region, FIT_CUTOFF, mc=MC)
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    written = save_fit(fit, OUT_DIR)
    # save_fit nests under etas/<region>/; flatten into OUT_DIR for a compact fixture.
    for p in written.iterdir():
        shutil.move(str(p), OUT_DIR / p.name)
    shutil.rmtree(OUT_DIR / "etas")
    # save_fit also archives the fit under fits/<cutoff>/; for a fixture of one fit at one cutoff
    # that is a byte-identical second copy, so it is dropped and a rerun stays reproducible.
    shutil.rmtree(OUT_DIR / "fits", ignore_errors=True)
    source = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    provenance = {
        "derived_from": source["file"],
        "source_sha256": source["sha256"],
        "command": "uv run python -m tests.fixtures.forecasting.make_fit_fixture",
        "created_at": utc_now().isoformat(),
        "model_id": fit.model_id,
        "model_version": fit.model_version,
        "etas_commit": ETAS_COMMIT,
        "fit_cutoff": FIT_CUTOFF.isoformat(),
        "auxiliary_years": AUXILIARY_YEARS,
        "mc": MC,
        "mc_note": "3.0 is the fixture's ComCat query floor, passed explicitly; not a fitted Mc",
        "magnitudes": "reported ComCat magnitudes used as mw (loader reported_as_mw=True)",
        "parameter_snapshot_hash": fit.parameter_snapshot_hash,
        "training_catalog_hash": fit.training_catalog_hash,
        "n_events": fit.n_events,
        "licence": source["licence"],
    }
    (OUT_DIR / "provenance.json").write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT_DIR} snapshot={fit.parameter_snapshot_hash[:12]}")  # noqa: T201


if __name__ == "__main__":
    main()
