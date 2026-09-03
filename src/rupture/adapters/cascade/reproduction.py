"""Compare rupture's ground-failure models against the published USGS product for one event.

Three comparisons are run, and all three numbers are reported. They answer different questions
and only the first two are evidence of anything.

``LINK`` — link-function and coverage round trip
    Invert the published coverage raster to recover the linear predictor ``X``, feed ``X`` back
    through rupture's coverage transform and masks, and compare. This isolates the parts of the
    published model rupture can check exactly: the logistic link, the published coverage
    polynomial (landslide) or saturating curve (liquefaction), the masks and the four-decimal
    rounding. Agreement here is expected to be at rounding level; anything else is a defect.

``SHAKING`` — shaking response, static term taken from the product
    Recover the static (non-shaking) part of ``X`` from the published product, then recompute
    the whole field from the ShakeMap PGV, PGA and Vs30 with rupture's own coefficients. This
    tests the intercept, the shaking coefficients, the magnitude scaling, the clips and the
    masks against the real product. It does **not** test the static covariates: they were taken
    from the answer, and the result says so.

``UNCONDITIONED`` — the honest cost of the covariate gap
    Run rupture's model with no static covariates at all, which is what rupture can actually do
    today, and report how far that lands from the published product. This is the number that
    describes rupture's present capability, and it is not a good one.

Additionally the ``SHAKING`` comparison reports an **admissibility** statistic: the recovered
static term must lie inside the range the published coefficients and their clips permit (for the
liquefaction model, ``precipitation`` is clipped at 2500 mm and enters with a positive
coefficient while distance-to-water and water-table depth enter with negative ones and are
non-negative, so the static term cannot exceed ``0.0005408 * 2500 = 1.352``). A wrong coefficient
table, a units error or a mis-ordered term would push the recovered values outside that band, so
the fraction inside it is a genuine falsifiable check on the implementation.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from rupture.adapters.cascade.product import PublishedCoverage
from rupture.adapters.cascade.shakemap import ShakeMapGrid
from rupture.cascade.coefficients import Covariate
from rupture.cascade.covariates import PublishedStaticTerm, UnsourcedCovariates
from rupture.cascade.models import LogisticGroundFailureModel

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


class Comparison(StrEnum):
    LINK = "link"
    SHAKING = "shaking"
    UNCONDITIONED = "unconditioned"


@dataclass(frozen=True, slots=True)
class Agreement:
    """What one comparison actually achieved. No number here is rounded up."""

    comparison: Comparison
    model_id: str
    n_cells: int
    pearson_r: float
    mean_absolute_difference: float
    max_absolute_difference: float
    bias: float
    published_mean: float
    rupture_mean: float
    tolerance: float
    fraction_within_tolerance: float
    what_it_tests: str

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["comparison"] = self.comparison.value
        return payload


@dataclass(frozen=True, slots=True)
class Admissibility:
    """Whether the recovered static term lies inside the published coefficients' own range."""

    model_id: str
    n_cells: int
    upper_bound: float
    fraction_within: float
    minimum: float
    median: float
    p99: float
    maximum: float
    basis: str


@dataclass(frozen=True, slots=True)
class ReproductionReport:
    """Everything the Gorkha comparison found, ready to be written to JSON or a doc."""

    event_id: str
    model_id: str
    n_published_cells: int
    n_compared_cells: int
    coverage_threshold: float
    agreements: tuple[Agreement, ...]
    admissibility: Admissibility | None
    covariates_sourced: tuple[str, ...]
    covariates_not_sourced: tuple[str, ...]
    notes: tuple[str, ...]

    def agreement(self, comparison: Comparison) -> Agreement:
        for item in self.agreements:
            if item.comparison is comparison:
                return item
        msg = f"no {comparison.value} comparison in this report"
        raise KeyError(msg)

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "model_id": self.model_id,
            "n_published_cells": self.n_published_cells,
            "n_compared_cells": self.n_compared_cells,
            "coverage_threshold": self.coverage_threshold,
            "agreements": [a.as_dict() for a in self.agreements],
            "admissibility": asdict(self.admissibility) if self.admissibility else None,
            "covariates_sourced": list(self.covariates_sourced),
            "covariates_not_sourced": list(self.covariates_not_sourced),
            "notes": list(self.notes),
            "label": (
                "susceptibility reproduction check; not a forecast of individual slope failure"
            ),
        }


