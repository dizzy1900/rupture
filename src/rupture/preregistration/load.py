"""Discover and parse ``experiments/<id>/preregistration.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from rupture.domain.common import sha256_hex
from rupture.domain.preregistration import Preregistration

REGISTRATION_FILENAME = "preregistration.yaml"
EXPERIMENTS_DIRNAME = "experiments"


def file_sha256(path: Path) -> str:
    """sha256 of the file bytes, as the scoring run records for the freeze check."""
    return sha256_hex(path.read_bytes())


def parse_preregistration_yaml(text: str) -> Preregistration:
    """Parse a YAML document into :class:`Preregistration`.

    Raises ``ValueError`` on a non-mapping document or a schema failure.
    """
    payload: Any = yaml.safe_load(text)
    if not isinstance(payload, dict):
        msg = "preregistration YAML must be a mapping"
        raise ValueError(msg)
    try:
        return Preregistration.model_validate(payload)
    except ValidationError as exc:
        msg = _format_validation(exc)
        raise ValueError(msg) from exc


def _format_validation(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(item) for item in error["loc"]) or "(root)"
        parts.append(f"{loc}: {error['msg']}")
    return "; ".join(parts)


def discover(repo_root: Path) -> tuple[Path, ...]:
    """``experiments/*/preregistration.yaml``, ignoring README and underscore-prefixed names."""
    root = repo_root / EXPERIMENTS_DIRNAME
    if not root.is_dir():
        return ()
    found: list[Path] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name.startswith("."):
            continue
        candidate = child / REGISTRATION_FILENAME
        if candidate.is_file():
            found.append(candidate)
    return tuple(found)
