"""Static conditioning factors for the ground-failure models, and the honesty rule around them.

Both USGS models need global static rasters that rupture does not carry: slope, GLiM lithology
coefficients, GlobCover land-cover coefficients and HYDRO1k CTI for the landslide model;
WorldClim precipitation, distance to coast, distance to river and Fan et al. (2013) water-table
depth for the liquefaction model. **rupture could not obtain any of them at a size it is willing
to commit.** That is a declared gap, not an excuse to invent a constant.

The rule this module enforces is simple: a covariate is either *sourced* — it came from a real
dataset with provenance — or it is *absent*, in which case the model still runs but every output
records the absence, and no consumer can mistake the result for a fully-conditioned one.

Three sources exist:

:class:`UnsourcedCovariates`
    Nothing is available. The static part of the linear predictor is zero and is flagged.
:class:`TabulatedCovariates`
    Per-cell arrays supplied by the caller, with a provenance string. Used by tests and by
    anyone who does have the rasters.
:class:`PublishedStaticTerm`
    The assembled static term recovered by inverting a **published USGS product**. This is only
    legitimate for reproducing that same product; it is labelled as such and never presented as
    an independent covariate set.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

from rupture.cascade.coefficients import Covariate, GroundFailureModelSpec

FloatArray = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class CovariateSample:
    """One covariate over a set of cells, or an honest statement that it is missing."""

    covariate: Covariate
    values: FloatArray | None
    source: str
    licence: str | None = None

    @property
    def sourced(self) -> bool:
        return self.values is not None


@dataclass(frozen=True, slots=True)
class StaticTerm:
    """The non-shaking part of a logistic model's linear predictor, plus what it is worth.

    ``missing`` names every covariate that could not be sourced. When it is non-empty the term
    is a lower bound on the real one at best, and every downstream product says so.
    """

    values: FloatArray
    source: str
    missing: tuple[Covariate, ...]
    sourced: tuple[Covariate, ...]

    @property
    def complete(self) -> bool:
        return not self.missing

    def label(self) -> str:
        if self.complete:
            return f"static conditioning factors from {self.source}"
        names = ", ".join(sorted(c.value for c in self.missing))
        return (
            f"static conditioning factors INCOMPLETE ({self.source}); "
            f"not sourced and treated as zero: {names}"
        )


@runtime_checkable
class CovariateSource(Protocol):
    """Supplies static conditioning factors at given cell centres.

    Two methods, because the models need both: ``sample`` for a single covariate the model uses
    on its own (slope, which appears in a mask and in an interaction term) and ``static_term``
    for the assembled non-shaking part of the linear predictor.
    """

    source_id: str

    def sample(self, covariate: Covariate, lons: FloatArray, lats: FloatArray) -> CovariateSample:
        """Return the covariate at each (lon, lat), or a sample with ``values=None``."""
        ...

    def static_term(
        self, spec: GroundFailureModelSpec, lons: FloatArray, lats: FloatArray
    ) -> StaticTerm:
        """Assemble the non-shaking part of ``spec``'s linear predictor over these cells."""
        ...


class UnsourcedCovariates:
    """No static covariate is available. Every one is reported missing; the term is zero.

    This is rupture's default, and it is deliberately useless-looking: a ground-failure field
    computed this way carries only the shaking response of the published model and says so in
    its ``notes``. It exists so the model code can be exercised and validated end to end without
    anyone being able to mistake the output for a conditioned susceptibility map.
    """

    source_id = "unsourced"

    def __init__(self, reason: str = "no global covariate rasters are committed to rupture"):
        self.reason = reason

    def sample(self, covariate: Covariate, lons: FloatArray, lats: FloatArray) -> CovariateSample:
        del lons, lats
        return CovariateSample(covariate=covariate, values=None, source=self.reason)

    def static_term(
        self, spec: GroundFailureModelSpec, lons: FloatArray, lats: FloatArray
    ) -> StaticTerm:
        del lats
        return StaticTerm(
            values=np.zeros(lons.shape, dtype=np.float64),
            source=self.reason,
            missing=tuple(Covariate(term) for term in spec.static_terms),
            sourced=(),
        )


class TabulatedCovariates:
    """Covariates handed in as arrays, one per cell, with a provenance string."""

    def __init__(
        self,
        values: dict[Covariate, FloatArray],
        *,
        source_id: str,
        licence: str | None = None,
    ) -> None:
        self.source_id = source_id
        self._values = dict(values)
        self._licence = licence

    def sample(self, covariate: Covariate, lons: FloatArray, lats: FloatArray) -> CovariateSample:
        del lats
        array = self._values.get(covariate)
        if array is None:
            return CovariateSample(
                covariate=covariate,
                values=None,
                source=f"{self.source_id}: not carried",
            )
        if array.shape != lons.shape:
            msg = (
                f"covariate {covariate.value} has shape {array.shape}, "
                f"expected {lons.shape} (one value per cell)"
            )
            raise ValueError(msg)
        return CovariateSample(
            covariate=covariate,
            values=np.asarray(array, dtype=np.float64),
            source=self.source_id,
            licence=self._licence,
        )

    def static_term(
        self, spec: GroundFailureModelSpec, lons: FloatArray, lats: FloatArray
    ) -> StaticTerm:
        total = np.zeros(lons.shape, dtype=np.float64)
        missing: list[Covariate] = []
        sourced: list[Covariate] = []
        for term in spec.static_terms:
            covariate = Covariate(term)
            sample = self.sample(covariate, lons, lats)
            if sample.values is None:
                missing.append(covariate)
                continue
            values = sample.values
            clip = spec.clips.get(covariate)
            if clip is not None:
                values = np.clip(values, clip.low, clip.high)
            total = total + spec.coefficients[term] * values
            sourced.append(covariate)
        return StaticTerm(
            values=total,
            source=self.source_id,
            missing=tuple(missing),
            sourced=tuple(sourced),
        )


class PublishedStaticTerm:
    """The static term recovered by inverting an already-published USGS ground-failure product.

    Only honest use: reproducing the product it was recovered from, to check that rupture's
    coefficient table, link function, clips, masks and coverage transform match the operational
    implementation. It is **not** an independently sourced covariate set and it cannot be
    transferred to another event, so ``missing`` still lists every covariate it stands in for.
    """

    source_id = "recovered-from-published-usgs-product"

    def __init__(self, values: FloatArray, *, product: str) -> None:
        self._values = np.asarray(values, dtype=np.float64)
        self.product = product

    def sample(self, covariate: Covariate, lons: FloatArray, lats: FloatArray) -> CovariateSample:
        del lons, lats
        return CovariateSample(
            covariate=covariate,
            values=None,
            source=f"{self.source_id}: only the assembled term is available, not its parts",
        )

    def static_term(
        self, spec: GroundFailureModelSpec, lons: FloatArray, lats: FloatArray
    ) -> StaticTerm:
        del lats
        if self._values.shape != lons.shape:
            msg = (
                f"recovered static term has shape {self._values.shape}, expected {lons.shape}"
            )
            raise ValueError(msg)
        return StaticTerm(
            values=self._values,
            source=f"{self.source_id} ({self.product})",
            missing=tuple(Covariate(t) for t in spec.static_terms),
            sourced=(),
        )
