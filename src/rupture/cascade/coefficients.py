"""Published coefficients for the two USGS ground-failure models.

**Every number in this module is copied from a published source; none is fitted, tuned or
invented by rupture.** The authoritative machine-readable source is the USGS ``groundfailure``
reference implementation, which is US public domain with a worldwide CC0 1.0 dedication and is
committed under ``tests/fixtures/cascade/usgs_groundfailure/`` with its provenance and licence.
``tests/unit/cascade/test_coefficients.py`` re-parses those committed files and asserts that
every value below still matches, so a silent divergence fails the offline suite.

Citations
---------
Landslide
    Nowicki Jessee, M.A., Hamburger, M.W., Allstadt, K.E., Wald, D.J., Robeson, S.M., Tanyas, H.,
    Hearne, M., Thompson, E.M. (2018). A Global Empirical Model for Near Real-time Assessment of
    Seismically Induced Landslides. *Journal of Geophysical Research: Earth Surface*, 123,
    1835-1859. doi:10.1029/2017JF004494.
Liquefaction
    Zhu, J., Baise, L.G., Thompson, E.M. (2017). An Updated Geospatial Liquefaction Model for
    Global Application. *Bulletin of the Seismological Society of America*, 107, 1365-1385.
    doi:10.1785/0120160198.

Two divergences between the operational USGS code and the papers are recorded here rather than
resolved, because rupture reproduces the operational product and will not quietly pick a side.
See :data:`OPEN_QUESTIONS` and ``docs/CASCADE.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from rupture.domain.cascade import CascadeKind


class Covariate(StrEnum):
    """Named model inputs.

    Shaking covariates come from a ground-motion field; the rest are static conditioning
    factors supplied by a :class:`rupture.cascade.covariates.CovariateSource`.
    """

    PGV_CM_S = "pgv_cm_s"
    PGA_G = "pga_g"
    VS30_M_S = "vs30_m_s"
    SLOPE_DEG = "slope_deg"
    LITHOLOGY_COEFFICIENT = "lithology_coefficient"
    LANDCOVER_COEFFICIENT = "landcover_coefficient"
    CTI = "cti"
    PRECIPITATION_MM = "precipitation_mm"
    DISTANCE_TO_WATER_KM = "distance_to_water_km"
    WATER_TABLE_DEPTH_M = "water_table_depth_m"


SHAKING_COVARIATES: Final[frozenset[Covariate]] = frozenset(
    {Covariate.PGV_CM_S, Covariate.PGA_G, Covariate.VS30_M_S}
)
"""Covariates rupture reads off a :class:`~rupture.domain.groundmotion.GroundMotionField`.

