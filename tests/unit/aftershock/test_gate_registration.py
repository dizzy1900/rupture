"""The gate is registered and importable. Running it is `make validate-aftershock` (about 60 s)."""

from __future__ import annotations

from pathlib import Path

from rupture.validation import aftershock as gate
from rupture.validation.registry import GATES

MK_FILE = Path(__file__).resolve().parents[3] / "mk" / "aftershock.mk"


def test_the_gate_name_is_registered() -> None:
    assert "aftershock" in GATES


def test_the_gate_exposes_run() -> None:
    assert callable(gate.run)
    assert gate.RUNTIME_BUDGET_S <= 90.0


def test_the_make_fragment_registers_the_target() -> None:
    text = MK_FILE.read_text(encoding="utf-8")
    assert "VALIDATE_GATES += validate-aftershock" in text
    assert "rupture validate aftershock" in text
