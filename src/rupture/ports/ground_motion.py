"""Port: scenario and event-based ground-motion calculation.

Two adapters implement this (ADR-0020): the OpenQuake engine in its pinned container, which is
authoritative but runs only where the image's architecture matches the host, and a native GSIM
evaluator verified against OpenQuake's own published test vectors, which runs anywhere. Every
field records which one produced it.

The port is **three** protocols rather than one, because the two engines are not capable of the
same things and a single protocol would force one of them to carry a method it can only raise
from (ADR-0043):

``GroundMotionEngine``
    A scenario field for one rupture. Both adapters implement it.
``LogicTreeGroundMotionEngine``
    ...and a field whose realisations are shared between the branches of a GSIM logic tree by
    weight. Both adapters implement it.
``EventBasedGroundMotionEngine``
    ...and a full event-based calculation: sample a stochastic event set from a rate model over
    an investigation time and return the ground motion for every sampled rupture with the rate it
    carries. Only the OpenQuake adapter implements this; the native engine's own event-based path
    goes through :mod:`rupture.risk.event_set`, which samples the event set from a promoted F1
    forecast rather than from a source model, and then reuses ``scenario`` per event.

A caller that needs a capability checks for the method (``isinstance(engine, ...)``), because a
``runtime_checkable`` Protocol checks exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from rupture.domain.groundmotion import GroundMotionField, GsimLogicTree, Site
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


@runtime_checkable
class LogicTreeGroundMotionEngine(GroundMotionEngine, Protocol):
    """An engine that can evaluate a weighted GSIM logic tree, not just one model."""

    def scenario_logic_tree(
        self,
        rupture: ScenarioRupture,
        sites: tuple[Site, ...],
        *,
        tree: GsimLogicTree,
        imt: str = "PGA",
        n_realisations: int = 1,
        truncation_level: float = 3.0,
        seed: int | None = None,
    ) -> GroundMotionField:
        """One field whose realisations are allocated between the tree's branches by weight."""
        ...


@runtime_checkable
class EventBasedGroundMotionEngine(GroundMotionEngine, Protocol):
    """An engine that can run a full event-based calculation from a rate model."""

    def event_based(
        self,
        source_model_xml: str,
        sites: tuple[Site, ...],
        *,
        tree: GsimLogicTree,
        investigation_time_years: float,
        ses_per_logic_tree_path: int,
        imt: str = "PGA",
        truncation_level: float = 3.0,
        seed: int | None = None,
    ) -> EventBasedGroundMotion:
        """Ground motion for every rupture of a stochastic event set, with each event's rate."""
        ...


@dataclass(frozen=True, slots=True)
class EventBasedGroundMotion:
    """The result of an event-based run: one field per sampled rupture, each with its rate.

    ``occurrence_rate_per_year`` is the rate a *single* sampled event stands for, which for an
    event-based calculation is ``1 / (investigation_time * ses_per_logic_tree_path *
    number_of_logic_tree_samples)`` — every event in a stochastic event set is equally weighted,
    the rate information having been consumed when the set was sampled.
    """

    fields: tuple[GroundMotionField, ...]
    magnitudes: tuple[float, ...]
    occurrence_rate_per_year: float
    investigation_time_years: float
    ses_per_logic_tree_path: int
    n_realisations: int
    engine_id: str
    engine_version: str
    notes: str | None = None
