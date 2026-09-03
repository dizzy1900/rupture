"""The two USGS ground-failure models, implemented from their published coefficients.

These are **susceptibility products**. Each cell carries the modelled areal fraction of that cell
affected, given the shaking and the static conditioning factors. Nothing here says that a
particular slope, or a particular parcel, fails: the models are empirical fits to inventories of
past events, used by the USGS for near-real-time situational awareness.

The computation follows the USGS reference implementation step for step (see
:mod:`rupture.cascade.coefficients` for the provenance of every number):

1. clip the covariates the published code clips;
2. ``X = intercept + shaking terms + static term``;
3. ``P = 1 / (1 + exp(-X))``;
4. mark the cells failing a PGV / PGA / Vs30 cut-off;
5. ``coverage = f(P)`` with the model's own published transform;
6. zero the marked cells and the cells outside the model's slope band;
7. round to four decimal places, as the published rasters are.

Masked cells are emitted with ``probability = 0.0``, the convention the published GeoTIFFs
themselves use, and every mask that could not be applied for want of a covariate is named in the
output's ``notes`` rather than silently skipped.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from rupture.cascade.coefficients import (
    NOWICKI_JESSEE_2018,
    ZHU_2017_GENERAL,
    ZHU_MAGNITUDE_SCALING_BASE,
    Covariate,
    GroundFailureModelSpec,
    Mask,
)
from rupture.cascade.covariates import (
    CovariateSource,
    StaticTerm,
    UnsourcedCovariates,
)
from rupture.domain.cascade import CascadeKind, GroundFailureCell, GroundFailureField
from rupture.domain.common import Provenance, utc_now
from rupture.domain.groundmotion import GroundMotionField

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]

ADAPTER_VERSION = "0.1.0"

MASK_NOT_APPLIED = -1
"""Sentinel in :attr:`Evaluation.mask_counts`: the covariate was unavailable."""


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Intermediate arrays from one model run, kept so a gate can inspect them."""

    longitudes: FloatArray
    latitudes: FloatArray
    linear_predictor: FloatArray
    probability: FloatArray
    coverage: FloatArray
    masked: BoolArray
    static_term: StaticTerm
    mask_counts: dict[str, int]

    @property
    def masks_not_applied(self) -> tuple[str, ...]:
        return tuple(k for k, v in self.mask_counts.items() if v == MASK_NOT_APPLIED)


def _mask_rejects(mask: Mask, values: FloatArray | None) -> BoolArray | None:
    """True where a cell fails the cut-off. ``None`` when the covariate was unavailable."""
    if values is None:
        return None
    reject = np.zeros(values.shape, dtype=np.bool_)
    if mask.low is not None:
        reject |= values < mask.low
    if mask.high is not None:
        reject |= values > mask.high
    return reject


def _safe_log(values: FloatArray) -> FloatArray:
    """``ln`` with non-positive inputs mapped to ``-inf`` instead of a warning."""
    with np.errstate(divide="ignore", invalid="ignore"):
        out = np.log(np.where(values > 0.0, values, np.nan))
    return np.nan_to_num(out, nan=-np.inf, neginf=-np.inf)


