"""Banned-language gate.

rupture does not predict earthquakes. This scan enforces that the repository never claims to.
The single permitted sentence and the glossary entries that explain the distinction live in the
allowlist file next to this module; anything else that matches a banned pattern fails the gate.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from rupture.validation.result import GateResult, GateStatus

# Patterns are matched case-insensitively on each line of text.
BANNED_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bpredict(?:s|ed|ing|ion|ions|or|ors|ive|ability)?\b", "predict*"),
    (r"\bearly[- ]warning\b", "early warning (rupture is not an EEW system)"),
    (r"\bwill occur\b", "deterministic claim: 'will occur'"),
    (r"\bwill (?:strike|hit|happen)\b", "deterministic claim: 'will strike/hit/happen'"),
    (r"\bnext big one\b", "'next big one'"),
    (r"\bimminent\b", "'imminent'"),
)

SCANNED_SUFFIXES = {".py", ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".cfg", ".ini"}
SKIPPED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    ".dvc",
    "reports",
    ".import_linter_cache",
}

ALLOWLIST_FILE = Path(__file__).with_name("banned_language_allowlist.txt")
# A line carrying this marker is exempt (used by tests that must spell out a violation).
INLINE_ALLOW_MARKER = "lang-gate: allow"
# The gate's own module defines the patterns and is not scanned.
SELF = Path(__file__).resolve()


def load_allowlist(path: Path = ALLOWLIST_FILE) -> list[str]:
    """Exact line fragments that are permitted even though they match a banned pattern."""
    if not path.exists():
        return []
    return [
        ln.strip()
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def iter_files(root: Path) -> Iterable[Path]:
    """Yield scannable text files under ``root``, skipping caches, venvs and generated output."""
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in SCANNED_SUFFIXES:
            continue
        if any(part in SKIPPED_DIRS for part in p.relative_to(root).parts):
            continue
        if p.name == ALLOWLIST_FILE.name or p.resolve() == SELF:
            continue
        yield p


def scan_text(text: str, *, allowlist: list[str], label: str) -> list[str]:
    """Return findings for one text blob.

    An allowlisted fragment exempts **only itself**, not the line it sits on. That distinction is
    the whole security of this gate: allowlisting a line would let a claim ride along beside a
    permitted phrase, and the permitted phrases are published paper titles that live in citation
    tables, where a markdown row is a single line. So each fragment is removed from the line and
    the remainder is scanned. The inline marker is different by design: it exempts a whole line,
    and it is only for test strings that must spell out a violation.
    """
    findings: list[str] = []
    compiled = [(re.compile(pat, re.IGNORECASE), why) for pat, why in BANNED_PATTERNS]
    for lineno, line in enumerate(text.splitlines(), start=1):
        if INLINE_ALLOW_MARKER in line:
            continue
        remainder = line
        for frag in allowlist:
            if frag in remainder:
                remainder = remainder.replace(frag, " ")
        for rx, why in compiled:
            if rx.search(remainder):
                findings.append(f"{label}:{lineno}: {why}: {line.strip()[:120]}")
                break
    return findings


def run(root: Path, *, allowlist: list[str] | None = None) -> GateResult:
    """Scan the tree rooted at ``root``."""
    allow = load_allowlist() if allowlist is None else allowlist
    findings: list[str] = []
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(text, allowlist=allow, label=str(path.relative_to(root))))
    status = GateStatus.PASSED if not findings else GateStatus.FAILED
    return GateResult(name="validate-language", status=status, findings=findings)
