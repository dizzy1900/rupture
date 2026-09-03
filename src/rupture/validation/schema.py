"""Contract-drift gate: contracts/*.json must match the domain models exactly."""

from __future__ import annotations

from pathlib import Path

from rupture.domain import contracts
from rupture.validation.result import GateResult, GateStatus


def run(repo_root: Path) -> GateResult:
    drifted = contracts.drift(repo_root / "contracts")
    if drifted:
        return GateResult(
            name="validate-schema",
            status=GateStatus.FAILED,
            findings=[
                f"{n}: differs from the domain model (run `make schema-export`)" for n in drifted
            ],
        )
    return GateResult(
        name="validate-schema",
        status=GateStatus.PASSED,
        findings=[f"{len(contracts.CONTRACTS)} contracts match"],
    )
