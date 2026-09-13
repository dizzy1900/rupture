"""Git ancestry is the timestamp. Exit codes are distinguished; only 0 means pass.

``git merge-base --is-ancestor`` exits 0 when the first commit is an ancestor of the second,
1 when it is not, and 128 when the object is missing (a depth-1 clone, a typo, a rewritten
history). ADR-0056 decision 3: 128 is an *error*, never a negative and never a skip. Decision 5:
a shallow clone fails the check; it does not skip it.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

SHALLOW_REMEDY = (
    "shallow clone: git rev-parse --is-shallow-repository is true, so ancestry cannot be "
    "verified. This is an error, not a skip. Remedy: checkout with fetch-depth: 0 (a blobless "
    "filter clone is fine; depth 1 is not). serac already sets fetch-depth: 0; rupture's "
    ".github/workflows/ci.yml currently does not — the orchestrator must add it with this gate."
)


class GitError(RuntimeError):
    """A git invocation failed in a way that is not a yes/no ancestry answer."""

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class AncestryClass(StrEnum):
    """How a (C_P, C_D) pair relates, per ADR-0056 decisions 2, 3 and 6."""

    STRONG = "strong"
    WEAK_DATA_PREDATES = "weak_data_predates"
    FAIL = "fail"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class AncestryVerdict:
    """Result of :func:`classify`. ``ERROR`` and ``FAIL`` block the gate; the rest do not."""

    classification: AncestryClass
    registration_commit: str | None
    data_commit: str | None
    detail: str

    @property
    def blocks(self) -> bool:
        """True when this pair must fail the gate rather than be labelled and allowed."""
        return self.classification in (AncestryClass.FAIL, AncestryClass.ERROR)


def parse_is_shallow_output(text: str) -> bool:
    """Parse ``git rev-parse --is-shallow-repository`` stdout (``true`` / ``false``)."""
    value = text.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    msg = f"unrecognised --is-shallow-repository output: {text!r}"
    raise GitError(msg)


def _git(repo_root: Path, *args: str, timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_root), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise GitError("git is not on PATH", exit_code=None) from exc
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError(f"git {' '.join(args)} failed: {exc}", exit_code=None) from exc


def is_shallow_repository(repo_root: Path) -> bool:
    """True when this clone has truncated history and cannot verify ancestry."""
    proc = _git(repo_root, "rev-parse", "--is-shallow-repository")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise GitError(
            f"git rev-parse --is-shallow-repository exited {proc.returncode}: {err}",
            exit_code=proc.returncode,
        )
    return parse_is_shallow_output(proc.stdout)


def add_commits(repo_root: Path, path: str) -> tuple[str, ...]:
    """Every commit that *added* ``path``, oldest first.

    ADR-0056 failure mode 5: a path that was deleted and re-added yields more than one commit.
    The gate requires exactly one candidate rather than picking, which would let a re-add
    launder a late registration.
    """
    proc = _git(
        repo_root,
        "log",
        "--diff-filter=A",
        "--reverse",
        "--format=%H",
        "--",
        path,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise GitError(
            f"git log --diff-filter=A exited {proc.returncode} for {path!r}: {err}",
            exit_code=proc.returncode,
        )
    return tuple(line.strip() for line in proc.stdout.splitlines() if line.strip())


def earliest_add_commit(repo_root: Path, path: str) -> str:
    """The oldest add-commit for ``path``. Raises if git failed or nothing added the path."""
    commits = add_commits(repo_root, path)
    if not commits:
        msg = f"no add-commit for {path!r}; the path is not in git history"
        raise GitError(msg, exit_code=None)
    return commits[0]


def is_ancestor(repo_root: Path, ancestor: str, descendant: str) -> bool:
    """True iff ``ancestor`` is an ancestor of ``descendant`` (including equality).

    Exit 0 is True, exit 1 is False. Any other exit — 128 when the object is missing — raises
    :class:`GitError`. Callers must not treat that as a negative.
    """
    proc = _git(repo_root, "merge-base", "--is-ancestor", ancestor, descendant)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    err = (proc.stderr or proc.stdout or "").strip()
    raise GitError(
        f"git merge-base --is-ancestor exited {proc.returncode} ({ancestor} {descendant}): {err}",
        exit_code=proc.returncode,
    )


def commits_after(repo_root: Path, commit: str, path: str) -> tuple[str, ...]:
    """Commits reachable from HEAD that touch ``path`` after ``commit`` (the freeze check)."""
    proc = _git(repo_root, "log", "--format=%H", f"{commit}..HEAD", "--", path)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise GitError(
            f"git log {commit}..HEAD -- {path!r} exited {proc.returncode}: {err}",
            exit_code=proc.returncode,
        )
    return tuple(line.strip() for line in proc.stdout.splitlines() if line.strip())


def classify(
    repo_root: Path,
    registration_commit: str,
    data_commit: str,
    *,
    claim_strong: bool = False,
) -> AncestryVerdict:
    """Classify (C_P, C_D).

    * ``STRONG`` — C_P is an ancestor of C_D (registration preceded the data).
    * ``WEAK_DATA_PREDATES`` — C_D is an ancestor of C_P (the usual retrospective case).
    * ``FAIL`` — registration after data while claiming the strong form, or neither commit
      is an ancestor of the other.
    * ``ERROR`` — git failed, the clone is shallow, or an object is missing (exit 128).
    """
    try:
        if is_shallow_repository(repo_root):
            return AncestryVerdict(
                AncestryClass.ERROR, registration_commit, data_commit, SHALLOW_REMEDY
            )
        registration_precedes = is_ancestor(repo_root, registration_commit, data_commit)
        if registration_precedes:
            return AncestryVerdict(
                AncestryClass.STRONG,
                registration_commit,
                data_commit,
                "C_P is an ancestor of C_D",
            )
        data_precedes = is_ancestor(repo_root, data_commit, registration_commit)
    except GitError as exc:
        return AncestryVerdict(AncestryClass.ERROR, registration_commit, data_commit, str(exc))
    if data_precedes:
        if claim_strong:
            return AncestryVerdict(
                AncestryClass.FAIL,
                registration_commit,
                data_commit,
                "registration after data and claiming strong",
            )
        return AncestryVerdict(
            AncestryClass.WEAK_DATA_PREDATES,
            registration_commit,
            data_commit,
            "preregistration: weak (data predates registration)",
        )
    return AncestryVerdict(
        AncestryClass.FAIL,
        registration_commit,
        data_commit,
        "neither commit is an ancestor of the other",
    )
