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
from rupture.domain.money import ModelProvenance


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


WEIGHT_TOLERANCE = 1e-9


class GsimBranch(RuptureModel):
    """One branch of a GSIM logic tree: a model, its weight, and why it is there."""

    id: str
    gsim: str = Field(description="A GSIM rupture ships, i.e. a name in the native registry.")
    weight: float = Field(gt=0.0, le=1.0)
    rationale: str = Field(
        min_length=1, description="What epistemic alternative this branch stands for."
    )
    source_refs: tuple[str, ...] = ()


class GsimLogicTree(RuptureModel):
    """A weighted set of ground-shaking models for one tectonic region type.

    A single GSIM gives a loss interval that is conditional on that one model being right, which
    is the narrowest of the assumptions in a loss figure and rarely the most defensible. A logic
    tree carries the **epistemic** alternative explicitly: each branch is evaluated and the
    realisations are allocated between branches in proportion to the weights, so the resulting
    interval mixes aleatory ground-motion variability with model choice.

    ``provenance`` says what kind of claim the *weights* are. ``published`` means the tree and
    its weights are taken from a named model; ``assumed`` means rupture chose them and says so.
    A tree that claims ``published`` must carry a ``source_ref``.
    """

    id: str
    tectonic_region: str = Field(default="Active Shallow Crust")
    branches: tuple[GsimBranch, ...] = Field(min_length=1)
    provenance: ModelProvenance = ModelProvenance.ASSUMED
    source_refs: tuple[str, ...] = ()
    excluded: tuple[str, ...] = Field(
        default=(),
        description="Models a fuller tree would carry that rupture has not verified, named here.",
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _weights_and_sources(self) -> Self:
        total = sum(b.weight for b in self.branches)
        if abs(total - 1.0) > WEIGHT_TOLERANCE:
            msg = f"branch weights sum to {total!r}, not 1.0"
            raise ValueError(msg)
        if len({b.id for b in self.branches}) != len(self.branches):
            msg = "branch ids must be unique"
            raise ValueError(msg)
        if self.provenance is ModelProvenance.PUBLISHED and not self.source_refs:
            msg = "a logic tree claiming published weights must cite where they come from"
            raise ValueError(msg)
        return self

    def allocation(self, n_realisations: int) -> tuple[int, ...]:
        """Realisations per branch, by largest remainder, so the weights are honoured exactly.

        Sampling a branch per realisation would honour the weights only in expectation and would
        make two runs with the same seed but different branch order disagree. A deterministic
        allocation makes the mixed field reproducible and the weights exact to within one
        realisation. Every branch gets at least one realisation, so a low-weight branch is never
        silently dropped; that is refused instead when there are fewer realisations than branches.
        """
        if n_realisations < len(self.branches):
            msg = (
                f"{n_realisations} realisation(s) cannot represent {len(self.branches)} branches; "
                "ask for at least one per branch"
            )
            raise ValueError(msg)
        raw = [b.weight * n_realisations for b in self.branches]
        counts = [max(int(x), 1) for x in raw]
        remainder = n_realisations - sum(counts)
        order = sorted(range(len(raw)), key=lambda i: raw[i] - int(raw[i]), reverse=True)
        index = 0
        while remainder > 0:
            counts[order[index % len(order)]] += 1
            remainder -= 1
            index += 1
        while remainder < 0:
            candidate = order[-(1 + (index % len(order)))]
            if counts[candidate] > 1:
                counts[candidate] -= 1
                remainder += 1
            index += 1
        return tuple(counts)

    def describe(self) -> str:
        parts = ", ".join(f"{b.gsim} {b.weight:.0%}" for b in self.branches)
        tail = f"; not represented: {', '.join(self.excluded)}" if self.excluded else ""
        return f"{self.id} ({self.provenance.value} weights): {parts}{tail}"
