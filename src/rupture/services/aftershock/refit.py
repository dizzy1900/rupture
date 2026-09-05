"""Executing the refit schedule, and picking up what it wrote.

``REFIT_SCHEDULE`` (:mod:`rupture.services.aftershock.forecaster`) says *when* an operating
service refits -- at +1, 3, 6, 12 h then daily to +30 d -- and ``scheduled_fit_cutoff`` says which
fit a request at a given issue time should use. Neither of them runs anything. This module is the
runner, and the reader that lets a live service see its output.

**Why it is a separate process, not a thread in the service.** One EM fit of a sequence zone takes
tens of seconds and grows with the sequence; it is not something to do inside an HTTP request, and
a background thread inside a web worker would compete with requests for the GIL and be duplicated
by every worker. So the executor is a command -- ``rupture aftershock refit`` -- run by whatever
already runs periodic work (cron, systemd timer, EventBridge, a Batch job on
``infra/jobs/``). It writes ``<fits_dir>/<cutoff>/fit_result.json``, and
:class:`FitsStore` in the serving process notices the new file and serves it without a restart.

**What is refused.** A cutoff later than ``now`` is not fitted: a fit is trained on
``origin_time < cutoff``, so a future cutoff would silently be "everything I have", which is not
the fit the schedule names and, against a live feed, would be a fit on data the schedule says the
model should not yet have seen. A cutoff beyond the catalogue's coverage is refused for the same
reason and named in the outcome, rather than producing a fit that looks current and is not.

a fit is a set of rate parameters.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from rupture.domain import Catalog, FitResult, Region, utc_now
from rupture.services.aftershock.forecaster import REFIT_SCHEDULE, AftershockForecaster
from rupture.services.aftershock.sequences import Mainshock

FIT_FILE = "fit_result.json"
PROVENANCE_FILE = "provenance.json"
DEFAULT_THROUGH = timedelta(days=30)

Fitter = Callable[[Catalog, Region, datetime], FitResult]
OutcomeStatus = Literal["written", "already-fitted", "not-yet-due", "beyond-coverage", "planned"]


def cutoff_label(cutoff: datetime) -> str:
    """The directory name for a fit cutoff (``20150425T071125Z``), as ``make_fits`` writes it."""
    return f"{cutoff:%Y%m%dT%H%M%SZ}"


def scheduled_cutoffs(
    mainshock_time: datetime, *, through: timedelta = DEFAULT_THROUGH
) -> tuple[datetime, ...]:
    """Every cutoff the schedule defines out to ``through``, including the pre-mainshock one.

    The first entry is the mainshock time itself: before +1 h the service uses a fit cut at the
    mainshock, i.e. purely pre-mainshock parameters for the zone (ADR-0028 item 3). It is part of
    the schedule an operator has to have on disk, so the runner produces it too.
    """
    offsets = (timedelta(0), *(off for off in REFIT_SCHEDULE if off <= through))
    return tuple(mainshock_time + offset for offset in offsets)


@dataclass(frozen=True, slots=True)
class RefitOutcome:
    """What happened at one scheduled cutoff."""

    cutoff: datetime
    elapsed: timedelta
    status: OutcomeStatus
    path: Path | None = None
    n_events: int | None = None
    branching_ratio: float | None = None
    converged: bool | None = None
    runtime_s: float | None = None
    reason: str | None = None

    def render(self) -> str:
        head = f"{self.cutoff.isoformat()} (+{_render_elapsed(self.elapsed)}) {self.status}"
        if self.status == "written":
            return (
                f"{head}: n={self.n_events} converged={self.converged} "
                f"branching_ratio={self.branching_ratio:.3f} in {self.runtime_s:.0f}s"
                if self.branching_ratio is not None and self.runtime_s is not None
                else head
            )
        return f"{head}: {self.reason}" if self.reason else head


def _render_elapsed(elapsed: timedelta) -> str:
    hours = elapsed.total_seconds() / 3600.0
    return f"{hours:.0f}h" if hours < 24 else f"{hours / 24:.0f}d"


def plan_refits(
    mainshock_time: datetime,
    *,
    now: datetime,
    have: Collection[str],
    through: timedelta = DEFAULT_THROUGH,
    coverage_end: datetime | None = None,
    force: bool = False,
) -> list[RefitOutcome]:
    """Classify every scheduled cutoff without fitting anything.

    ``have`` is the set of ISO cutoffs already on disk (the keys of
    :func:`~rupture.services.aftershock.sequences.load_committed_fits`). Nothing here reads or
    writes; :func:`run_refits` calls it and then does the work for the ``planned`` entries.
    """
    limit = min(now, coverage_end) if coverage_end is not None else now
    out: list[RefitOutcome] = []
    for cutoff in scheduled_cutoffs(mainshock_time, through=through):
        elapsed = cutoff - mainshock_time
        if cutoff.isoformat() in have and not force:
            out.append(
                RefitOutcome(cutoff, elapsed, "already-fitted", reason="a fit is already on disk")
            )
        elif cutoff > limit:
            beyond_coverage = coverage_end is not None and cutoff > coverage_end
            out.append(
                RefitOutcome(
                    cutoff,
                    elapsed,
                    "beyond-coverage" if beyond_coverage else "not-yet-due",
                    reason=(
                        f"the catalogue is silent after {coverage_end.isoformat()}"
                        if beyond_coverage and coverage_end is not None
                        else f"the schedule reaches this cutoff after {now.isoformat()}"
                    ),
                )
            )
        else:
            out.append(RefitOutcome(cutoff, elapsed, "planned"))
    return out


def run_refits(
    *,
    catalog: Catalog,
    parent_region: Region,
    mainshock: Mainshock,
    fits_dir: Path,
    now: datetime,
    forecaster: AftershockForecaster | None = None,
    through: timedelta = DEFAULT_THROUGH,
    coverage_end: datetime | None = None,
    force: bool = False,
    dry_run: bool = False,
    fitter: Fitter | None = None,
    on_outcome: Callable[[RefitOutcome], None] | None = None,
    provenance_extra: Mapping[str, object] | None = None,
) -> list[RefitOutcome]:
    """Walk the schedule and fit every cutoff that is due, writing each fit as it completes.

    Each fit is written before the next one starts, so a runner killed half way leaves the fits it
    finished usable rather than nothing. ``fitter`` exists so a test can drive the walk without
    spending a minute in the EM.
    """
    engine = forecaster or AftershockForecaster()
    region = engine.zone(mainshock, parent_region)
    fit_one: Fitter = fitter if fitter is not None else engine.fit
    existing = {
        _read_cutoff(path): path for path in sorted(fits_dir.glob(f"*/{FIT_FILE}"))
    }  # ISO cutoff -> file
    planned = plan_refits(
        mainshock.origin_time,
        now=now,
        have=set(existing),
        through=through,
        coverage_end=coverage_end,
        force=force,
    )
    written: dict[str, object] = {}
    out: list[RefitOutcome] = []
    for entry in planned:
        if entry.status != "planned" or dry_run:
            out.append(entry)
            if on_outcome is not None:
                on_outcome(entry)
            continue
        started = time.perf_counter()
        fit = fit_one(catalog, region, entry.cutoff)
        runtime = time.perf_counter() - started
        directory = fits_dir / cutoff_label(entry.cutoff)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / FIT_FILE
        path.write_text(
            json.dumps(fit.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        done = RefitOutcome(
            cutoff=entry.cutoff,
            elapsed=entry.elapsed,
            status="written",
            path=path,
            n_events=fit.n_events,
            branching_ratio=_diagnostic_float(fit, "branching_ratio"),
            converged=fit.converged,
            runtime_s=runtime,
        )
        written[entry.cutoff.isoformat()] = _fit_record(fit, entry.elapsed, runtime)
        out.append(done)
        if on_outcome is not None:
            on_outcome(done)
    if written and not dry_run:
        _merge_provenance(
            fits_dir / PROVENANCE_FILE,
            written,
            region_id=region.id,
            extra=provenance_extra or {},
        )
    return out


def _diagnostic_float(fit: FitResult, key: str) -> float | None:
    value = fit.diagnostics.get(key)
    return float(value) if isinstance(value, int | float) else None


def _fit_record(fit: FitResult, elapsed: timedelta, runtime: float) -> dict[str, object]:
    return {
        "elapsed": _render_elapsed(elapsed),
        "n_events": fit.n_events,
        "mc": fit.mc,
        "converged": fit.converged,
        "iterations": fit.diagnostics.get("iterations"),
        "branching_ratio": fit.diagnostics.get("branching_ratio"),
        "b_value": fit.diagnostics.get("b_value"),
        "beta_fixed": fit.diagnostics.get("beta_fixed"),
        "at_bound": fit.diagnostics.get("at_bound"),
        "parameter_snapshot_hash": fit.parameter_snapshot_hash,
        "training_catalog_hash": fit.training_catalog_hash,
        "runtime_s": round(runtime, 1),
    }


def _merge_provenance(
    path: Path, records: Mapping[str, object], *, region_id: str, extra: Mapping[str, object]
) -> None:
    """Add the new fits to ``provenance.json`` without discarding what is already recorded."""
    meta: dict[str, object] = {}
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            meta = loaded
    fits = meta.get("fits")
    merged: dict[str, object] = dict(fits) if isinstance(fits, dict) else {}
    merged.update(records)
    meta["fits"] = merged
    meta["region_id"] = region_id
    meta.setdefault("created_at", utc_now().isoformat())
    meta["updated_at"] = utc_now().isoformat()
    commands = meta.get("written_by")
    history = list(commands) if isinstance(commands, list) else []
    entry = "rupture aftershock refit"
    if entry not in history:
        history.append(entry)
    meta["written_by"] = history
    for key, value in extra.items():
        meta.setdefault(key, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_cutoff(path: Path) -> str:
    return FitResult.model_validate_json(path.read_text(encoding="utf-8")).fit_cutoff.isoformat()


@dataclass(eq=False)
class FitsStore:
    """The fits on disk for one sequence, re-read when the directory changes.

    A serving process holds one of these per sequence and asks it for the fits on every request.
    The check is a ``stat`` of each ``*/fit_result.json`` -- cheap, and it means a fit written by
    ``rupture aftershock refit`` while the service is up is served by the next request rather than
    after a restart. A fit that fails to parse is skipped and named in :attr:`problems` (the
    refit runner writes the file atomically enough for this to be rare, but a half-copied file
    must not take the service down).
    """

    directory: Path
    problems: dict[str, str] = field(default_factory=dict, repr=False)
    _stamp: tuple[tuple[str, int, int], ...] | None = field(default=None, repr=False)
    _fits: dict[str, FitResult] = field(default_factory=dict, repr=False)

    def _scan(self) -> tuple[tuple[str, int, int], ...]:
        if not self.directory.is_dir():
            return ()
        out: list[tuple[str, int, int]] = []
        for path in sorted(self.directory.glob(f"*/{FIT_FILE}")):
            try:
                stat = path.stat()
            except OSError:  # pragma: no cover - the file vanished between glob and stat
                continue
            out.append((str(path), stat.st_mtime_ns, stat.st_size))
        return tuple(out)

    def fits(self) -> Mapping[str, FitResult]:
        """Every persisted fit, keyed by ISO cutoff. Reloads only when something changed."""
        stamp = self._scan()
        if stamp == self._stamp:
            return self._fits
        loaded: dict[str, FitResult] = {}
        problems: dict[str, str] = {}
        for name, _mtime, _size in stamp:
            path = Path(name)
            try:
                fit = FitResult.model_validate_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                problems[path.parent.name] = str(exc)
                continue
            loaded[fit.fit_cutoff.isoformat()] = fit
        self._fits = loaded
        self.problems = problems
        self._stamp = stamp
        return self._fits
