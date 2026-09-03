"""Gate registry: ``rupture validate <name>`` imports ``rupture.validation.<name>`` and runs it.

Phase-2 agents add a gate by dropping a module here that exposes ``run() -> GateResult``; nothing
else needs editing. Unknown or not-yet-written gates report NOT_IMPLEMENTED rather than failing
silently or pretending to pass.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from typing import cast

from rupture.validation.result import GateResult, GateStatus

GATES: tuple[str, ...] = (
    "language",
    "schema",
    "catalog",
    "etas",
    "eval",
    "hazard",
    "cascade",
    "risk",
    "aftershock",
)

PHASE_FOR_GATE: dict[str, str] = {
    "catalog": "Phase 2A (catalog-engineer)",
    "etas": "Phase 2B (forecast-engineer)",
    "eval": "Phase 2B (forecast-engineer)",
    "hazard": "Phase 2C (hazard-engineer)",
    "cascade": "Phase 2D (cascade-engineer)",
    "aftershock": "Prompt 2 C4 (ops-forecaster)",
}


def run_gate(name: str, repo_root: Path) -> GateResult:
    if name not in GATES:
        return GateResult(
            name=f"validate-{name}", status=GateStatus.FAILED, findings=[f"unknown gate {name!r}"]
        )
    try:
        module = importlib.import_module(f"rupture.validation.{name}")
    except ModuleNotFoundError as exc:
        if exc.name != f"rupture.validation.{name}":
            raise
        return GateResult(
            name=f"validate-{name}",
            status=GateStatus.NOT_IMPLEMENTED,
            reason=f"not implemented yet: delivered in {PHASE_FOR_GATE.get(name, 'a later phase')}",
        )
    run = cast("Callable[[Path], GateResult]", module.run)
    return run(repo_root)
