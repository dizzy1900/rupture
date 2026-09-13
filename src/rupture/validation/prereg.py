"""``validate-prereg``: pre-registration is a check that runs, not a promise.

ADR-0056. For each ``experiments/<id>/preregistration.yaml`` the gate validates the schema,
records the file's sha256, requires a unique add-commit C_P, refuses in-place amendments
(decision 4: amendments are new files), and classifies git ancestry of each declared
``test_data_paths`` entry against C_P.

A shallow clone **errors**, it does not skip. CI must check out with ``fetch-depth: 0``
(a blobless filter clone is fine; depth 1 is not). serac already does this; rupture's
``.github/workflows/ci.yml`` currently does not — adding this gate without that setting
makes every CI job fail the check, which is the intended failure rather than a silent skip.

This module is the gate. Git subprocesses live in :mod:`rupture.preregistration`, not in
:mod:`rupture.scoring` (import-linter: scoring imports only domain).

Orchestrator wiring (this worktree does not edit these files):

* ``src/rupture/validation/registry.py`` ``GATES``: add ``"prereg"``.
* ``PHASE_FOR_GATE``: ``"prereg": "ADR-0056 (pre-registration by git ancestry)"``.
* ``cli.py``: no change; gate commands are generated from ``GATES``.
* ``.github/workflows/ci.yml``: ``fetch-depth: 0`` on the offline checkout; a
  ``make validate-prereg`` step; ``"prereg"`` in the ``covered`` set.
"""

from __future__ import annotations

from pathlib import Path

from rupture.preregistration.ancestry import (
    SHALLOW_REMEDY,
    GitError,
    add_commits,
    classify,
    commits_after,
    is_shallow_repository,
)
from rupture.preregistration.load import discover, file_sha256, parse_preregistration_yaml
from rupture.validation.result import GateResult, GateStatus


def run(repo_root: Path) -> GateResult:
    findings: list[str] = []
    failures: list[str] = []

    try:
        shallow = is_shallow_repository(repo_root)
    except GitError as exc:
        return GateResult(
            name="validate-prereg",
            status=GateStatus.FAILED,
            findings=[f"git failed before ancestry could run: {exc}"],
        )
    if shallow:
        return GateResult(
            name="validate-prereg",
            status=GateStatus.FAILED,
            findings=[SHALLOW_REMEDY],
        )

    registrations = discover(repo_root)
    if not registrations:
        return GateResult(
            name="validate-prereg",
            status=GateStatus.PASSED,
            findings=["no experiments registered"],
        )

    for path in registrations:
        _check_one(repo_root, path, findings=findings, failures=failures)

    status = GateStatus.FAILED if failures else GateStatus.PASSED
    return GateResult(
        name="validate-prereg",
        status=status,
        findings=[*findings, *failures],
    )


def _unique_add_commit(repo_root: Path, git_path: str) -> str:
    added = add_commits(repo_root, git_path)
    if len(added) != 1:
        listed = ", ".join(added) or "(none)"
        raise GitError(
            f"expected exactly one add-commit for {git_path}, got {len(added)}: {listed}"
        )
    return added[0]


def _check_one(repo_root: Path, path: Path, *, findings: list[str], failures: list[str]) -> None:
    rel = path.relative_to(repo_root).as_posix()
    try:
        record = parse_preregistration_yaml(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        failures.append(f"{rel}: invalid preregistration: {exc}")
        return

    if record.experiment_id != path.parent.name:
        failures.append(
            f"{rel}: experiment_id {record.experiment_id!r} does not match directory "
            f"{path.parent.name!r}"
        )
        return

    findings.append(f"{record.experiment_id}: sha256={file_sha256(path)}")
    try:
        c_p = _unique_add_commit(repo_root, rel)
        later = commits_after(repo_root, c_p, rel)
    except GitError as exc:
        failures.append(f"{rel}: {exc}")
        return

    findings.append(f"{record.experiment_id}: C_P={c_p}")
    if record.preregistration_commit is not None and record.preregistration_commit != c_p:
        failures.append(
            f"{rel}: preregistration_commit {record.preregistration_commit!r} does not "
            f"match add-commit {c_p}"
        )
    elif later:
        failures.append(
            f"{rel}: amended after C_P={c_p} by {', '.join(later)}; amendments are new "
            "files (ADR-0056 decision 4)"
        )
    elif not record.test_data_paths:
        findings.append(
            f"{record.experiment_id}: no test_data_paths; ancestry is vacuous "
            "(prospective, or the data is not in git yet)"
        )
    else:
        for data_path in record.test_data_paths:
            _check_data_path(
                repo_root,
                record.experiment_id,
                c_p,
                data_path,
                findings=findings,
                failures=failures,
            )


def _check_data_path(
    repo_root: Path,
    experiment_id: str,
    c_p: str,
    data_path: str,
    *,
    findings: list[str],
    failures: list[str],
) -> None:
    try:
        c_d = _unique_add_commit(repo_root, data_path)
    except GitError as exc:
        failures.append(f"{experiment_id}: {data_path}: {exc}")
        return
    verdict = classify(repo_root, c_p, c_d)
    label = (
        f"{experiment_id}: {data_path} C_D={c_d} {verdict.classification.value}: {verdict.detail}"
    )
    if verdict.blocks:
        failures.append(label)
        return
    findings.append(label)
