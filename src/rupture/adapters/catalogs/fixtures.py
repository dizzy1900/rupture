"""Offline fixture support shared by the catalogue adapters.

A fixture directory (``data/fixtures/<source>/``) holds real payloads cut by the adapter plus a
``provenance.json`` describing every file: the exact URL / query, ``retrieved_at``, the
``sha256`` of the file as committed, and the licence. Nothing here is edited by hand; the
adapters regenerate the files and this module refuses a file whose digest does not match.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rupture.domain import Provenance, sha256_hex

PROVENANCE_FILE = "provenance.json"


class FixtureError(RuntimeError):
    """A fixture is missing, undocumented or does not match its recorded digest."""


@dataclass(frozen=True, slots=True)
class FixtureFile:
    """One committed payload with the provenance recorded for it."""

    path: Path
    provenance: Provenance
    query: dict[str, Any]
    content: bytes


def load_fixture_dir(directory: Path, *, adapter_version: str) -> list[FixtureFile]:
    """Read every file listed in ``directory/provenance.json`` and verify its sha256.

    Files present on disk but not listed are ignored (and reported by the catalog gate); listed
    files that are missing or altered raise :class:`FixtureError`.
    """
    prov_path = directory / PROVENANCE_FILE
    if not prov_path.exists():
        msg = f"fixture directory {directory} has no {PROVENANCE_FILE}"
        raise FixtureError(msg)
    meta = json.loads(prov_path.read_text(encoding="utf-8"))
    files: dict[str, dict[str, Any]] = meta.get("files", {})
    out: list[FixtureFile] = []
    for name, info in sorted(files.items()):
        path = directory / name
        if not path.exists():
            msg = f"fixture {path} listed in {prov_path} is missing"
            raise FixtureError(msg)
        content = path.read_bytes()
        digest = sha256_hex(content)
        if digest != info["sha256"]:
            msg = f"fixture {path} sha256 {digest} != recorded {info['sha256']} (edited by hand?)"
            raise FixtureError(msg)
        prov = Provenance(
            source=meta["source"],
            source_url=info.get("source_url"),
            retrieved_at=datetime.fromisoformat(info["retrieved_at"]),
            sha256=digest,
            licence=meta.get("licence"),
            adapter_version=adapter_version,
            notes=info.get("notes") or f"offline fixture {directory.name}/{name}",
        )
        out.append(
            FixtureFile(path=path, provenance=prov, query=info.get("query", {}), content=content)
        )
    return out


def write_fixture_provenance(
    directory: Path,
    *,
    source: str,
    licence: str | None,
    adapter_version: str,
    files: dict[str, dict[str, Any]],
    notes: str | None = None,
) -> Path:
    """Write ``provenance.json`` for a fixture directory (used by the refresh tooling only)."""
    directory.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "source": source,
        "licence": licence,
        "adapter_version": adapter_version,
        "rule": "never edited by hand; regenerate with the adapter and re-record provenance",
        "files": dict(sorted(files.items())),
    }
    if notes:
        payload["notes"] = notes
    path = directory / PROVENANCE_FILE
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
