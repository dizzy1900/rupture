"""Shared, model-agnostic dataset and cross-validation machinery for learned models.

This package is the single place rupture's learned models turn a :class:`~rupture.domain.Catalog`
into tensors, and it exists so that the leakage rules of ADR-0022 are implemented once rather than
once per model. Four modules, one rule each:

======================  =====================================================================
:mod:`dataset`          builders take a hard ``cutoff`` and **raise** on any event at or after
                        it (decision 1); :func:`causal_slice` is the separate, explicit filter
:mod:`windows`          feature windows are closed-left, open-right: a feature at *t* sees only
                        ``origin_time < t`` (decision 2)
:mod:`splits`           blocked time-forward folds only; there is no shuffle parameter to pass
                        (decision 3)
:mod:`normalise`        statistics are fitted on training rows only and travel with the model
                        (decision 5)
======================  =====================================================================

:mod:`geo` holds the azimuthal-equidistant projection to kilometres that EarthquakeNPP's dataset
convention calls for.

Both views of a catalogue are built here. :class:`EventSequence` is the marked point-process view
(one row per event) and :class:`GridCounts` is the raster view (counts per time bin, cell and
magnitude bin, on exactly the protocol lattice). A model consuming either one emits forecasts on
the same grid and bins as the ETAS baseline, which is what makes a pycsep comparison meaningful.
"""

from __future__ import annotations

from rupture.models.data.dataset import (
    EventSequence,
    GridCounts,
    SequenceSpec,
    build_grid_counts,
    build_sequence,
    causal_slice,
    days_between,
    epoch_plus_days,
    time_edges,
)
from rupture.models.data.geo import Projection
from rupture.models.data.normalise import Standardiser
from rupture.models.data.splits import (
    BlockedSplit,
    blocked_splits,
    iter_blocked_splits,
    split_indices,
)
from rupture.models.data.windows import (
    causal_bounds,
    causal_feature_matrix,
    n_strictly_before,
    rolling_count,
    rolling_reduce,
    time_since_previous,
)

__all__ = [
    "BlockedSplit",
    "EventSequence",
    "GridCounts",
    "Projection",
    "SequenceSpec",
    "Standardiser",
    "blocked_splits",
    "build_grid_counts",
    "build_sequence",
    "causal_bounds",
    "causal_feature_matrix",
    "causal_slice",
    "days_between",
    "epoch_plus_days",
    "iter_blocked_splits",
    "n_strictly_before",
    "rolling_count",
    "rolling_reduce",
    "split_indices",
    "time_edges",
    "time_since_previous",
]