class LogisticGroundFailureModel:
    """Base for both published models: the shared link, masking and packaging."""

    def __init__(
        self,
        spec: GroundFailureModelSpec,
        *,
        covariates: CovariateSource | None = None,
        cell_size_deg: float = 1.0 / 60.0,
    ) -> None:
        self.spec = spec
        self.model_id = spec.model_id
        self.model_version = spec.model_version
        self.source_refs: tuple[str, ...] = (
            spec.citation,
            f"doi:{spec.doi}",
            spec.coefficient_source,
        )
        self.covariates: CovariateSource = covariates or UnsourcedCovariates()
        self.cell_size_deg = cell_size_deg

    # -- what the two models differ on --------------------------------------------------
    def shaking_term(
        self,
        pgv_cm_s: FloatArray,
        vs30_m_s: FloatArray,
        magnitude: float,
        slope_deg: FloatArray | None,
    ) -> FloatArray:
        raise NotImplementedError

    def coverage(self, probability: FloatArray) -> FloatArray:
        raise NotImplementedError

    def invert_coverage(self, coverage: FloatArray) -> FloatArray:
        """Recover ``P`` from an areal coverage. Used to read a published product."""
        raise NotImplementedError

    # -- the shared machinery -----------------------------------------------------------
    def evaluate_arrays(
        self,
        *,
        longitudes: FloatArray,
        latitudes: FloatArray,
        pgv_cm_s: FloatArray,
        pga_g: FloatArray | None,
        vs30_m_s: FloatArray,
        magnitude: float,
    ) -> Evaluation:
        spec = self.spec
        pgv_clip = spec.clips.get(Covariate.PGV_CM_S)
        pgv = (
            np.clip(pgv_cm_s, pgv_clip.low, pgv_clip.high)
            if pgv_clip is not None
            else np.asarray(pgv_cm_s, dtype=np.float64)
        )
        slope = self.covariates.sample(Covariate.SLOPE_DEG, longitudes, latitudes).values
        static = self.covariates.static_term(spec, longitudes, latitudes)
        linear = (
            spec.intercept
            + self.shaking_term(pgv, vs30_m_s, magnitude, slope)
            + static.values
        )
        probability = 1.0 / (1.0 + np.exp(-linear))

        available: dict[Covariate, FloatArray | None] = {
            Covariate.PGV_CM_S: np.asarray(pgv_cm_s, dtype=np.float64),
            Covariate.PGA_G: pga_g,
            Covariate.VS30_M_S: np.asarray(vs30_m_s, dtype=np.float64),
            Covariate.SLOPE_DEG: slope,
        }
        masked = np.zeros(np.shape(longitudes), dtype=np.bool_)
        counts: dict[str, int] = {}
        for mask in spec.masks:
            reject = _mask_rejects(mask, available.get(mask.covariate))
            if reject is None:
                counts[mask.covariate.value] = MASK_NOT_APPLIED
                continue
            counts[mask.covariate.value] = int(reject.sum())
            masked |= reject

        coverage = np.where(masked, 0.0, self.coverage(probability))
        coverage = np.round(np.clip(coverage, 0.0, 1.0), 4)
        return Evaluation(
            longitudes=np.asarray(longitudes, dtype=np.float64),
            latitudes=np.asarray(latitudes, dtype=np.float64),
            linear_predictor=linear,
            probability=probability,
            coverage=coverage,
            masked=masked,
            static_term=static,
            mask_counts=counts,
        )

    def evaluate(
        self,
        field: GroundMotionField,
        *,
        scenario_id: str,
        pga_field: GroundMotionField | None = None,
        magnitude: float | None = None,
        provenance: Provenance | None = None,
        field_id: str | None = None,
    ) -> GroundFailureField:
        """Evaluate the model over the sites of a PGV ground-motion field.

        ``field`` carries PGV in cm/s, the models' shaking input; Vs30 is read off each
        :class:`~rupture.domain.groundmotion.Site`. ``pga_field`` supplies the PGA the published
        models screen on. When a mask's covariate is absent the mask is **not** applied and the
        omission is written into the output's ``notes``.
        """
        if field.imt.upper() != "PGV":
            msg = f"{self.model_id} needs a PGV field, got imt={field.imt!r}"
            raise ValueError(msg)
        if magnitude is None and self.spec.model_id == ZHU_2017_GENERAL.model_id:
            msg = (
                "the Zhu (2017) model scales PGV by event magnitude; pass magnitude= "
                "explicitly rather than letting rupture assume one"
            )
            raise ValueError(msg)
        lons = np.array([s.longitude for s in field.sites], dtype=np.float64)
        lats = np.array([s.latitude for s in field.sites], dtype=np.float64)
        vs30 = np.array([s.vs30 for s in field.sites], dtype=np.float64)
        pga: FloatArray | None = None
        if pga_field is not None:
            if pga_field.imt.upper() != "PGA":
                msg = f"pga_field must carry PGA, got imt={pga_field.imt!r}"
                raise ValueError(msg)
            if len(pga_field.sites) != len(field.sites):
                msg = "pga_field must be evaluated at the same sites as the PGV field"
                raise ValueError(msg)
            pga = pga_field.median()
        evaluation = self.evaluate_arrays(
            longitudes=lons,
            latitudes=lats,
            pgv_cm_s=field.median(),
            pga_g=pga,
            vs30_m_s=vs30,
            magnitude=magnitude if magnitude is not None else float("nan"),
        )
        return self.package(
            evaluation,
            scenario_id=scenario_id,
            shaking_source=field.id,
            field_id=field_id,
            provenance=provenance
            or Provenance(
                source="rupture.cascade",
                source_url=None,
                retrieved_at=utc_now(),
                sha256=None,
                licence=None,
                adapter_version=ADAPTER_VERSION,
                notes=f"derived from ground-motion field {field.id}",
            ),
        )

    def package(
        self,
        evaluation: Evaluation,
        *,
        scenario_id: str,
        shaking_source: str,
        provenance: Provenance,
        field_id: str | None = None,
    ) -> GroundFailureField:
        """Wrap an :class:`Evaluation` in the domain record, caveats and all."""
        cells = tuple(
            GroundFailureCell(
                longitude=float(lon),
                latitude=float(lat),
                probability=float(cov),
                areal_coverage=float(cov),
            )
            for lon, lat, cov in zip(
                evaluation.longitudes,
                evaluation.latitudes,
                evaluation.coverage,
                strict=True,
            )
        )
        notes = [
            f"{self.spec.probability_units}; susceptibility and exposure, not a forecast of "
            f"individual slope failure",
            evaluation.static_term.label(),
        ]
        for name, count in sorted(evaluation.mask_counts.items()):
            notes.append(
                f"mask {name}: NOT APPLIED, covariate unavailable"
                if count == MASK_NOT_APPLIED
                else f"mask {name}: {count} cells zeroed"
            )
        notes.extend(self.spec.notes)
        return GroundFailureField(
            id=field_id or f"{self.model_id}-{scenario_id}",
            kind=self.spec.kind,
            scenario_id=scenario_id,
            model_id=self.model_id,
            model_version=self.model_version,
            cells=cells,
            cell_size_deg=self.cell_size_deg,
            shaking_source=shaking_source,
            computed_at=utc_now(),
            provenance=provenance,
            source_refs=self.source_refs,
            notes=" | ".join(notes),
        )


