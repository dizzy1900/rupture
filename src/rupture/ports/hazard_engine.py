"""Port: PSHA and scenario ground-motion calculations."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from pydantic import Field

from rupture.domain import HazardCurveSet, RuptureModel


def _default_imts() -> dict[str, tuple[float, ...]]:
    return {"PGA": (0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0)}


class ClassicalPSHAJob(RuptureModel):
    """Typed description of a classical PSHA run. Paths are to NRML/CSV inputs on disk."""

    id: str
    description: str
    source_model_logic_tree: Path
    gsim_logic_tree: Path
    sites_csv: Path | None = None
    region_grid_spacing_km: float | None = Field(default=None, gt=0.0)
    region_wkt: str | None = None
    investigation_time_years: float = Field(default=50.0, gt=0.0)
    imts: dict[str, tuple[float, ...]] = Field(default_factory=_default_imts)
    truncation_level: float = Field(default=3.0, ge=0.0)
    maximum_distance_km: float = Field(default=200.0, gt=0.0)
    reference_vs30: float = Field(default=760.0, gt=0.0)
    number_of_logic_tree_samples: int = Field(default=0, ge=0)
    random_seed: int = 42


class ScenarioGroundMotionJob(RuptureModel):
    """Typed description of a scenario ground-motion field calculation."""

    id: str
    description: str
    rupture_model: Path
    gsim: str
    sites_csv: Path
    imts: tuple[str, ...] = ("PGA",)
    number_of_ground_motion_fields: int = Field(default=100, ge=1)
    truncation_level: float = Field(default=3.0, ge=0.0)
    maximum_distance_km: float = Field(default=200.0, gt=0.0)
    reference_vs30: float = Field(default=760.0, gt=0.0)
    random_seed: int = 42


@runtime_checkable
class HazardEngine(Protocol):
    engine_id: str
    engine_version: str

    def available(self) -> tuple[bool, str]:
        """(True, '') when the engine can run here; else (False, reason) — printed, never hidden."""
        ...

    def run_classical(self, job: ClassicalPSHAJob, work_dir: Path) -> HazardCurveSet: ...

    def run_scenario(self, job: ScenarioGroundMotionJob, work_dir: Path) -> Path:
        """Runs the scenario; returns the directory of exported ground-motion fields."""
        ...
