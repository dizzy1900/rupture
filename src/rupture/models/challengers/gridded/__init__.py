"""C1b: a gridded spatio-temporal challenger (ConvLSTM) on the region's own lattice.

See ``docs/CHALLENGER_GRIDDED.md`` and ADR-0031.
"""

from rupture.models.challengers.gridded.challenger import (
    MODEL_ID,
    MODEL_VERSION,
    GriddedChallenger,
    GriddedConfig,
    archive_dir,
    fit_dir,
    load_fit,
    save_fit,
)

__all__ = [
    "MODEL_ID",
    "MODEL_VERSION",
    "GriddedChallenger",
    "GriddedConfig",
    "archive_dir",
    "fit_dir",
    "load_fit",
    "save_fit",
]