class NowickiJessee2018(LogisticGroundFailureModel):
    """Landslide areal coverage, Nowicki Jessee et al. (2018).

    The interaction term needs slope, which is a static covariate. Without a slope source the
    interaction contributes nothing, the slope band mask is not applied, and both facts are
    written into the output. That is the declared gap; nothing is substituted for it.
    """

    def __init__(
        self,
        *,
        covariates: CovariateSource | None = None,
        cell_size_deg: float = 1.0 / 60.0,
    ) -> None:
        super().__init__(
            NOWICKI_JESSEE_2018, covariates=covariates, cell_size_deg=cell_size_deg
        )

    def shaking_term(
        self,
        pgv_cm_s: FloatArray,
        vs30_m_s: FloatArray,
        magnitude: float,
        slope_deg: FloatArray | None,
    ) -> FloatArray:
        del vs30_m_s, magnitude
        c = self.spec.coefficients
        log_pgv = _safe_log(pgv_cm_s)
        term = c["log_pgv"] * log_pgv
        if slope_deg is not None:
            term = term + c["log_pgv_x_slope_deg"] * log_pgv * slope_deg
        return term

    def coverage(self, probability: FloatArray) -> FloatArray:
        k = self.spec.coverage_coefficients
        p = probability
        return np.exp(k["a"] + k["b"] * p + k["c"] * p**2 + k["d"] * p**3)

    def invert_coverage(self, coverage: FloatArray) -> FloatArray:
        k = self.spec.coverage_coefficients
        grid = np.linspace(0.0, 1.0, 200001)
        curve = np.exp(k["a"] + k["b"] * grid + k["c"] * grid**2 + k["d"] * grid**3)
        out = np.interp(coverage, curve, grid)
        return np.where((coverage >= curve[0]) & (coverage <= curve[-1]), out, np.nan)


