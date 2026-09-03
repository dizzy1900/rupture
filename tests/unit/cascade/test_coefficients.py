"""Every coefficient rupture carries must still equal its published source.

The committed USGS reference-implementation files are the source of truth; this test re-parses
them rather than restating the numbers, so a typo in either place fails.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rupture.cascade import coefficients as coef

_FLOAT = r"-?\d+(?:\.\d*)?(?:e-?\d+)?"


def parse_block(text: str, name: str) -> dict[str, float]:
    match = re.search(rf"\b{name}\s*=\s*\{{(.*?)\}}", text, flags=re.S)
    assert match is not None, f"{name} not found in the committed USGS source"
    return {k: float(v) for k, v in re.findall(rf'"(\w+)"\s*:\s*({_FLOAT})', match.group(1))}


def test_jessee_coefficients_match_the_committed_usgs_source(usgs_fixtures: Path) -> None:
    published = parse_block((usgs_fixtures / "jessee_2018.py.txt").read_text(), "COEFFS")
    spec = coef.NOWICKI_JESSEE_2018
    assert spec.intercept == published["b0"]
    assert spec.coefficients["log_pgv"] == published["b1"]
    assert spec.coefficients["slope_deg"] == published["b2"]
    assert spec.coefficients["lithology_coefficient"] == published["b3"]
    assert spec.coefficients["cti"] == published["b4"]
    assert spec.coefficients["landcover_coefficient"] == published["b5"]
    assert spec.coefficients["log_pgv_x_slope_deg"] == published["b6"]


def test_jessee_coverage_coefficients_match(usgs_fixtures: Path) -> None:
    published = parse_block((usgs_fixtures / "jessee_2018.py.txt").read_text(), "COV_COEFFS")
    assert coef.NOWICKI_JESSEE_2018.coverage_coefficients == published


def test_zhu_coefficients_match_the_committed_usgs_source(usgs_fixtures: Path) -> None:
    published = parse_block((usgs_fixtures / "zhu_2017.py.txt").read_text(), "COEFFS")
    spec = coef.ZHU_2017_GENERAL
    assert spec.intercept == published["b0"]
    assert spec.coefficients["log_pgv_magnitude_scaled"] == published["b1"]
    assert spec.coefficients["log_vs30"] == published["b2"]
    assert spec.coefficients["precipitation_mm"] == published["b3"]
    assert spec.coefficients["distance_to_water_km"] == published["b4"]
    assert spec.coefficients["water_table_depth_m"] == published["b5"]


def test_zhu_coverage_coefficients_match(usgs_fixtures: Path) -> None:
    published = parse_block((usgs_fixtures / "zhu_2017.py.txt").read_text(), "COV_COEFFS")
    assert coef.ZHU_2017_GENERAL.coverage_coefficients == published


@pytest.mark.parametrize(
    ("filename", "key", "expected"),
    [
        ("zhu_2017_general.ini", "minpgv", 3.0),
        ("zhu_2017_general.ini", "minpga", 10.0),
        ("zhu_2017_general.ini", "vs30max", 620.0),
        ("zhu_2017_general.ini", "slopemin", 0.0),
        ("zhu_2017_general.ini", "slopemax", 5.0),
        ("jessee_2018.ini", "minpga", 2.0),
        ("jessee_2018.ini", "slopemin", 2.0),
        ("jessee_2018.ini", "slopemax", 90.0),
    ],
)
def test_masks_match_the_committed_ini(
    usgs_fixtures: Path, filename: str, key: str, expected: float
) -> None:
    text = (usgs_fixtures / filename).read_text()
    match = re.search(rf"^\s*{key}\s*=\s*({_FLOAT})", text, flags=re.M)
    assert match is not None
    assert float(match.group(1)) == expected


@pytest.mark.parametrize(
    ("filename", "spec", "usgs_key", "covariate"),
    [
        ("jessee_2018.py.txt", coef.NOWICKI_JESSEE_2018, "pgv", coef.Covariate.PGV_CM_S),
        ("jessee_2018.py.txt", coef.NOWICKI_JESSEE_2018, "cti", coef.Covariate.CTI),
        ("zhu_2017.py.txt", coef.ZHU_2017_GENERAL, "pgv", coef.Covariate.PGV_CM_S),
        (
            "zhu_2017.py.txt",
            coef.ZHU_2017_GENERAL,
            "precip",
            coef.Covariate.PRECIPITATION_MM,
        ),
    ],
)
def test_clips_match_the_committed_usgs_source(
    usgs_fixtures: Path,
    filename: str,
    spec: coef.GroundFailureModelSpec,
    usgs_key: str,
    covariate: coef.Covariate,
) -> None:
    text = (usgs_fixtures / filename).read_text()
    block = re.search(r"\bCLIPS\s*=\s*\{(.*?)\}", text, flags=re.S)
    assert block is not None
    published = {
        key: (float(low), float(high))
        for key, low, high in re.findall(
            rf'"(\w+)"\s*:\s*\(({_FLOAT}),\s*({_FLOAT})\)', block.group(1)
        )
    }
    clip = spec.clips[covariate]
    assert (clip.low, clip.high) == published[usgs_key]


def test_masks_and_terms_are_internally_consistent() -> None:
    for spec in coef.MODELS.values():
        # every named coefficient is either the intercept or a term the model declares
        declared = set(spec.static_terms) | set(spec.shaking_terms)
        assert declared == set(spec.coefficients), spec.model_id
        assert set(spec.term_descriptions) == set(spec.coefficients), spec.model_id
        for term in spec.static_terms:
            coef.Covariate(term)  # every static term names a real covariate


def test_the_two_open_questions_are_recorded() -> None:
    """The interaction sign and the missing per-class tables are not quietly resolved."""
    joined = " ".join(coef.OPEN_QUESTIONS).lower()
    assert "interaction" in joined
    assert "lithology" in joined
    assert "land-cover" in joined
    assert coef.NOWICKI_JESSEE_2018.coefficients["log_pgv_x_slope_deg"] == 0.01
