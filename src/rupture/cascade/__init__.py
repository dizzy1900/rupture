"""C3, triggered cascades: earthquake-induced ground failure and co-seismic slope exposure.

Everything in this package produces **susceptibility and exposure** products. They say where
ground failure is more or less likely given shaking and terrain; they do not state that a
particular slope fails, and the domain records carry that caveat in their own payload so a
downstream reader cannot lose it.

Layout:

``coefficients``
    The published coefficient tables, with the provenance of every number.
``covariates``
    Static conditioning factors, and the rule that an unavailable covariate is a declared gap.
``models``
    Nowicki Jessee et al. (2018) landslide and Zhu et al. (2017) liquefaction.
``exposure``
    Overlay of a scenario ground-motion field on slope units, for the co-seismic ice/rock
    avalanche mechanism.
``discriminator``
    Client for the ``SourceTypeAssessment`` file contract shared with the sibling ``serac``.
"""

from rupture.cascade.coefficients import (
    MODELS,
    NOWICKI_JESSEE_2018,
    OPEN_QUESTIONS,
    ZHU_2017_GENERAL,
    Covariate,
    GroundFailureModelSpec,
)
from rupture.cascade.covariates import (
    CovariateSample,
    CovariateSource,
    PublishedStaticTerm,
    StaticTerm,
    TabulatedCovariates,
    UnsourcedCovariates,
)
from rupture.cascade.models import (
    KIND_TO_MODEL,
    MODEL_CLASSES,
    Evaluation,
    LogisticGroundFailureModel,
    NowickiJessee2018,
    Zhu2017General,
    build,
)

__all__ = [
    "KIND_TO_MODEL",
    "MODELS",
    "MODEL_CLASSES",
    "NOWICKI_JESSEE_2018",
    "OPEN_QUESTIONS",
    "ZHU_2017_GENERAL",
    "Covariate",
    "CovariateSample",
    "CovariateSource",
    "Evaluation",
    "GroundFailureModelSpec",
    "LogisticGroundFailureModel",
    "NowickiJessee2018",
    "PublishedStaticTerm",
    "StaticTerm",
    "TabulatedCovariates",
    "UnsourcedCovariates",
    "Zhu2017General",
    "build",
]
