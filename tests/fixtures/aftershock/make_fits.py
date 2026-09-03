"""Regenerate the committed ETAS fits behind the aftershock gate (offline, real fits, slow).

Run from the repository root::

    uv run python -m tests.fixtures.aftershock.make_fits

For each validation sequence and each scheduled refit cutoff that the issue times in
``rupture.services.aftershock.sequences.ISSUE_OFFSETS`` land on, this runs the real EM fit of
:class:`~rupture.adapters.forecasting.etas_mizrahi.MizrahiETAS` on the committed ComCat slice and
writes ``fits/<sequence>/<cutoff>/fit_result.json`` plus a ``provenance.json`` naming the slice
digest, the configuration and the pinned etas commit.

They exist only so ``make validate-aftershock`` stays inside its time budget: the six fits take
about four minutes together, which is too long for a gate. The fits are deterministic (the
adapter uses a fixed EM starting point), so a rerun reproduces the parameter hashes unless the
slice or the pinned package changes -- which the gate checks by recomputing
``training_catalog_hash`` from the slice it loads.
"""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from rupture.adapters.forecasting.etas_mizrahi import ETAS_COMMIT
from rupture.domain import utc_now
from rupture.services.aftershock.forecaster import AftershockForecaster, scheduled_fit_cutoff
from rupture.services.aftershock.sequences import (
    ISSUE_OFFSETS,
    PROVENANCE_FILE,
    SEQUENCES,
    fits_dir,
    fixture_dir,
    load_parent_region,
    load_sequence_catalog,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    forecaster = AftershockForecaster()
    slice_meta = json.loads((fixture_dir(REPO_ROOT) / PROVENANCE_FILE).read_text(encoding="utf-8"))
    for spec in SEQUENCES.values():
        catalog = load_sequence_catalog(spec, REPO_ROOT)
        parent = load_parent_region(spec, REPO_ROOT)
        region = forecaster.zone(spec.mainshock, parent)
        out_root = fits_dir(spec, REPO_ROOT)
        shutil.rmtree(out_root, ignore_errors=True)
        out_root.mkdir(parents=True, exist_ok=True)
        records: dict[str, object] = {}
        for label, offset in ISSUE_OFFSETS:
            cutoff = scheduled_fit_cutoff(
                spec.mainshock.origin_time, spec.mainshock.origin_time + offset
            )
            started = time.perf_counter()
            fit = forecaster.fit(catalog, region, cutoff)
            runtime = time.perf_counter() - started
            directory = out_root / f"{cutoff:%Y%m%dT%H%M%SZ}"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "fit_result.json").write_text(
                json.dumps(fit.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            records[cutoff.isoformat()] = {
                "issue_label": label,
                "n_events": fit.n_events,
                "mc": fit.mc,
                "converged": fit.converged,
                "iterations": fit.diagnostics["iterations"],
                "branching_ratio": fit.diagnostics["branching_ratio"],
                "b_value": fit.diagnostics["b_value"],
                "beta_fixed": fit.diagnostics["beta_fixed"],
                "at_bound": fit.diagnostics["at_bound"],
                "parameter_snapshot_hash": fit.parameter_snapshot_hash,
                "training_catalog_hash": fit.training_catalog_hash,
                "runtime_s": round(runtime, 1),
            }
            print(  # noqa: T201
                f"{spec.id} {label}: n={fit.n_events} converged={fit.converged} "
                f"branching={fit.diagnostics['branching_ratio']} {runtime:.0f}s"
            )
        (out_root / "provenance.json").write_text(
            json.dumps(
                {
                    "command": "uv run python -m tests.fixtures.aftershock.make_fits",
                    "created_at": utc_now().isoformat(),
                    "sequence": spec.id,
                    "derived_from": spec.fixture_file,
                    "source_sha256": slice_meta["files"][spec.fixture_file]["sha256"],
                    "licence": slice_meta["licence"],
                    "region_id": region.id,
                    "zone_radius_note": (
                        "Wells & Coppersmith (1994) subsurface rupture length x 1.5; see "
                        "rupture.services.aftershock.window"
                    ),
                    "model_id": "etas-mizrahi",
                    "etas_commit": ETAS_COMMIT,
                    "auxiliary_years": forecaster.auxiliary_years,
                    "fix_b_value": forecaster.fix_b_value,
                    "m_max": region.magnitude_max,
                    "mc_source": "parent region Region.mc (published catalogue build)",
                    "fits": records,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"wrote {out_root}")  # noqa: T201


if __name__ == "__main__":
    main()
