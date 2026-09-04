"""Weights & Biases adapter for the :class:`~rupture.ports.Tracker` port (ADR-0023).

The remote tracker is a **mirror**, never a replacement. Every :class:`WandbTracker` wraps a
:class:`~rupture.adapters.storage.run_log.JsonlTracker` and writes to it first; only then does it
try to send the same record to W&B. Two consequences follow, and both are deliberate:

* ``records()`` reads the local file. Anything a report cites is read back from a file in this
  repository, not from a vendor's API, so a reviewer with no account can check it.
* A W&B failure never loses a run and never fails a job. It is logged at WARNING and recorded on
  :attr:`WandbTracker.mirror_errors`; the local write has already happened.

``wandb`` is imported lazily, inside :meth:`WandbTracker.log`, so importing this module costs
nothing and needs no extra. Nothing in ``tests/unit`` may reach the network, so the unit tests
inject a stub module through the ``wandb_module`` argument rather than installing the real one.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

from rupture.adapters.storage.run_log import JsonlTracker
from rupture.ports import RunRecord

log = logging.getLogger(__name__)

#: Environment variable that decides whether a W&B run is online. Absent means offline, which is
#: what a contributor with no account gets.
API_KEY_ENV = "WANDB_API_KEY"
#: Overrides the mode this adapter would otherwise choose ("online", "offline", "disabled").
MODE_ENV = "RUPTURE_WANDB_MODE"
DEFAULT_PROJECT = "rupture"


def resolve_mode(env: dict[str, str] | None = None) -> str:
    """``online`` when an API key is present, ``offline`` otherwise; ``RUPTURE_WANDB_MODE`` wins."""
    environ = os.environ if env is None else env
    override = environ.get(MODE_ENV, "").strip()
    if override:
        return override
    return "online" if environ.get(API_KEY_ENV, "").strip() else "offline"


class WandbTracker:
    """Mirror run records into a W&B run while the local JSONL log stays authoritative.

    ``local`` is the record of truth. ``project`` and ``group`` are W&B's own grouping; ``group``
    defaults to the region the first record names, so one region's fits sit together.
    """

    def __init__(
        self,
        local: JsonlTracker,
        *,
        project: str = DEFAULT_PROJECT,
        group: str | None = None,
        job_type: str | None = None,
        mode: str | None = None,
        wandb_module: ModuleType | None = None,
    ) -> None:
        self.local = local
        self.project = project
        self.group = group
        self.job_type = job_type
        self.mode = mode or resolve_mode()
        self._wandb = wandb_module
        self._run: Any | None = None
        self._started = False
        #: Every mirror failure, in order. Empty is the healthy case.
        self.mirror_errors: list[str] = []

    @property
    def path(self) -> Path:
        """The local log this tracker writes through. Reports cite this, not a W&B URL."""
        return self.local.path

    # ------------------------------------------------------------------ the port
    def log(self, record: RunRecord) -> None:
        """Append locally, then mirror. The local write is the one allowed to raise."""
        self.local.log(record)
        try:
            run = self._ensure_run(record)
        except Exception as exc:  # a tracking mirror never fails the job it is mirroring
            self._note_failure("init", exc)
            return
        if run is None:
            return
        try:
            run.log(_flatten(record))
            summary = getattr(run, "summary", None)
            if summary is not None:
                summary["last_run_id"] = record.run_id
                summary["last_kind"] = record.kind
        except Exception as exc:  # see above
            self._note_failure("log", exc)

    def records(
        self, *, kind: str | None = None, region_id: str | None = None
    ) -> Iterable[RunRecord]:
        """Read back from the local log. W&B is write-only here, by design (ADR-0023)."""
        return self.local.records(kind=kind, region_id=region_id)

    # ------------------------------------------------------------------ lifecycle
    def finish(self) -> None:
        """Close the W&B run if one was opened. Safe to call when none was."""
        if self._run is None:
            return
        try:
            self._run.finish()
        except Exception as exc:  # see above
            self._note_failure("finish", exc)
        finally:
            self._run = None

    def __enter__(self) -> WandbTracker:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.finish()

    # ------------------------------------------------------------------ internals
    def _ensure_run(self, record: RunRecord) -> Any | None:
        if self._started:
            return self._run
        self._started = True
        module = self._wandb if self._wandb is not None else import_module("wandb")
        self._run = module.init(
            project=self.project,
            group=self.group or record.region_id,
            job_type=self.job_type or record.kind,
            mode=self.mode,
            config={
                "region_id": record.region_id,
                "model_id": record.model_id,
                "local_run_log": self.local.path.as_posix(),
            },
        )
        return self._run

    def _note_failure(self, stage: str, exc: Exception) -> None:
        message = f"{stage}: {type(exc).__name__}: {exc}"
        self.mirror_errors.append(message)
        log.warning(
            "W&B mirror failed (%s); the run is still recorded in %s", message, self.local.path
        )


def _flatten(record: RunRecord) -> dict[str, Any]:
    """One record as a flat dict of W&B-loggable values. Nested values become JSON strings."""
    flat: dict[str, Any] = {
        "run_id": record.run_id,
        "kind": record.kind,
        "at": record.at.isoformat(),
        "region_id": record.region_id,
        "model_id": record.model_id,
        "parameter_snapshot_hash": record.parameter_snapshot_hash,
        "notes": record.notes,
    }
    for prefix, payload in (("inputs", record.inputs), ("outputs", record.outputs)):
        for key, value in payload.items():
            flat[f"{prefix}/{key}"] = value if isinstance(value, int | float | str) else repr(value)
    return flat
