"""Scorers keyed by hypothesis arm (ADR-0055).

This package imports only :mod:`rupture.domain`, numpy and scipy. That is a deliberate constraint
rather than an accident of layering: ADR-0061 commits rupture to interoperating with CSEP rather
than forking it, pyCSEP has no alarm-forecast class, and code that has not entangled itself with
one repository's domain types is code that can be offered to another.
"""

from rupture.scoring.consistency_power import (
    ConsistencyPowerResult,
    ConsistencyTest,
    RejectionRegion,
    events_needed,
    minimum_detectable_concentration,
    minimum_detectable_rate_multiplier,
    simulated_power,
)
from rupture.scoring.errors import (
    ArmNotImplementedError,
    LeakyReferenceError,
    MissingReferenceError,
    RefusedMetricError,
    ScoringError,
    UniformReferenceRefusedError,
)
from rupture.scoring.registry import (
    ScorerEntry,
    implemented_arms,
    registry_table,
    score,
    scorer_for,
)

__all__ = [
    "ArmNotImplementedError",
    "ConsistencyPowerResult",
    "ConsistencyTest",
    "LeakyReferenceError",
    "MissingReferenceError",
    "RefusedMetricError",
    "RejectionRegion",
    "ScorerEntry",
    "ScoringError",
    "UniformReferenceRefusedError",
    "events_needed",
    "implemented_arms",
    "minimum_detectable_concentration",
    "minimum_detectable_rate_multiplier",
    "registry_table",
    "score",
    "scorer_for",
    "simulated_power",
]