``vs30`` is here because it rides on :class:`~rupture.domain.groundmotion.Site`, not because it
is shaking. The USGS product takes it from a separate global raster; see ``docs/CASCADE.md``.
"""


@dataclass(frozen=True, slots=True)
class Clip:
    """An inclusive clip applied to a covariate before it enters the logit score."""

    low: float
    high: float
    units: str
    source: str


@dataclass(frozen=True, slots=True)
class Mask:
    """A screening cut-off. Cells outside the range are not evaluated by the published model."""

    covariate: Covariate
    low: float | None
    high: float | None
    units: str
    source: str


@dataclass(frozen=True, slots=True)
class GroundFailureModelSpec:
    """One published logistic ground-failure model, coefficients and all.

    The logit score is ``X = intercept + sum_i coefficient_i * term_i``; the probability is
    ``P = 1 / (1 + exp(-X))``; the reported quantity is ``coverage(P)``, an areal fraction.
    """

    model_id: str
    model_version: str
    kind: CascadeKind
    title: str
    citation: str
    doi: str
    intercept: float
    coefficients: dict[str, float]
    term_descriptions: dict[str, str]
    static_terms: tuple[str, ...]
    shaking_terms: tuple[str, ...]
    clips: dict[Covariate, Clip]
    masks: tuple[Mask, ...]
    coverage_coefficients: dict[str, float]
    coverage_form: str
    maximum_probability: float
    default_stddev_logit: float
    probability_units: str
    coefficient_source: str
    covariates_required: tuple[Covariate, ...]
    notes: tuple[str, ...] = field(default_factory=tuple)


USGS_REFERENCE_IMPLEMENTATION: Final[str] = (
    "https://code.usgs.gov/ghsc/esi/groundfailure/groundfailure"
)
USGS_LICENCE: Final[str] = "CC0-1.0 (US public domain)"

# --------------------------------------------------------------------------- landslide
NOWICKI_JESSEE_2018: Final[GroundFailureModelSpec] = GroundFailureModelSpec(
    model_id="nowicki_jessee_2018",
    model_version="usgs-groundfailure/jessee_2018",
    kind=CascadeKind.LANDSLIDE,
    title="Nowicki Jessee and others (2018)",
    citation=(
        "Nowicki Jessee, M.A., Hamburger, M.W., Allstadt, K.E., Wald, D.J., Robeson, S.M., "
        "Tanyas, H., Hearne, M., Thompson, E.M., 2018, A Global Empirical Model for Near "
        "Real-time Assessment of Seismically Induced Landslides, Journal of Geophysical "
        "Research: Earth Surface, 123, 1835-1859"
    ),
    doi="10.1029/2017JF004494",
    intercept=-6.30,
    coefficients={
        "log_pgv": 1.65,
        "slope_deg": 0.06,
        "lithology_coefficient": 1.0,
        "cti": 0.03,
        "landcover_coefficient": 1.0,
        "log_pgv_x_slope_deg": 0.01,
    },
    term_descriptions={
        "log_pgv": "ln(PGV), PGV in cm/s, clipped to [0, 211]",
        "slope_deg": "slope in degrees (arctan of the GMTED2010 gradient raster)",
        "lithology_coefficient": (
            "per-GLiM-class coefficient, pre-substituted into the GLIM_replace.tif raster; the "
            "coefficient here is 1.0 because the raster already holds the fitted values"
        ),
        "cti": "compound topographic index (HYDRO1k), clipped to [0, 19]",
        "landcover_coefficient": (
            "per-land-cover-class coefficient, pre-substituted into globcover_replace.tif; the "
            "coefficient here is 1.0 for the same reason"
        ),
        "log_pgv_x_slope_deg": "ln(PGV) * slope in degrees",
    },
    static_terms=("slope_deg", "lithology_coefficient", "cti", "landcover_coefficient"),
    shaking_terms=("log_pgv", "log_pgv_x_slope_deg"),
    clips={
        Covariate.PGV_CM_S: Clip(0.0, 211.0, "cm/s", "gfail/models/jessee_2018.py CLIPS"),
        Covariate.CTI: Clip(0.0, 19.0, "index", "gfail/models/jessee_2018.py CLIPS"),
    },
    masks=(
        Mask(
            Covariate.SLOPE_DEG,
            2.0,
            90.0,
            "degrees",
            "defaultconfigfiles/models/jessee_2018.ini slopemin/slopemax",
        ),
        Mask(
            Covariate.PGA_G,
            0.02,
            None,
            "g",
            "jessee_2018.ini minpga = 2 %g (Jibson and Harp, 2016)",
        ),
    ),
    coverage_coefficients={"a": -7.592, "b": 5.237, "c": -3.042, "d": 4.035},
    coverage_form="exp(a + b*P + c*P**2 + d*P**3)",
    maximum_probability=0.256,
    default_stddev_logit=0.03,
    probability_units="Proportion of area affected",
    coefficient_source=(
        f"{USGS_REFERENCE_IMPLEMENTATION}/-/raw/main/src/gfail/models/jessee_2018.py "
        f"(COEFFS, CLIPS, COV_COEFFS); masks from defaultconfigfiles/models/jessee_2018.ini"
    ),
    covariates_required=(
        Covariate.PGV_CM_S,
        Covariate.PGA_G,
        Covariate.SLOPE_DEG,
        Covariate.LITHOLOGY_COEFFICIENT,
        Covariate.LANDCOVER_COEFFICIENT,
        Covariate.CTI,
    ),
    notes=(
        "The USGS operational product replaces the unconsolidated-sediment lithology "
        "coefficient with -1.36 (weaker), from -3.21 in the fitted table, 'to better reflect "
        "that this unit is not actually strong'. The substitution is in the operational code "
        "and is recorded in the Gorkha product's own info.json.",
        "The lithology and land-cover coefficients are not scalars: they are per-class values "
        "pre-substituted into two global rasters that the USGS does not publish at a fetchable "
        "URL. rupture therefore treats them as covariates supplied by a CovariateSource, and "
        "an absent source is a declared gap rather than a guessed constant.",
    ),
)

# --------------------------------------------------------------------------- liquefaction
ZHU_2017_GENERAL: Final[GroundFailureModelSpec] = GroundFailureModelSpec(
    model_id="zhu_2017_general",
    model_version="usgs-groundfailure/zhu_2017_general",
    kind=CascadeKind.LIQUEFACTION,
    title="Zhu and others (2017), general (global) model",
    citation=(
        "Zhu, J., Baise, L.G., Thompson, E.M., 2017, An Updated Geospatial Liquefaction Model "
        "for Global Application, Bulletin of the Seismological Society of America, 107, "
        "1365-1385"
    ),
    doi="10.1785/0120160198",
    intercept=8.801,
    coefficients={
        "log_pgv_magnitude_scaled": 0.334,
        "log_vs30": -1.918,
        "precipitation_mm": 0.0005408,
        "distance_to_water_km": -0.2054,
        "water_table_depth_m": -0.0333,
    },
    term_descriptions={
        "log_pgv_magnitude_scaled": (
            "ln(PGV * 1/(1 + 2.71828**(-2*(Mw - 6)))), PGV in cm/s clipped to [0, 150]; the "
            "magnitude scaling is a near-field saturation term in the operational code"
        ),
        "log_vs30": "ln(Vs30) in m/s",
        "precipitation_mm": "mean annual precipitation, mm, clipped to [0, 2500]",
        "distance_to_water_km": "min(distance to coast, distance to river), km",
        "water_table_depth_m": "water table depth, m",
    },
    static_terms=("precipitation_mm", "distance_to_water_km", "water_table_depth_m"),
    shaking_terms=("log_pgv_magnitude_scaled", "log_vs30"),
    clips={
        Covariate.PGV_CM_S: Clip(0.0, 150.0, "cm/s", "gfail/models/zhu_2017.py CLIPS"),
        Covariate.PRECIPITATION_MM: Clip(0.0, 2500.0, "mm", "gfail/models/zhu_2017.py CLIPS"),
    },
    masks=(
        Mask(
            Covariate.SLOPE_DEG,
            0.0,
            5.0,
            "degrees",
            "defaultconfigfiles/models/zhu_2017_general.ini slopemin/slopemax",
        ),
        Mask(Covariate.PGV_CM_S, 3.0, None, "cm/s", "zhu_2017_general.ini minpgv = 3.0"),
        Mask(Covariate.PGA_G, 0.10, None, "g", "zhu_2017_general.ini minpga = 10 %g"),
        Mask(Covariate.VS30_M_S, None, 620.0, "m/s", "zhu_2017_general.ini vs30max = 620"),
    ),
    coverage_coefficients={"a": 0.4915, "b": 42.4, "c": 9.165},
    coverage_form="a / (1 + b*exp(-c*P))**2",
    maximum_probability=0.487,
    default_stddev_logit=0.05,
    probability_units="Proportion of area affected",
    coefficient_source=(
        f"{USGS_REFERENCE_IMPLEMENTATION}/-/raw/main/src/gfail/models/zhu_2017.py "
        f"(COEFFS, CLIPS, COV_COEFFS); masks from "
        f"defaultconfigfiles/models/zhu_2017_general.ini"
    ),
    covariates_required=(
        Covariate.PGV_CM_S,
        Covariate.PGA_G,
        Covariate.VS30_M_S,
        Covariate.SLOPE_DEG,
        Covariate.PRECIPITATION_MM,
        Covariate.DISTANCE_TO_WATER_KM,
        Covariate.WATER_TABLE_DEPTH_M,
    ),
    notes=(
        "The operational magnitude-scaling factor is written with the literal 2.71828 rather "
        "than e. rupture reproduces the literal, because the object of the exercise is the "
        "USGS product; the difference is about 1e-6 in the scaling factor.",
        "The USGS product takes Vs30 from the Wald and Allen (2007) topographic-slope raster, "
        "not from the ShakeMap SVEL band. rupture uses whatever Vs30 the supplied "
        "GroundMotionField carries and records which it was.",
    ),
)

MODELS: Final[dict[str, GroundFailureModelSpec]] = {
    NOWICKI_JESSEE_2018.model_id: NOWICKI_JESSEE_2018,
    ZHU_2017_GENERAL.model_id: ZHU_2017_GENERAL,
}

MODEL_FOR_KIND: Final[dict[CascadeKind, GroundFailureModelSpec]] = {
    CascadeKind.LANDSLIDE: NOWICKI_JESSEE_2018,
    CascadeKind.LIQUEFACTION: ZHU_2017_GENERAL,
}

ZHU_MAGNITUDE_SCALING_BASE: Final[float] = 2.71828
"""The literal the USGS code uses in place of e. Kept so the reproduction is exact."""

OPEN_QUESTIONS: Final[tuple[str, ...]] = (
    "Nowicki Jessee interaction sign. The operational code adds +0.01 * ln(PGV) * slope "
    "(gfail/models/jessee_2018.py COEFFS['b6'] = 0.01, and the same value in the 'slim' "
    "variant, both applied as X += term * coeff). Secondary descriptions of the paper give the "
    "interaction as negative. rupture implements the operational value because that is the "
    "coefficient the published Gorkha product was computed with, and because it is the only "
    "value rupture could verify against a primary machine-readable source. The paper's own "
    "Table has not been read by this implementation; the sign is therefore an open question, "
    "not a settled one.",
    "Lithology and land-cover coefficients. These are per-class values baked into two USGS "
    "global rasters (GLIM_replace.tif, globcover_replace.tif). rupture could not obtain either "
    "raster or the per-class tables from a machine-readable source, so it does not carry them. "
    "They are covariates, and an absent covariate is a declared gap.",
)
