"""Git-ancestry machinery for mechanical pre-registration (ADR-0056).

This package is deliberately *not* :mod:`rupture.scoring`. Scoring import-linter-imports only
domain, so that the alarm scorer can be offered upstream; git subprocesses would pin it to
this repository. Validation calls here; scoring never should.
"""

from rupture.preregistration.ancestry import (
    SHALLOW_REMEDY,
    AncestryClass,
    AncestryVerdict,
    GitError,
    add_commits,
    classify,
    commits_after,
    earliest_add_commit,
    is_ancestor,
    is_shallow_repository,
    parse_is_shallow_output,
)
from rupture.preregistration.load import (
    discover,
    file_sha256,
    parse_preregistration_yaml,
)

__all__ = [
    "SHALLOW_REMEDY",
    "AncestryClass",
    "AncestryVerdict",
    "GitError",
    "add_commits",
    "classify",
    "commits_after",
    "discover",
    "earliest_add_commit",
    "file_sha256",
    "is_ancestor",
    "is_shallow_repository",
    "parse_is_shallow_output",
    "parse_preregistration_yaml",
]
