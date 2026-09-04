"""The learned-model hook: documented, reserved, and deliberately not implemented.

The brief asks for a documented hook for a learned global model as v1 and asks that it **not** be
trained. These tests hold both halves: the seam exists and says what an implementation owes, and
nothing in the repository answers to it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rupture.cascade import learned, models


def test_constructing_the_hook_raises_and_says_what_it_is() -> None:
    with pytest.raises(NotImplementedError) as excinfo:
        learned.LearnedGroundFailureModel()
    message = str(excinfo.value)
    assert "documented hook" in message
    assert "ADR-0042" in message
    assert "rupture.ports.cascade.CascadeModel" in message


def test_nothing_answers_to_the_reserved_id() -> None:
    """Not registered is the point: a hook that resolved would be an untrained model shipping."""
    assert learned.MODEL_ID not in models.MODEL_CLASSES
    assert learned.MODEL_ID not in models.ALIASES
    with pytest.raises(KeyError, match="unknown cascade model"):
        models.build(learned.MODEL_ID)


def test_the_contract_an_implementation_must_meet_is_explicit() -> None:
    requirements = " | ".join(learned.REQUIRED_OF_AN_IMPLEMENTATION)
    assert "CascadeModel" in requirements
    assert "GroundFailureField" in requirements
    assert "provenance" in requirements
    assert "ADR-0022" in requirements  # the leakage rule, if it is ever fitted here
    assert "reproduction" in requirements
    assert "chamoli" in requirements


def test_the_repository_states_it_is_not_trained_here(repo_root: Path) -> None:
    adr = repo_root / "docs" / "adr" / "0036-learned-ground-failure-hook.md"
    assert adr.is_file(), "the hook must be recorded as an ADR, not only in a docstring"
    text = adr.read_text(encoding="utf-8")
    assert "not train" in text or "not trained" in text
    cascade_doc = (repo_root / "docs" / "CASCADE.md").read_text(encoding="utf-8")
    assert "learned" in cascade_doc.lower()
    assert "0036-learned-ground-failure-hook.md" in cascade_doc
