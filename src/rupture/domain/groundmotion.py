"""Ground-motion fields (the bridge from hazard to loss).

A :class:`GroundMotionField` is the output of a scenario or event-based calculation: intensity
measure values at sites, for one or more realisations. It always records **which engine produced
it**, because rupture has two (ADR-0020): the OpenQuake engine in its pinned container, which is
authoritative, and a native GSIM evaluator verified against OpenQuake's own published test
vectors, which runs where the container cannot. A number whose engine is unknown is not usable.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Self

import numpy as np
import numpy.typing as npt
from pydantic import Field, model_validator

from rupture.domain.common import Provenance, RuptureModel, UTCDatetime


class GroundMotionEngineId(StrEnum):
    OPENQUAKE_ENGINE = "openquake.engine"
    NATIVE_GSIM = "rupture.native_gsim"


class Site(RuptureModel):
    """One site at which ground motion is evaluated."""

    id: str
    longitude: float = Field(ge=-180.0, le=180.0)
    latitude: float = Field(ge=-90.0, le=90.0)
    vs30: float = Field(gt=0.0, description="Time-averaged shear-wave velocity to 30 m, m/s.")
    vs30_measured: bool = False
    z1pt0: float | None = Field(default=None, ge=0.0, description="Depth to Vs=1.0 km/s, m.")
    z2pt5: float | None = Field(default=None, ge=0.0, description="Depth to Vs=2.5 km/s, km.")


class GroundMotionField(RuptureModel):
    """Intensity measure values per site per realisation, for one intensity measure type.

    ``values[r][s]`` is realisation ``r`` at site ``s``, in g for PGA and SA, cm/s for PGV.
    A single-realisation field is a median ground-motion field; many realisations carry the
    GSIM's aleatory variability and are what loss intervals are computed from.
    """

    id: str
    scenario_id: str
    imt: str = Field(description="OpenQuake spelling: 'PGA', 'PGV', 'SA(0.3)'.")
    sites: tuple[Site, ...] = Field(min_length=1)
    values: tuple[tuple[float, ...], ...] = Field(min_length=1)
    engine: GroundMotionEngineId
    engine_version: str
    gsim: str = Field(description="GSIM/GMPE identifier, e.g. 'BooreEtAl2014'.")
    rupture_id: str | None = None
    truncation_level: float | None = Field(default=None, ge=0.0)
    random_seed: int | None = None
    computed_at: UTCDatetime
    provenance: Provenance
    notes: str | None = None

    @model_validator(mode="after")
    def _shape_and_finiteness(self) -> Self:
        width = len(self.sites)
        for row in self.values:
            if len(row) != width:
                msg = "every realisation must have one value per site"
                raise ValueError(msg)
            for v in row:
                if not math.isfinite(v) or v < 0.0:
                    msg = "ground-motion values must be finite and non-negative"
                    raise ValueError(msg)
        return self

    @property
    def n_realisations(self) -> int:
        return len(self.values)

    def array(self) -> npt.NDArray[np.float64]:
        """(n_realisations, n_sites) float64."""
        return np.asarray(self.values, dtype=np.float64)

    def median(self) -> npt.NDArray[np.float64]:
        """Per-site median across realisations."""
        return np.median(self.array(), axis=0)
