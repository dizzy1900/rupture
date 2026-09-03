"""C1a: a neural temporal point process challenger to the ETAS baseline.

A marked spatio-temporal Hawkes process whose triggering kernels are convex mixtures over Omori
and power-law bases, with the mixture weights and productivity produced by a small MLP from each
event's own magnitude and depth. The likelihood and its compensator are exact; the forecast is
Monte Carlo simulation of the branching process onto the protocol lattice.

Modules: :mod:`kernels` (basis functions and their integrals), :mod:`model` (the ``nn.Module``,
features and log-likelihood), :mod:`simulate` (branching-process sampler), :mod:`adapter` (the
``ForecastModel`` implementation and persistence), :mod:`train` (hyperparameter selection on a
validation window only), :mod:`schedule` (the pseudo-prospective run and the ETAS comparison),
:mod:`ablation` (the deliberately leaky variants, which are never results).

See ``docs/CHALLENGER_NTPP.md`` and ADR-0029. The expected outcome is that this does not beat
ETAS; a negative result established without leakage is the deliverable.
"""

from __future__ import annotations

from rupture.models.challengers.ntpp.adapter import (
    MODEL_ID,
    NeuralTPPForecaster,
    load_saved_fit,
    save_fit,
)
from rupture.models.challengers.ntpp.model import NTPPConfig

__all__ = ["MODEL_ID", "NTPPConfig", "NeuralTPPForecaster", "load_saved_fit", "save_fit"]
