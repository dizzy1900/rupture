"""Re-cut the committed ForecastGrid slice the offline risk tests sample event sets from.

Run by hand after re-issuing the Nepal forecast; needs ``data/forecasts/`` to be populated, which
needs the DVC pipeline (catalogue build, ETAS fit, issue) and therefore network::

    uv run rupture catalog build --region nepal-himalaya --from 1976-01-01 --to 2026-08-01
    uv run rupture forecast fit --model etas --region nepal-himalaya --cutoff 2022-01-01T00:00:00Z
    uv run rupture forecast issue --model etas --region nepal-himalaya --horizon 1y \\
        --issue 2026-08-01T00:00:00Z
    uv run python tests/fixtures/risk/forecast/refresh.py

**The fixture is a real slice, never a synthesised grid.** It is the cells of a real issued
``ForecastGrid`` that lie inside a box around the Trishuli corridor, with their expected counts
carried through unchanged. Because it is a slice, its total rate is a fraction of the region's
and an annual loss computed from it is correspondingly smaller: the fixture exists to prove the
F1-to-F2 join runs offline on real forecast output, not to state the corridor's annual loss.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from rupture.adapters.storage.zarr_store import ZarrGridStore
from rupture.domain.forecast import ForecastGrid

HERE = Path(__file__).parent
REPO_ROOT = HERE.parents[3]
GRID_ID = "etas-mizrahi-nepal-himalaya-20260801T000000Z-365d"
OUT = HERE / "trishuli-corridor-slice.json"
BOX = (84.7, 27.5, 85.9, 28.6)
"""(min lon, min lat, max lon, max lat) around the Trishuli corridor, in degrees."""


def slice_grid(grid: ForecastGrid, box: tuple[float, float, float, float]) -> ForecastGrid:
    """The cells of ``grid`` whose lower-left corner lies in ``box``, counts unchanged."""
    lon0, lat0, lon1, lat1 = box
    keep = [
        index
        for index, (lon, lat) in enumerate(grid.cell_origins)
        if lon0 <= lon <= lon1 and lat0 <= lat <= lat1
    ]
    if not keep:
        msg = f"no cell of {grid.id} lies in {box}"
        raise ValueError(msg)
    return grid.model_copy(
        update={
            "id": f"{grid.id}-trishuli-slice",
            "cell_origins": tuple(grid.cell_origins[i] for i in keep),
            "expected_counts": tuple(grid.expected_counts[i] for i in keep),
            "notes": (
                f"REAL SLICE of {grid.id}: the {len(keep)} of {len(grid.cell_origins)} cells "
                f"whose lower-left corner lies in {box}. Expected counts are carried through "
                "unchanged, so the slice's total rate is a fraction of the region's."
            ),
        }
    )


def refresh() -> None:
    grid = ZarrGridStore(REPO_ROOT / "data" / "forecasts").load(GRID_ID)
    sliced = slice_grid(grid, BOX)
    payload = json.dumps(sliced.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)
    OUT.write_text(payload + "\n", encoding="utf-8")
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    provenance = {
        "source": "rupture.forecast.issue (etas-mizrahi)",
        "source_url": None,
        "retrieved_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "licence": "Apache-2.0 (rupture); derived from the ComCat/ISC/GCMT catalogue build",
        "parent_grid_id": grid.id,
        "region_id": grid.region_id,
        "model_id": grid.model_id,
        "model_version": grid.model_version,
        "fit_cutoff": grid.fit_cutoff.isoformat(),
        "issue_time": grid.issue_time.isoformat(),
        "training_catalog_hash": grid.training_catalog_hash,
        "parameter_snapshot_hash": grid.parameter_snapshot_hash,
        "bbox": list(BOX),
        "cells_kept": len(sliced.cell_origins),
        "cells_in_parent": len(grid.cell_origins),
        "parent_total_expected": grid.total_expected(),
        "slice_total_expected": sliced.total_expected(),
        "notes": (
            "A real slice of a real issued ForecastGrid, not a synthesised one. The parent grid "
            "was issued from the ETAS baseline fitted with a hard cutoff at fit_cutoff; no event "
            "at or after that cutoff reached the fit. The slice's rates are a fraction of the "
            "region's, so an annual loss computed from it is not the corridor's annual loss."
        ),
        "files": [{"file": OUT.name, "sha256": digest, "bytes": len(payload) + 1}],
    }
    (HERE / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    print(f"{OUT.name}: {len(payload) + 1} bytes, {len(sliced.cell_origins)} cells")  # noqa: T201


if __name__ == "__main__":
    refresh()
