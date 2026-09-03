"""The ``make validate-*`` gates. Each gate is a function returning a :class:`GateResult`."""

from rupture.validation.result import GateResult, GateStatus

__all__ = ["GateResult", "GateStatus"]
