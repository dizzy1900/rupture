"""Port: scenario and event-based ground-motion calculation.

Two adapters implement this (ADR-0020): the OpenQuake engine in its pinned container, which is
authoritative but runs only where the image's architecture matches the host, and a native GSIM
evaluator verified against OpenQuake's own published test vectors, which runs anywhere. Every
field records which one produced it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from rupture.domain.groundmotion import GroundMotionField, Site
from rupture.domain.hazard import ScenarioRupture


@runtime_checkable
class GroundMotionEngine(Protocol):
    engine_id: str
    engine_version: str

    def available(self) -> tuple[bool, str]:
        """``(True, '')`` when this engine can run here; else ``(False, reason)``, printed."""
        ...

    def scenario(
        self,
        rupture: ScenarioRupture,
        sites: tuple[Site, ...],
        *,
        imt: str = "PGA",
        gsim: str,
        n_realisations: int = 1,
        truncation_level: float = 3.0,
        seed: int | None = None,
    ) -> GroundMotionField:
        """Ground-motion field for one rupture at the given sites."""
        ...

    def supported_gsims(self) -> tuple[str, ...]:
        """GSIMs this engine can evaluate; a GSIM absent here must not be requested."""
        ...
