"""The 2015 Gorkha reproduction case, wired to the committed offline fixtures.

Gorkha (ComCat ``us20002926``, Mw 7.8, 2015-04-25) is the reference case because it is one of
the events for which the USGS actually published a ``ground-failure`` product, so rupture's
implementation can be held against a real answer rather than against itself.

Everything here reads ``tests/fixtures/cascade/gorkha-2015/``: real slices of the published
ShakeMap Atlas grid and of the two published ground-failure rasters, with their provenance. No
network, and nothing synthesised.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rupture.adapters.cascade.product import PublishedCoverage, read_coverage_csv
from rupture.adapters.cascade.reproduction import ReproductionReport, reproduce
from rupture.adapters.cascade.shakemap import ShakeMapGrid, read_slice_csv
from rupture.cascade.coefficients import NOWICKI_JESSEE_2018, ZHU_2017_GENERAL
from rupture.cascade.models import LogisticGroundFailureModel, NowickiJessee2018, Zhu2017General

EVENT_ID = "us20002926"
MAGNITUDE = 7.8
FIXTURE_DIR = Path("tests") / "fixtures" / "cascade" / "gorkha-2015"

SHAKEMAP_VERSION = "1"
SHAKEMAP_URL = (
    "https://earthquake.usgs.gov/product/shakemap/us20002926/atlas/1594162031303/"
    "download/grid.xml"
)


@dataclass(frozen=True, slots=True)
class ModelCase:
    """One published model and the thresholds the comparison uses for it."""

    model_id: str
    coverage_file: str
    cell_size_deg: float
    coverage_threshold: float
    threshold_reason: str


CASES: tuple[ModelCase, ...] = (
    ModelCase(
        model_id=ZHU_2017_GENERAL.model_id,
        coverage_file="usgs_zhu_2017_general_coverage_slice.csv",
        cell_size_deg=4.0 / 240.0,
        coverage_threshold=0.005,
        threshold_reason=(
            "the model's own maskthreshold in zhu_2017_general.ini; below it the published "
            "raster's 4-dp rounding makes the coverage transform uninvertible"
        ),
    ),
    ModelCase(
        model_id=NOWICKI_JESSEE_2018.model_id,
        coverage_file="usgs_jessee_2018_coverage_slice.csv",
        cell_size_deg=8.0 / 480.0,
        coverage_threshold=0.002,
        threshold_reason=(
            "the model's own maskthreshold in jessee_2018.ini; below it the published raster's "
            "4-dp rounding makes the coverage transform uninvertible"
        ),
    ),
)

CASE_FOR_MODEL = {case.model_id: case for case in CASES}


def fixture_dir(repo_root: Path) -> Path:
    return repo_root / FIXTURE_DIR


def load_shakemap(repo_root: Path) -> ShakeMapGrid:
    """The committed slice of the ShakeMap the ground-failure product was computed from."""
    base = fixture_dir(repo_root)
    return read_slice_csv(
        base / "shakemap_grid_slice.csv",
        event_id=EVENT_ID,
        magnitude=MAGNITUDE,
        shakemap_version=SHAKEMAP_VERSION,
        source_url=SHAKEMAP_URL,
    )


def load_published(repo_root: Path, case: ModelCase) -> PublishedCoverage:
    base = fixture_dir(repo_root)
    return read_coverage_csv(
        base / case.coverage_file,
        model_id=case.model_id,
        provenance_path=base / "provenance.json",
        cell_size_deg=case.cell_size_deg,
    )


def build_model(case: ModelCase) -> LogisticGroundFailureModel:
    if case.model_id == ZHU_2017_GENERAL.model_id:
        return Zhu2017General(cell_size_deg=case.cell_size_deg)
    return NowickiJessee2018(cell_size_deg=case.cell_size_deg)


def run_case(repo_root: Path, case: ModelCase) -> ReproductionReport:
    """Reproduce one published Gorkha ground-failure raster and report what was achieved."""
    return reproduce(
        build_model(case),
        published=load_published(repo_root, case),
        shakemap=load_shakemap(repo_root),
        magnitude=MAGNITUDE,
        event_id=EVENT_ID,
        coverage_threshold=case.coverage_threshold,
    )


def run_all(repo_root: Path) -> dict[str, ReproductionReport]:
    return {case.model_id: run_case(repo_root, case) for case in CASES}
