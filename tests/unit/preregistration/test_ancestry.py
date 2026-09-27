"""Ancestry helpers against this repository's history and against throwaway git repos."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rupture.preregistration.ancestry import (
    AncestryClass,
    GitError,
    add_commits,
    classify,
    commits_after,
    earliest_add_commit,
    is_ancestor,
    is_shallow_repository,
    parse_is_shallow_output,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
CLAUDE_MD = "CLAUDE.md"
MISSING = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=check,
    )


def _init_repo(root: Path) -> None:
    _run_git(root, "init", "-b", "main")


def _commit(root: Path, message: str) -> str:
    _run_git(
        root,
        "-c",
        "user.email=prereg@test",
        "-c",
        "user.name=prereg",
        "-c",
        "commit.gpgsign=false",
        "-c",
        "core.hooksPath=/dev/null",
        "commit",
        "-m",
        message,
    )
    return _run_git(root, "rev-parse", "HEAD").stdout.strip()


def _write_add_commit(root: Path, relpath: str, content: str, message: str) -> str:
    path = root / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _run_git(root, "add", "--", relpath)
    return _commit(root, message)


def test_parse_is_shallow_output_accepts_true_and_false() -> None:
    assert parse_is_shallow_output("true\n") is True
    assert parse_is_shallow_output("false") is False
    with pytest.raises(GitError, match="unrecognised"):
        parse_is_shallow_output("maybe")


def test_this_worktree_is_not_shallow() -> None:
    assert is_shallow_repository(REPO_ROOT) is False


def test_claude_md_add_commit_is_an_ancestor_of_head() -> None:
    added = add_commits(REPO_ROOT, CLAUDE_MD)
    assert len(added) == 1
    c_p = earliest_add_commit(REPO_ROOT, CLAUDE_MD)
    assert c_p == added[0]
    assert is_ancestor(REPO_ROOT, c_p, "HEAD") is True


def test_a_missing_object_is_an_error_not_a_negative() -> None:
    with pytest.raises(GitError, match="exited 128") as exc_info:
        is_ancestor(REPO_ROOT, MISSING, "HEAD")
    assert exc_info.value.exit_code == 128
    verdict = classify(REPO_ROOT, MISSING, "HEAD")
    assert verdict.classification is AncestryClass.ERROR
    assert verdict.blocks


def test_registration_before_data_is_strong(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    c_p = _write_add_commit(tmp_path, "prereg.yaml", "p\n", "register")
    c_d = _write_add_commit(tmp_path, "data.txt", "d\n", "data")
    verdict = classify(tmp_path, c_p, c_d)
    assert verdict.classification is AncestryClass.STRONG
    assert not verdict.blocks


def test_data_before_registration_is_weak(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    c_d = _write_add_commit(tmp_path, "data.txt", "d\n", "data")
    c_p = _write_add_commit(tmp_path, "prereg.yaml", "p\n", "register")
    verdict = classify(tmp_path, c_p, c_d)
    assert verdict.classification is AncestryClass.WEAK_DATA_PREDATES
    assert "weak (data predates registration)" in verdict.detail
    assert not verdict.blocks


def test_data_before_registration_fails_when_claiming_strong(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    c_d = _write_add_commit(tmp_path, "data.txt", "d\n", "data")
    c_p = _write_add_commit(tmp_path, "prereg.yaml", "p\n", "register")
    verdict = classify(tmp_path, c_p, c_d, claim_strong=True)
    assert verdict.classification is AncestryClass.FAIL
    assert verdict.blocks
    assert "claiming strong" in verdict.detail


def test_orphan_histories_fail(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    c_p = _write_add_commit(tmp_path, "prereg.yaml", "p\n", "register")
    _run_git(tmp_path, "checkout", "--orphan", "other")
    _run_git(tmp_path, "rm", "-rf", "--cached", ".")
    c_d = _write_add_commit(tmp_path, "data.txt", "d\n", "unrelated data")
    verdict = classify(tmp_path, c_p, c_d)
    assert verdict.classification is AncestryClass.FAIL
    assert "neither commit" in verdict.detail


def test_commits_after_sees_a_later_touch(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    c_p = _write_add_commit(tmp_path, "prereg.yaml", "p\n", "register")
    assert commits_after(tmp_path, c_p, "prereg.yaml") == ()
    (tmp_path / "prereg.yaml").write_text("p2\n", encoding="utf-8")
    _run_git(tmp_path, "add", "--", "prereg.yaml")
    later = _commit(tmp_path, "amend in place")
    assert commits_after(tmp_path, c_p, "prereg.yaml") == (later,)
