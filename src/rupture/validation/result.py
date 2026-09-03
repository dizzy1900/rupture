"""Common result type for validation gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class GateStatus(StrEnum):
    """Outcome of a gate. SKIPPED is only legal with an explicit, printed reason."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_IMPLEMENTED = "not_implemented"


@dataclass(slots=True)
class GateResult:
    """What a gate found. ``findings`` are human-readable lines; ``reason`` explains a skip."""

    name: str
    status: GateStatus
    findings: list[str] = field(default_factory=list)
    reason: str | None = None

    @property
    def ok(self) -> bool:
        """True when the gate does not block promotion (passed, or skipped with a reason)."""
        return self.status == GateStatus.PASSED or (
            self.status == GateStatus.SKIPPED and self.reason is not None
        )

    def render(self) -> str:
        """Multi-line summary for the terminal."""
        head = f"[{self.status.value.upper():>15}] {self.name}"
        lines = [head]
        if self.reason:
            lines.append(f"    reason: {self.reason}")
        lines.extend(f"    - {f}" for f in self.findings)
        return "\n".join(lines)