TOLERANCE = 0.01
"""Per-cell areal-coverage tolerance the gate reports against. Coverage is a fraction in [0, 1];
the published rasters are rounded to four decimals, so 0.01 is 100 rounding units and is a loose
band by design: it is there to catch a broken implementation, not to certify a good one."""


def _stats(
    comparison: Comparison, model_id: str, published: FloatArray, mine: FloatArray, what: str
) -> Agreement:
    keep = np.isfinite(published) & np.isfinite(mine)
    a, b = published[keep], mine[keep]
    r = (
        float(np.corrcoef(a, b)[0, 1])
        if a.size > 1 and a.std() > 0 and b.std() > 0
        else float("nan")
    )
    difference = np.abs(a - b)
    return Agreement(
        comparison=comparison,
        model_id=model_id,
        n_cells=int(a.size),
        pearson_r=r,
        mean_absolute_difference=float(difference.mean()),
        max_absolute_difference=float(difference.max()),
        bias=float((b - a).mean()),
        published_mean=float(a.mean()),
        rupture_mean=float(b.mean()),
        tolerance=TOLERANCE,
        fraction_within_tolerance=float((difference <= TOLERANCE).mean()) if a.size else 0.0,
        what_it_tests=what,
    )


def _admissible_upper_bound(model: LogisticGroundFailureModel) -> tuple[float, str] | None:
    """The largest value the static term can take under the published coefficients."""
    spec = model.spec
    bound = 0.0
    parts: list[str] = []
    for term in spec.static_terms:
        covariate = Covariate(term)
        coefficient = spec.coefficients[term]
        clip = spec.clips.get(covariate)
        if coefficient > 0.0:
            if clip is None:
                return None  # unbounded above: no falsifiable bound available
            bound += coefficient * clip.high
            parts.append(f"{coefficient} * {clip.high} ({covariate.value} clipped)")
        else:
            parts.append(f"{coefficient} * (>= 0) <= 0 ({covariate.value})")
    return bound, "; ".join(parts)


