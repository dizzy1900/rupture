"""rupture.adapters.storage.

Also the home of :func:`make_tracker`, the selector ADR-0023 describes: the local JSONL log is the
default and the record of truth, and Weights & Biases is a mirror that has to earn its way in by
having both an API key and the optional extra installed. Nothing here imports ``wandb`` unless
both are true, so the offline path costs nothing and a fresh clone with no account is unaffected.

Call sites take a ``Tracker``; they do not choose an adapter::

    from rupture.adapters.storage import make_tracker

    tracker = make_tracker(JsonlTracker.default_path(data_dir, region_id))

``make_tracker`` never raises on the remote path and never returns nothing: every failure falls
back to the local tracker and states the reason, which is printed by default so a run says out
loud which tracker it got.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from importlib.util import find_spec
from pathlib import Path

from rupture.adapters.storage.run_log import JsonlTracker
from rupture.adapters.storage.wandb_tracker import API_KEY_ENV, WandbTracker, resolve_mode
from rupture.ports import Tracker

__all__ = [
    "JsonlTracker",
    "TrackerChoice",
    "WandbTracker",
    "make_tracker",
    "tracker_reason",
]


class TrackerChoice:
    """A selected tracker and the one-line reason it was selected. Truthy iff remote."""

    __slots__ = ("reason", "remote", "tracker")

    def __init__(self, tracker: Tracker, *, remote: bool, reason: str) -> None:
        self.tracker = tracker
        self.remote = remote
        self.reason = reason

    def __bool__(self) -> bool:
        return self.remote


def tracker_reason(path: Path, *, env: dict[str, str] | None = None) -> TrackerChoice:
    """Choose a tracker for ``path`` and say why, without printing anything.

    The order is deliberate: no key means no attempt at all (a contributor with no account never
    sees a W&B message), and a key with no extra installed is a misconfiguration worth naming.
    """
    environ = dict(os.environ) if env is None else env
    local = JsonlTracker(Path(path))
    if not environ.get(API_KEY_ENV, "").strip():
        return TrackerChoice(
            local,
            remote=False,
            reason=f"local JSONL tracker at {local.path} ({API_KEY_ENV} not set)",
        )
    if find_spec("wandb") is None:
        return TrackerChoice(
            local,
            remote=False,
            reason=(
                f"local JSONL tracker at {local.path} ({API_KEY_ENV} is set but the 'wandb' extra "
                "is not installed: uv sync --extra wandb)"
            ),
        )
    mirror = WandbTracker(local, mode=resolve_mode(environ))
    return TrackerChoice(
        mirror,
        remote=True,
        reason=(
            f"W&B mirror (mode={mirror.mode}) over the local JSONL tracker at {local.path}; "
            "the local log stays the record of truth"
        ),
    )


def make_tracker(
    path: Path,
    *,
    env: dict[str, str] | None = None,
    printer: Callable[[str], None] | None = print,
) -> Tracker:
    """The local tracker, mirrored to W&B when an API key and the extra are both present.

    ``printer`` receives the reason; pass ``None`` to stay quiet. The returned object always
    satisfies :class:`~rupture.ports.Tracker`, and its ``records()`` always reads the local file.
    """
    choice = tracker_reason(Path(path), env=env)
    if printer is not None:
        printer(f"tracker: {choice.reason}")
    return choice.tracker