class Zhu2017General(LogisticGroundFailureModel):
    """Liquefaction areal coverage, Zhu et al. (2017) general (global) model."""

    def __init__(
        self,
        *,
        covariates: CovariateSource | None = None,
        cell_size_deg: float = 1.0 / 60.0,
    ) -> None:
        super().__init__(ZHU_2017_GENERAL, covariates=covariates, cell_size_deg=cell_size_deg)

    def magnitude_scaling(self, magnitude: float) -> float:
        """Near-field saturation factor applied to PGV, exactly as the USGS code writes it."""
        return 1.0 / (1.0 + ZHU_MAGNITUDE_SCALING_BASE ** (-2.0 * (magnitude - 6.0)))

    def shaking_term(
        self,
        pgv_cm_s: FloatArray,
        vs30_m_s: FloatArray,
        magnitude: float,
        slope_deg: FloatArray | None,
    ) -> FloatArray:
        del slope_deg
        c = self.spec.coefficients
        scaled = pgv_cm_s * self.magnitude_scaling(magnitude)
        return c["log_pgv_magnitude_scaled"] * _safe_log(scaled) + c["log_vs30"] * _safe_log(
            vs30_m_s
        )

    def coverage(self, probability: FloatArray) -> FloatArray:
        k = self.spec.coverage_coefficients
        return k["a"] / (1.0 + k["b"] * np.exp(-k["c"] * probability)) ** 2

    def invert_coverage(self, coverage: FloatArray) -> FloatArray:
        k = self.spec.coverage_coefficients
        with np.errstate(divide="ignore", invalid="ignore"):
            inner = np.sqrt(k["a"] / np.where(coverage > 0.0, coverage, np.nan)) - 1.0
            p = -np.log(np.where(inner > 0.0, inner, np.nan) / k["b"]) / k["c"]
        return np.where((p >= 0.0) & (p <= 1.0), p, np.nan)


MODEL_CLASSES: dict[str, type[LogisticGroundFailureModel]] = {
    NOWICKI_JESSEE_2018.model_id: NowickiJessee2018,
    ZHU_2017_GENERAL.model_id: Zhu2017General,
}

KIND_TO_MODEL: dict[CascadeKind, str] = {
    CascadeKind.LANDSLIDE: NOWICKI_JESSEE_2018.model_id,
    CascadeKind.LIQUEFACTION: ZHU_2017_GENERAL.model_id,
}


def build(model_id: str, **kwargs: object) -> LogisticGroundFailureModel:
    """Construct a model by id (``landslide``/``liquefaction`` aliases accepted)."""
    alias = {"landslide": NOWICKI_JESSEE_2018.model_id, "liquefaction": ZHU_2017_GENERAL.model_id}
    resolved = alias.get(model_id, model_id)
    cls = MODEL_CLASSES.get(resolved)
    if cls is None:
        known = ", ".join(sorted({*MODEL_CLASSES, *alias}))
        msg = f"unknown cascade model {model_id!r}; known: {known}"
        raise KeyError(msg)
    covariates = kwargs.get("covariates")
    cell_size = kwargs.get("cell_size_deg", 1.0 / 60.0)
    if covariates is not None and not isinstance(covariates, CovariateSource):
        msg = "covariates must implement rupture.cascade.covariates.CovariateSource"
        raise TypeError(msg)
    return cls(covariates=covariates, cell_size_deg=float(cell_size))  # type: ignore[arg-type]
