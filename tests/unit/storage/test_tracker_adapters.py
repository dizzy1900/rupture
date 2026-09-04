"""ADR-0023's two adapters and the factory that chooses between them, entirely offline.

No test here installs or imports the real ``wandb``: the mirror is exercised against a stub module
that records what it was asked to do. That is the point of the adapter's ``wandb_module`` seam.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from importlib.util import find_spec
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from rupture.adapters.storage import (
    JsonlTracker,
    WandbTracker,
    make_tracker,
    tracker_reason,
)
from rupture.adapters.storage.wandb_tracker import API_KEY_ENV, MODE_ENV, resolve_mode
from rupture.ports import RunRecord, Tracker


def record(run_id: str = "r1", *, kind: str = "fit", region: str = "turkiye-eaf") -> RunRecord:
    return RunRecord(
        run_id=run_id,
        kind=kind,
        at=datetime(2026, 9, 3, tzinfo=UTC),
        region_id=region,
        model_id="ntpp-neural-hawkes",
        parameter_snapshot_hash="deadbeef",
        inputs={"cutoff": "2022-01-01T00:00:00+00:00", "n_events": 405},
        outputs={"log_likelihood": -1234.5, "diagnostics": {"epochs_run": 554}},
        notes="offline",
    )


class StubRun:
    def __init__(self, kwargs: dict[str, Any]) -> None:
        self.init_kwargs = kwargs
        self.logged: list[dict[str, Any]] = []
        self.summary: dict[str, Any] = {}
        self.finished = False

    def log(self, payload: dict[str, Any]) -> None:
        self.logged.append(payload)

    def finish(self) -> None:
        self.finished = True


class StubWandb(ModuleType):
    """Enough of ``wandb`` for the adapter: ``init`` returning a run with ``log``/``finish``."""

    def __init__(self, *, fail_on_init: bool = False, fail_on_log: bool = False) -> None:
        super().__init__("wandb")
        self.runs: list[StubRun] = []
        self.init_calls = 0
        self._fail_on_init = fail_on_init
        self._fail_on_log = fail_on_log

    def init(self, **kwargs: Any) -> StubRun:
        self.init_calls += 1
        if self._fail_on_init:
            raise RuntimeError("no network")
        run = StubRun(kwargs)
        if self._fail_on_log:

            def boom(_payload: dict[str, Any]) -> None:
                raise RuntimeError("upload rejected")

            run.log = boom  # type: ignore[method-assign]
        self.runs.append(run)
        return run


# ------------------------------------------------------------------ the port itself
def test_both_adapters_satisfy_the_tracker_port(tmp_path: Path) -> None:
    local = JsonlTracker(tmp_path / "runs.jsonl")
    assert isinstance(local, Tracker)
    assert isinstance(WandbTracker(local, wandb_module=StubWandb()), Tracker)


# ------------------------------------------------------------------ the mirror
def test_the_mirror_writes_locally_first_and_sends_the_same_record(tmp_path: Path) -> None:
    stub = StubWandb()
    local = JsonlTracker(tmp_path / "runs.jsonl")
    tracker = WandbTracker(local, project="rupture", wandb_module=stub)

    tracker.log(record())

    stored = list(tracker.records())
    assert [r.run_id for r in stored] == ["r1"], "the local log is the record of truth"
    assert stored[0].outputs["log_likelihood"] == -1234.5
    assert stub.init_calls == 1
    sent = stub.runs[0].logged[0]
    assert sent["run_id"] == "r1"
    assert sent["region_id"] == "turkiye-eaf"
    assert sent["outputs/log_likelihood"] == -1234.5
    assert sent["outputs/diagnostics"] == repr({"epochs_run": 554}), "nested values are stringified"
    assert stub.runs[0].init_kwargs["group"] == "turkiye-eaf"
    assert stub.runs[0].init_kwargs["config"]["local_run_log"] == local.path.as_posix()


def test_one_wandb_run_per_tracker_not_per_record(tmp_path: Path) -> None:
    stub = StubWandb()
    tracker = WandbTracker(JsonlTracker(tmp_path / "runs.jsonl"), wandb_module=stub)
    tracker.log(record("r1"))
    tracker.log(record("r2", kind="issue"))
    assert stub.init_calls == 1
    assert [p["run_id"] for p in stub.runs[0].logged] == ["r1", "r2"]
    assert stub.runs[0].summary["last_kind"] == "issue"


@pytest.mark.parametrize("failure", ["init", "log"])
def test_a_wandb_failure_never_loses_the_run_and_never_raises(tmp_path: Path, failure: str) -> None:
    stub = StubWandb(fail_on_init=failure == "init", fail_on_log=failure == "log")
    tracker = WandbTracker(JsonlTracker(tmp_path / "runs.jsonl"), wandb_module=stub)

    tracker.log(record())  # must not raise

    assert [r.run_id for r in tracker.records()] == ["r1"]
    assert tracker.mirror_errors
    assert tracker.mirror_errors[0].startswith(failure)


def test_a_failed_init_is_not_retried_on_every_record(tmp_path: Path) -> None:
    stub = StubWandb(fail_on_init=True)
    tracker = WandbTracker(JsonlTracker(tmp_path / "runs.jsonl"), wandb_module=stub)
    tracker.log(record("r1"))
    tracker.log(record("r2"))
    assert stub.init_calls == 1, "one failed handshake, not one per record"
    assert [r.run_id for r in tracker.records()] == ["r1", "r2"]


def test_records_filters_the_same_way_the_local_tracker_does(tmp_path: Path) -> None:
    tracker = WandbTracker(JsonlTracker(tmp_path / "runs.jsonl"), wandb_module=StubWandb())
    tracker.log(record("r1", kind="fit"))
    tracker.log(record("r2", kind="issue", region="nepal-himalaya"))
    assert [r.run_id for r in tracker.records(kind="issue")] == ["r2"]
    assert [r.run_id for r in tracker.records(region_id="turkiye-eaf")] == ["r1"]


def test_finish_closes_the_run_and_is_safe_when_none_was_opened(tmp_path: Path) -> None:
    stub = StubWandb()
    with WandbTracker(JsonlTracker(tmp_path / "a.jsonl"), wandb_module=stub) as tracker:
        tracker.log(record())
    assert stub.runs[0].finished
    WandbTracker(JsonlTracker(tmp_path / "b.jsonl"), wandb_module=stub).finish()


# ------------------------------------------------------------------ the mode
@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "offline"),
        ({API_KEY_ENV: ""}, "offline"),
        ({API_KEY_ENV: "k"}, "online"),
        ({API_KEY_ENV: "k", MODE_ENV: "offline"}, "offline"),
        ({MODE_ENV: "disabled"}, "disabled"),
    ],
)
def test_mode_is_offline_unless_an_api_key_says_otherwise(
    env: dict[str, str], expected: str
) -> None:
    assert resolve_mode(env) == expected


# ------------------------------------------------------------------ the factory
def test_the_factory_falls_back_to_local_with_a_printed_reason(tmp_path: Path) -> None:
    printed: list[str] = []
    tracker = make_tracker(tmp_path / "runs.jsonl", env={}, printer=printed.append)
    assert isinstance(tracker, JsonlTracker)
    assert len(printed) == 1
    assert API_KEY_ENV in printed[0]
    assert "not set" in printed[0]


def test_a_key_without_the_extra_is_named_not_silently_ignored(tmp_path: Path) -> None:
    if "wandb" in sys.modules or _wandb_installed():
        pytest.skip("the wandb extra is installed here; this covers the fresh-clone case")
    choice = tracker_reason(tmp_path / "runs.jsonl", env={API_KEY_ENV: "k"})
    assert not choice.remote
    assert isinstance(choice.tracker, JsonlTracker)
    assert "extra is not installed" in choice.reason


def test_the_factory_is_quiet_when_asked_to_be(tmp_path: Path) -> None:
    assert isinstance(make_tracker(tmp_path / "runs.jsonl", env={}, printer=None), JsonlTracker)


def test_no_wandb_import_happens_on_the_default_path(tmp_path: Path) -> None:
    """The offline default must not pull the vendor SDK in, installed or not."""
    before = "wandb" in sys.modules
    make_tracker(tmp_path / "runs.jsonl", env={}, printer=None)
    assert ("wandb" in sys.modules) == before


def _wandb_installed() -> bool:
    return find_spec("wandb") is not None
