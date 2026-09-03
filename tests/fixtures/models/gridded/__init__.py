"""Test-only helpers for the gridded challenger.

No event data lives here. Everything comes from the committed real ComCat slice under
``tests/fixtures/forecasting/`` through its loader; this package only defines the small region
and the small configuration that keep the unit suite fast. See ``provenance.json``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from rupture.domain import Region, TectonicSetting
from rupture.models.challengers.gridded import GriddedConfig

#: Cutoff used by the unit suite; well inside the fixture's 2018-01-01 to 2020-01-01 span.
FIXTURE_CUTOFF = datetime(2019, 7, 1, tzinfo=UTC)

#: Mc for the fixture slice. The fixture holds reported preferred magnitudes down to M 3.0, so
#: 3.5 leaves a usable margin; it is passed explicitly and never inferred.
FIXTURE_MC = 3.5


def small_region() -> Region:
    """The fixture's own query box on a coarse lattice: 1120 cells and 21 bins, so a fit is quick.

    The polygon is the box the committed ComCat slice was cut with, because a smaller box holds
    no pre-cutoff events at all — the fixture's seismicity is the 2019 Ridgecrest sequence, which
    is after the cutoff. The cell size is 0.2 degrees rather than the protocol's 0.1 purely to
    keep the unit suite fast. Not one of the protocol regions and never used for a published
    result.
    """
    return Region(
        id="gridded-test-box",
        name="Gridded challenger test box (tests only)",
        polygon=((-122.0, 32.0), (-114.0, 32.0), (-114.0, 37.5), (-122.0, 37.5)),
        depth_max_km=30.0,
        tectonic_setting=TectonicSetting.TRANSFORM,
        cell_size_deg=0.2,
        target_min_magnitude=3.95,
        magnitude_max=5.95,
        description="Test-only rectangle; not one of the protocol regions.",
    )


def small_config(**changes: object) -> GriddedConfig:
    """A configuration sized for the unit suite: a couple of epochs on a few cells."""
    base = {
        "n_frames": 3,
        "hidden_channels": 4,
        "max_epochs": 2,
        "patience": 2,
        "batch_size": 8,
        "training_years": 2.0,
        "inner_validation_years": 0.5,
        "torch_num_threads": 1,
    }
    base.update(changes)
    return GriddedConfig(**base)  # type: ignore[arg-type]