def reproduce(
    model: LogisticGroundFailureModel,
    *,
    published: PublishedCoverage,
    shakemap: ShakeMapGrid,
    magnitude: float,
    event_id: str,
    coverage_threshold: float,
) -> ReproductionReport:
    """Run all three comparisons for one model against one published product."""
    lons, lats = published.longitudes, published.latitudes
    pgv = shakemap.sample("PGV", lons, lats)
    pga_g = shakemap.sample("PGA", lons, lats) / 100.0
    vs30 = shakemap.sample("SVEL", lons, lats)

    # Cells the comparison can say anything about: the published value must be far enough above
    # the coverage transform's own floor that inverting a four-decimal number is stable.
    well_conditioned: BoolArray = published.coverage > coverage_threshold
    recovered_p = model.invert_coverage(published.coverage)
    with np.errstate(divide="ignore", invalid="ignore"):
        recovered_x = np.log(recovered_p / (1.0 - recovered_p))
    usable = well_conditioned & np.isfinite(recovered_x)

    shaking = model.shaking_term(
        np.clip(pgv, *_pgv_clip(model)),
        vs30,
        magnitude,
        None,
    )
    static_recovered = recovered_x - model.spec.intercept - shaking

    def run(covariate_source: object) -> FloatArray:
        model.covariates = covariate_source  # type: ignore[assignment]
        evaluation = model.evaluate_arrays(
            longitudes=lons,
            latitudes=lats,
            pgv_cm_s=pgv,
            pga_g=pga_g,
            vs30_m_s=vs30,
            magnitude=magnitude,
        )
        return evaluation.coverage

    original = model.covariates
    try:
        unconditioned = run(UnsourcedCovariates())
        shaking_only = run(
            PublishedStaticTerm(
                np.where(np.isfinite(static_recovered), static_recovered, 0.0),
                product=f"USGS ground-failure {model.model_id} for {event_id}",
            )
        )
    finally:
        model.covariates = original

    link_round_trip = np.round(
        np.clip(model.coverage(np.where(usable, recovered_p, np.nan)), 0.0, 1.0), 4
    )

    agreements = (
        _stats(
            Comparison.LINK,
            model.model_id,
            published.coverage[usable],
            link_round_trip[usable],
            "logistic link, the published coverage transform and the 4-dp rounding",
        ),
        _stats(
            Comparison.SHAKING,
            model.model_id,
            published.coverage[usable],
            shaking_only[usable],
            "intercept, shaking coefficients, magnitude scaling, clips and masks, with the "
            "static term taken from the published product (so the static covariates are NOT "
            "tested)",
        ),
        _stats(
            Comparison.UNCONDITIONED,
            model.model_id,
            published.coverage[usable],
            unconditioned[usable],
            "what rupture can actually compute today, with no static covariate sourced",
        ),
    )

    admissibility: Admissibility | None = None
    bound = _admissible_upper_bound(model)
    if bound is not None:
        upper, basis = bound
        values = static_recovered[usable]
        values = values[np.isfinite(values)]
        admissibility = Admissibility(
            model_id=model.model_id,
            n_cells=int(values.size),
            upper_bound=upper,
            fraction_within=float((values <= upper).mean()) if values.size else float("nan"),
            minimum=float(values.min()) if values.size else float("nan"),
            median=float(np.median(values)) if values.size else float("nan"),
            p99=float(np.percentile(values, 99)) if values.size else float("nan"),
            maximum=float(values.max()) if values.size else float("nan"),
            basis=basis,
        )

    sourced = tuple(
        c.value for c in (Covariate.PGV_CM_S, Covariate.PGA_G, Covariate.VS30_M_S)
    )
    not_sourced = tuple(Covariate(t).value for t in model.spec.static_terms)
    notes = [
        "PGA, PGV and Vs30 come from the same published ShakeMap the USGS ground-failure "
        "product was computed from; Vs30 is the ShakeMap SVEL band, while the product uses a "
        "separate Wald and Allen (2007) raster, so the two are close but not identical.",
        "Cells at or below the coverage threshold are excluded because the published raster is "
        "rounded to four decimals and the coverage transform cannot be inverted stably there, "
        "not because they disagree.",
        "The slope-band mask could not be applied: no slope raster is committed, so the "
        "published cells that are exactly zero are not reproducible here.",
    ]
    link_result, shaking_result = agreements[0], agreements[1]
    if shaking_result.max_absolute_difference == link_result.max_absolute_difference == 0.0:
        notes.append(
            "DEGENERATE: for this model and window the shaking comparison reduced exactly to "
            "the link round trip. No shaking-dependent mask fired and every shaking term is "
            "absorbed by the static term recovered from the product, so the shaking comparison "
            "adds no evidence beyond the link one. Treat its perfect score as arithmetic, not "
            "as validation."
        )
    return ReproductionReport(
        event_id=event_id,
        model_id=model.model_id,
        n_published_cells=len(published),
        n_compared_cells=int(usable.sum()),
        coverage_threshold=coverage_threshold,
        agreements=agreements,
        admissibility=admissibility,
        covariates_sourced=sourced,
        covariates_not_sourced=not_sourced,
        notes=tuple(notes),
    )


def _pgv_clip(model: LogisticGroundFailureModel) -> tuple[float, float]:
    clip = model.spec.clips.get(Covariate.PGV_CM_S)
    return (clip.low, clip.high) if clip is not None else (0.0, np.inf)
