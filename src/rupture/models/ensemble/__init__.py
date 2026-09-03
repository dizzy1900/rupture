"""Log-linear ensemble of the ETAS baseline with any challenger.

See ``docs/CHALLENGER_ENSEMBLE.md`` and ADR-0032. rupture does not predict earthquakes.
"""

from rupture.models.ensemble.loglinear import (
    DEFAULT_FLOOR_FRACTION,
    MODEL_ID,
    MODEL_VERSION,
    Component,
    EnsembleWeights,
    LogLinearEnsemble,
    combine,
    fit_weights,
    floored_log_rates,
    observed_counts,
    poisson_log_likelihood,
    simplex_grid,
)

__all__ = [
    "DEFAULT_FLOOR_FRACTION",
    "MODEL_ID",
    "MODEL_VERSION",
    "Component",
    "EnsembleWeights",
    "LogLinearEnsemble",
    "combine",
    "fit_weights",
    "floored_log_rates",
    "observed_counts",
    "poisson_log_likelihood",
    "simplex_grid",
]
