"""Port: earthquake-triggered ground failure and co-seismic slope exposure."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from rupture.domain.cascade import CascadeExposure, GroundFailureField
from rupture.domain.groundmotion import GroundMotionField


@runtime_checkable
class CascadeModel(Protocol):
    """A ground-failure model: shaking plus static conditioning factors to susceptibility."""

    model_id: str
    model_version: str
    source_refs: tuple[str, ...]

    def evaluate(self, field: GroundMotionField, *, scenario_id: str) -> GroundFailureField: ...


@runtime_checkable
class SlopeUnitSource(Protocol):
    """Slope units, read from the sibling serac's export or a committed fixture."""

    source_id: str

    def units_for(self, aoi_id: str) -> tuple[dict[str, object], ...]: ...

    def exposure(
        self, field: GroundMotionField, *, aoi_id: str, pga_threshold_g: float
    ) -> CascadeExposure: ...
