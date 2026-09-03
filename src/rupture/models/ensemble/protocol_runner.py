"""Run the protocol schedule for the gridded challenger and the log-linear ensemble.

This is the experiment driver behind ``docs/CHALLENGER_GRIDDED.md`` and
``docs/CHALLENGER_ENSEMBLE.md``. It does, in order and per region:

1. **Hyperparameter search** — a small grid of gridded configurations, each fitted with a cutoff of
   ``search_cutoff`` and ranked by its own inner validation block (which ends at that cutoff). The
   winner is frozen and its config hash recorded before anything later runs.
2. **Weight-fitting block** — the frozen configuration is fitted at ``weights_cutoff``; the ETAS
   baseline is fitted at the same cutoff; both issue forecasts on every 30-day window between
   ``weights_cutoff`` and ``test_cutoff``, and the ensemble weights are fitted on those windows and
   on nothing else.
3. **Test fit** — the frozen configuration is fitted at ``test_cutoff`` and persisted to
   ``baselines/gridded/<region>/``.
4. **Test schedule** — the protocol schedule (30-day windows from ``test_cutoff``), scoring the
   gridded model and the ensemble with the existing ``PyCSEPEvaluator`` and comparing each against
   the ETAS baseline's own stored forecasts with the paired T-test and the W-test.
5. **Leaky ablation** (ADR-0022 § 6) — one deliberately leaky gridded fit whose training windows
   run through the end of the test period, compared against the honest one. It is a measurement of
   what the discipline is worth and is never reported as a result.

Every stage caches to disk so a run can be resumed. Nothing here re-fits ETAS for the test period:
the declared baseline's forecasts are read from the store the published schedule wrote, so the
challenger is compared against exactly the forecasts the baseline was scored on.

rupture does not predict earthquakes.
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from rupture.adapters.evaluation.pycsep import PyCSEPEvaluator
from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.adapters.forecasting.etas_mizrahi import save_fit as save_etas_fit
from rupture.adapters.storage.run_log import JsonlTracker
from rupture.adapters.storage.zarr_store import ZarrGridStore
from rupture.domain import Catalog, EvaluationResult, ForecastGrid, Region, TestName, utc_now
from rupture.models.challengers.gridded import (
    GriddedChallenger,
    GriddedConfig,
)
from rupture.models.challengers.gridded import (
    archive_dir as gridded_archive_dir,
)
from rupture.models.challengers.gridded import (
    load_fit as load_gridded_fit,
)
from rupture.models.challengers.gridded import (
    save_fit as save_gridded_fit,
)
from rupture.models.ensemble.loglinear import (
    LogLinearEnsemble,
    observed_counts,
    poisson_log_likelihood,
)
from rupture.pipelines.evaluate import target_slice
from rupture.pipelines.io import load_catalog, load_region
from rupture.ports import RunRecord

log = logging.getLogger("rupture.models.protocol_runner")

CONSISTENCY: tuple[TestName, ...] = (TestName.N, TestName.M, TestName.S, TestName.L, TestName.CL)
ONE_SIDED: tuple[TestName, ...] = (TestName.M, TestName.S, TestName.L, TestName.CL)

SEARCH_CUTOFF = datetime(2020, 1, 1, tzinfo=UTC)
WEIGHTS_CUTOFF = datetime(2020, 1, 1, tzinfo=UTC)
TEST_CUTOFF = datetime(2022, 1, 1, tzinfo=UTC)
SCHEDULE_END = datetime(2026, 8, 1, tzinfo=UTC)
HORIZON = timedelta(days=30)
SEED = 20220101
N_SIMULATIONS = 1000

#: The search grid. Small on purpose: the training signal is a few hundred events. It varies the
#: three things that could plausibly matter here — how far back the model looks, at what temporal
#: resolution, and how hard it is pushed away from its climatological initialisation.
SEARCH_GRID: tuple[dict[str, Any], ...] = (
    {"n_frames": 6, "frame_days": 30.0, "hidden_channels": 8},
    {"n_frames": 8, "frame_days": 7.5, "hidden_channels": 8},
    {"n_frames": 6, "frame_days": 30.0, "hidden_channels": 16, "learning_rate": 3e-4},
    {"n_frames": 8, "frame_days": 7.5, "hidden_channels": 8, "learning_rate": 3e-4},
)


@dataclass(frozen=True)
class Paths:
    repo: Path

    @property
    def catalogs(self) -> Path:
        return self.repo / "data" / "catalogs"

    @property
    def regions(self) -> Path:
        return self.repo / "data" / "regions"

    @property
    def baselines(self) -> Path:
        return self.repo / "baselines"

    @property
    def etas_store(self) -> Path:
        return self.repo / "data" / "forecasts"

    def out(self, region_id: str) -> Path:
        return self.repo / "reports" / "challenger" / region_id


def issue_times(
    start: datetime, end: datetime, step: timedelta, horizon: timedelta
) -> list[datetime]:
    out: list[datetime] = []
    t = start
    while t + horizon <= end:
        out.append(t)
        t += step
    return out


# ---------------------------------------------------------------------- providers
def stored_etas_provider(store: ZarrGridStore, region_id: str) -> Any:
    """Component reading the declared baseline's own stored forecasts (no refitting)."""
    cache: dict[str, ForecastGrid] = {}

    def provider(_history: Catalog, issue_time: datetime, horizon: timedelta) -> ForecastGrid:
        fid = ForecastGrid.make_id("etas-mizrahi", region_id, issue_time, horizon)
        if fid not in cache:
            cache[fid] = store.load(fid)
        return cache[fid]

    return provider


def live_etas_provider(
    model: MizrahiETAS,
    region_id: str,
    mc: float,
    *,
    n_simulations: int,
    seed: int,
    cache: Path,
) -> Any:
    """Component that issues ETAS forecasts itself, caching each grid under ``cache``."""
    store = ZarrGridStore(cache)

    def provider(history: Catalog, issue_time: datetime, horizon: timedelta) -> ForecastGrid:
        fid = ForecastGrid.make_id(model.model_id, region_id, issue_time, horizon)
        try:
            return store.load(fid)
        except FileNotFoundError:
            pass
        except (OSError, KeyError, ValueError) as exc:
            # a run killed mid-write leaves a partial store; reissue rather than trust it
            log.warning("discarding unreadable cached forecast %s (%s)", fid, exc)
            shutil.rmtree(cache / region_id / model.model_id / f"{fid}.zarr", ignore_errors=True)
        usable = history.earthquakes().at_least(mc)
        grid = model.forecast(usable, issue_time, horizon, n_simulations=n_simulations, seed=seed)
        store.save(grid)
        return grid

    return provider


def gridded_provider(model: GriddedChallenger) -> Any:
    def provider(history: Catalog, issue_time: datetime, horizon: timedelta) -> ForecastGrid:
        return model.forecast(history, issue_time, horizon)

    return provider


# ---------------------------------------------------------------------- stages
def fit_gridded_cached(
    catalog: Catalog,
    region: Region,
    cutoff: datetime,
    config: GriddedConfig,
    baselines: Path,
    *,
    canonical: bool,
) -> GriddedChallenger:
    """Fit, or reload an archived fit whose config hash matches."""
    archive = gridded_archive_dir(baselines, region.id, cutoff)
    if (archive / "fit_result.json").exists():
        model = load_gridded_fit(baselines, region.id, cutoff=cutoff)
        stored = model.fit_result
        if stored is not None and stored.diagnostics.get("config_hash") == config.hash():
            log.info("reusing archived gridded fit at %s", cutoff.isoformat())
            return model
    model = GriddedChallenger(config)
    started = time.time()
    model.fit(catalog, region, cutoff)
    log.info("gridded fit at %s took %.1f s", cutoff.isoformat(), time.time() - started)
    save_gridded_fit(model, baselines, canonical=canonical)
    return model


def search_hyperparameters(
    catalog: Catalog, region: Region, out: Path
) -> tuple[GriddedConfig, list[dict[str, Any]]]:
    """Rank the search grid on each candidate's own inner validation block. Frozen afterwards.

    Candidate fits are written under ``out/search-fits`` and never into ``baselines/``: they are
    search residue, not a declared baseline, and they all share one cutoff so they would otherwise
    overwrite one another's archive.
    """
    cache = out / "hyperparameter_search.json"
    search_cache = out / "search-fits"
    table: list[dict[str, Any]] = []
    if cache.exists():
        table = json.loads(cache.read_text(encoding="utf-8"))["candidates"]
    else:
        for changes in SEARCH_GRID:
            cfg = replace(GriddedConfig(), **changes)
            model = fit_gridded_cached(
                catalog, region, SEARCH_CUTOFF, cfg, search_cache, canonical=False
            )
            fit = model.fit_result
            assert fit is not None
            table.append(
                {
                    "config": cfg.as_dict(),
                    "config_hash": cfg.hash(),
                    "validation_nll": float(fit.diagnostics["training"]["best_validation_nll"]),
                    "untrained_validation_nll": float(
                        fit.diagnostics["training"]["untrained_validation_nll"]
                    ),
                    "selected_the_untrained_climatology": bool(
                        fit.diagnostics["training"]["selected_the_untrained_climatology"]
                    ),
                    "best_epoch": int(fit.diagnostics["training"]["best_epoch"]),
                    "epochs_run": int(fit.diagnostics["training"]["epochs_run"]),
                    "n_weights": int(fit.diagnostics["n_weights"]),
                    "train_windows": int(fit.diagnostics["train_windows"]),
                    "validation_windows": int(fit.diagnostics["validation_windows"]),
                }
            )
        out.mkdir(parents=True, exist_ok=True)
        cache.write_text(
            json.dumps(
                {
                    "search_cutoff": SEARCH_CUTOFF.isoformat(),
                    "criterion": (
                        "lowest Poisson negative log-likelihood on the candidate's own inner "
                        "validation block, which ends at the search cutoff"
                    ),
                    "candidates": table,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    # Ties are real here: every candidate's untrained state is the same climatological prior, so
    # if none of them improves on it they all score identically. Break toward the smaller model,
    # then toward the shorter lookback, then by position in the grid — all deterministic.
    ranked = sorted(
        enumerate(table),
        key=lambda item: (
            round(item[1]["validation_nll"], 9),
            item[1]["n_weights"],
            item[1]["config"]["n_frames"],
            item[0],
        ),
    )
    best = ranked[0][1]
    return GriddedConfig(**best["config"]), table


def fit_etas_at(catalog: Catalog, region: Region, cutoff: datetime, baselines: Path) -> MizrahiETAS:
    from rupture.adapters.forecasting.etas_mizrahi import (  # noqa: PLC0415
        archive_dir as etas_archive_dir,
    )
    from rupture.domain import FitResult  # noqa: PLC0415

    model = MizrahiETAS()
    archived = etas_archive_dir(baselines, region.id, cutoff) / "fit_result.json"
    if archived.exists():
        model.load_fit(FitResult.model_validate_json(archived.read_text(encoding="utf-8")), region)
        return model
    started = time.time()
    fit = model.fit(catalog, region, cutoff)
    log.info("ETAS fit at %s took %.1f s", cutoff.isoformat(), time.time() - started)
    save_etas_fit(fit, baselines, canonical=False)
    return model


def score_window(
    evaluator: PyCSEPEvaluator,
    grid: ForecastGrid,
    benchmark: ForecastGrid | None,
    catalog: Catalog,
    region: Region,
) -> dict[str, Any]:
    target = target_slice(catalog, grid, region)
    results = evaluator.evaluate(
        grid, target, CONSISTENCY, n_simulations=N_SIMULATIONS, alpha=0.05, seed=SEED
    )
    row: dict[str, Any] = {
        "issue_time": grid.issue_time.isoformat(),
        "window_end": grid.window_end.isoformat(),
        "forecast_id": grid.id,
        "fit_cutoff": grid.fit_cutoff.isoformat(),
        "parameter_snapshot_hash": grid.parameter_snapshot_hash,
        "total_expected": grid.total_expected(),
        "target_catalog_hash": target.event_hash(),
        "tests": {r.test_name.value: _summary(r) for r in results},
    }
    n_obs = next((r.n_target_events for r in results), 0)
    row["n_target_events"] = int(n_obs)
    row["n_only"] = bool(n_obs == 0)
    if benchmark is not None:
        comparison = evaluator.compare(grid, benchmark, target)
        row["comparison"] = {r.test_name.value: _summary(r) for r in comparison}
        row["benchmark_model_id"] = benchmark.model_id
        row["pooling"] = _pooling_terms(evaluator, grid, benchmark, target)
    return row


def _pooling_terms(
    evaluator: PyCSEPEvaluator,
    grid: ForecastGrid,
    benchmark: ForecastGrid,
    target: Catalog,
) -> dict[str, Any]:
    """The per-window quantities the schedule-wide paired T-test needs (Rhoades et al. 2011).

    ``log_rates`` are the forecast rates in the cell-magnitude bin of each observed target event,
    logged; ``n_forecast`` is the window's total expected count. Pooling these across windows is
    what turns pycsep's per-window paired test into the "over those windows" test the promotion
    rule asks for.
    """
    g1 = evaluator.to_gridded_forecast(grid)
    g2 = evaluator.to_gridded_forecast(benchmark)
    csep_catalog, _ = evaluator.to_csep_catalog(target, g1, grid)
    rates1, n1 = g1.target_event_rates(csep_catalog, scale=False)
    rates2, n2 = g2.target_event_rates(csep_catalog, scale=False)
    with np.errstate(divide="ignore"):
        log1 = np.log(np.asarray(rates1, dtype=np.float64))
        log2 = np.log(np.asarray(rates2, dtype=np.float64))
    return {
        "log_rates": [float(v) for v in log1],
        "benchmark_log_rates": [float(v) for v in log2],
        "n_forecast": float(n1),
        "benchmark_n_forecast": float(n2),
    }


def _summary(r: EvaluationResult) -> dict[str, Any]:
    return {
        "statistic": r.statistic,
        "quantile": r.quantile,
        "quantile_low": r.quantile_low,
        "quantile_high": r.quantile_high,
        "p_value": r.p_value,
        "passed": r.passed,
        "n_target_events": r.n_target_events,
    }


def pass_rates(windows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for test in CONSISTENCY:
        rows = [w["tests"].get(test.value) for w in windows]
        decided = [r for r in rows if r is not None and r["passed"] is not None]
        passed = sum(1 for r in decided if r["passed"])
        out[test.value] = {
            "passed": passed,
            "scored": len(decided),
            "rate": (passed / len(decided)) if decided else None,
            "denominator_rule": (
                "all evaluated windows" if test == TestName.N else "windows with >= 1 target event"
            ),
        }
    return out


def comparison_summary(windows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the per-window paired comparisons against the baseline."""
    t_rows = [
        w["comparison"]["T"]
        for w in windows
        if "comparison" in w and w["comparison"]["T"]["passed"] is not None
    ]
    w_rows = [
        w["comparison"]["W"]
        for w in windows
        if "comparison" in w and w["comparison"]["W"]["passed"] is not None
    ]
    gains = [r["statistic"] for r in t_rows]
    return {
        "windows_compared": len(t_rows),
        "t_test_wins": sum(1 for r in t_rows if r["passed"]),
        "t_test_losses": sum(1 for r in t_rows if not r["passed"]),
        "mean_information_gain_per_event": float(np.mean(gains)) if gains else None,
        "median_information_gain_per_event": float(np.median(gains)) if gains else None,
        "n_windows_positive_gain": sum(1 for g in gains if g > 0.0),
        "w_test_wins": sum(1 for r in w_rows if r["passed"]),
        "windows_w_compared": len(w_rows),
        "note": (
            "A T-test 'win' is a window whose lower confidence bound on the information gain per "
            "event against the baseline is above zero. Pass rates and wins are reported with "
            "their denominators; a pass is not a skill claim."
        ),
    }


def pooled_sensitivity(windows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """How much of the pooled result rests on one window.

    A schedule dominated by a single sequence gives the pooled paired test the appearance of a
    large sample when it is really one event and its aftershocks. This reports each window's
    contribution to the total information gain and re-runs the pooled test with the largest
    contributor removed. The Student-t interval assumes independent target events, which
    aftershocks are not; this is the cheapest available check on how much that matters.
    """
    contributions: list[dict[str, Any]] = []
    for w in windows:
        pooling = w.get("pooling")
        if not pooling:
            continue
        diff = np.asarray(pooling["log_rates"], dtype=np.float64) - np.asarray(
            pooling["benchmark_log_rates"], dtype=np.float64
        )
        contributions.append(
            {
                "issue_time": w["issue_time"],
                "n_target_events": int(w["n_target_events"]),
                "sum_log_rate_difference": float(diff.sum()),
                "forecast_difference": float(
                    pooling["n_forecast"] - pooling["benchmark_n_forecast"]
                ),
                "contribution_to_total_gain": float(
                    diff.sum() - (pooling["n_forecast"] - pooling["benchmark_n_forecast"])
                ),
            }
        )
    if not contributions:
        return {"decided": False, "reason": "no compared windows"}
    ranked = sorted(contributions, key=lambda c: -abs(c["contribution_to_total_gain"]))
    largest = ranked[0]
    total = sum(c["contribution_to_total_gain"] for c in contributions)
    without = pooled_paired_test(windows, exclude=frozenset({largest["issue_time"]}))
    return {
        "total_gain": total,
        "largest_contributor": largest,
        "largest_contributor_share": (
            largest["contribution_to_total_gain"] / total if total else None
        ),
        "top_windows": ranked[:5],
        "pooled_test_without_largest_contributor": without,
        "caveat": (
            "Target events inside one aftershock sequence are not independent, so the pooled "
            "Student-t interval is narrower than the evidence warrants. Read the interval as a "
            "lower bound on the uncertainty, not an upper one."
        ),
    }


def uniform_spatial_grid(grid: ForecastGrid) -> ForecastGrid:
    """The same grid with its spatial field flattened: same total, same magnitude distribution."""
    counts = grid.counts()
    per_bin = counts.sum(axis=0)
    n_cells = counts.shape[0]
    flat = np.tile(per_bin / n_cells, (n_cells, 1))
    return grid.model_copy(
        update={
            "id": grid.id + "-uniform",
            "model_id": grid.model_id + "-uniform",
            "expected_counts": tuple(tuple(float(v) for v in row) for row in flat),
            "notes": "ABLATION: spatial field flattened to uniform, total and magnitudes kept",
        }
    )


def uniform_component_ablation(
    catalog: Catalog,
    region: Region,
    *,
    validation_times: Sequence[datetime],
    schedule: Sequence[datetime],
    etas_validation: Any,
    etas_component: Any,
    gridded_val: GriddedChallenger,
    gridded_test: GriddedChallenger,
    evaluator: PyCSEPEvaluator,
) -> dict[str, Any]:
    """Would any diffuse second component do, or does the learned spatial field matter?

    The ensemble's gain could be nothing more than *tempering* the baseline — raising its rate
    field to a power below one and renormalising, which flattens its dynamic range. Pooling with a
    spatially uniform field of the same total does exactly that and nothing else. This refits the
    weights on the same validation block with the uniform field in place of the challenger, scores
    the same schedule, and reports the pooled paired test, so the two can be read side by side.
    Consistency tests are not re-run: the question here is the information gain, not a pass rate.
    """
    uniform_val = LogLinearEnsemble(
        {
            "etas": etas_validation,
            "gridded": lambda h, t, hz: uniform_spatial_grid(gridded_val.forecast(h, t, hz)),
        },
        validation_issue_times=list(validation_times),
        horizon=HORIZON,
    )
    fit = uniform_val.fit(catalog, region, TEST_CUTOFF)
    weights = uniform_val.weights
    assert weights is not None
    uniform_test = LogLinearEnsemble(
        {
            "etas": etas_component,
            "gridded": lambda h, t, hz: uniform_spatial_grid(gridded_test.forecast(h, t, hz)),
        },
        validation_issue_times=list(validation_times),
        horizon=HORIZON,
    )
    uniform_test.load_weights(weights, fit)
    rows: list[dict[str, Any]] = []
    for t in schedule:
        history = catalog.before(t)
        grid = uniform_test.forecast(history, t, HORIZON)
        benchmark = etas_component(history, t, HORIZON)
        target = target_slice(catalog, grid, region)
        rows.append(
            {
                "issue_time": t.isoformat(),
                "n_target_events": int(observed_counts(target, grid).sum()),
                "total_expected": grid.total_expected(),
                "pooling": _pooling_terms(evaluator, grid, benchmark, target),
            }
        )
    return {
        "what": (
            "the ensemble refitted and rescored with the challenger's spatial field flattened to "
            "uniform; the total and the magnitude distribution are unchanged, so the only thing "
            "removed is where the challenger put the rate"
        ),
        "weights": fit.parameters,
        "pooled_paired_test": pooled_paired_test(rows),
        "reading": (
            "If this ablation matches the ensemble's own information gain, the gain is tempering "
            "of the baseline rather than anything the challenger learned about place."
        ),
    }


def promotion_decision(
    challenger: dict[str, Any],
    etas: dict[str, Any],
    pooled: dict[str, Any],
    n_windows: int,
) -> dict[str, Any]:
    """Protocol section 10, evaluated for one region. Two of three regions is decided elsewhere.

    Condition 1: the challenger passes N, M, S and L at a rate at least the baseline's, over at
    least twelve consecutive 30-day windows. Condition 2: it beats the baseline in the paired
    T-test at alpha with positive information gain per event over those windows.
    """
    if not etas.get("available"):
        return {
            "condition_1_pass_rates": None,
            "condition_2_paired_t_test": None,
            "promotable_in_this_region": False,
            "reason": "no published ETAS schedule to compare against",
        }
    per_test = {}
    for test in ("N", "M", "S", "L"):
        mine = challenger[test]["rate"]
        theirs = etas["pass_rates"][test]["rate"]
        per_test[test] = {
            "challenger": mine,
            "etas": theirs,
            "at_least_etas": bool(mine is not None and theirs is not None and mine >= theirs),
        }
    condition_1 = n_windows >= 12 and all(v["at_least_etas"] for v in per_test.values())
    condition_2 = bool(
        pooled.get("decided")
        and pooled.get("t_test_beats_benchmark")
        and (pooled.get("information_gain_per_event") or 0.0) > 0.0
    )
    return {
        "windows": n_windows,
        "condition_1_pass_rates": {"met": bool(condition_1), "per_test": per_test},
        "condition_2_paired_t_test": {
            "met": condition_2,
            "information_gain_per_event": pooled.get("information_gain_per_event"),
            "ig_lower": pooled.get("ig_lower"),
            "p_value": pooled.get("p_value"),
            "w_test_p_value": pooled.get("w_test_p_value"),
            "w_test_agrees": pooled.get("w_test_beats_benchmark"),
            "reason": pooled.get("reason"),
        },
        "promotable_in_this_region": bool(condition_1 and condition_2),
        "note": (
            "Promotion also requires both conditions in at least two of the three test regions; "
            "that is decided across regions, not here. A pass rate is not a skill claim."
        ),
    }


def pooled_paired_test(
    windows: Sequence[dict[str, Any]], *, alpha: float = 0.05, exclude: frozenset[str] = frozenset()
) -> dict[str, Any]:
    """The paired T-test and W-test over the whole schedule, not one window at a time.

    The promotion rule (protocol section 10, condition 2) asks whether the challenger beats ETAS
    in the paired T-test *over* at least twelve consecutive windows. pycsep's ``paired_t_test``
    scores one window, and on a 30-day window with one or two target events it has almost no
    power. This pools every window's target events into a single test, using the same statistic
    (Rhoades et al. 2011, equations 17 and 18) that pycsep implements per window: the information
    gain is ``(sum(log lambda_A - log lambda_B) - (N_A - N_B)) / N`` over all events and all
    windows, with N_A and N_B the summed forecast counts, and the Student-t interval is taken on
    the per-event differences.
    """
    log_a: list[float] = []
    log_b: list[float] = []
    n_a = 0.0
    n_b = 0.0
    used = 0
    for w in windows:
        pooling = w.get("pooling")
        if not pooling or w["issue_time"] in exclude:
            continue
        used += 1
        n_a += float(pooling["n_forecast"])
        n_b += float(pooling["benchmark_n_forecast"])
        log_a.extend(float(v) for v in pooling["log_rates"])
        log_b.extend(float(v) for v in pooling["benchmark_log_rates"])
    n_obs = len(log_a)
    base = {
        "windows_pooled": used,
        "windows_excluded": sorted(exclude),
        "target_events": n_obs,
        "total_forecast": n_a,
        "benchmark_total_forecast": n_b,
        "alpha": alpha,
        "statistic": "Rhoades et al. 2011 information gain per event, pooled over the schedule",
    }
    if n_obs < 2:
        return {**base, "decided": False, "reason": "fewer than two target events in the schedule"}
    diff = np.asarray(log_a, dtype=np.float64) - np.asarray(log_b, dtype=np.float64)
    if not np.all(np.isfinite(diff)):
        n_infinite = int(np.sum(~np.isfinite(diff)))
        return {
            **base,
            "decided": False,
            "reason": (
                f"{n_infinite} target event(s) fell in a bin one forecast gave zero rate, so the "
                f"log-rate difference is not finite; the pooled test is undefined"
            ),
        }
    information_gain = float((diff.sum() - (n_a - n_b)) / n_obs)
    first = float((diff**2).sum() / (n_obs - 1))
    second = float(diff.sum() ** 2 / (n_obs**2 - n_obs))
    variance = first - second
    if variance <= 0.0:
        return {**base, "decided": False, "reason": "zero variance in the per-event differences"}
    std = float(np.sqrt(variance))
    t_statistic = information_gain / (std / float(np.sqrt(n_obs)))
    t_critical = float(stats.t.ppf(1.0 - alpha / 2.0, n_obs - 1))
    half = t_critical * std / float(np.sqrt(n_obs))
    p_value = float(2.0 * stats.t.sf(abs(t_statistic), df=n_obs - 1))
    median_value = (n_a - n_b) / n_obs
    try:
        w_p: float | None = float(
            stats.wilcoxon(
                diff - median_value, alternative="two-sided", zero_method="wilcox"
            ).pvalue
        )
    except ValueError:  # every difference equals the median: the signed-rank test is undefined
        w_p = None
    return {
        **base,
        "decided": True,
        "information_gain_per_event": information_gain,
        "ig_lower": information_gain - half,
        "ig_upper": information_gain + half,
        "t_statistic": t_statistic,
        "t_critical": t_critical,
        "p_value": p_value,
        "t_test_beats_benchmark": bool(information_gain - half > 0.0),
        "w_test_p_value": w_p,
        "w_test_beats_benchmark": (
            bool(w_p < alpha and information_gain > 0.0) if w_p is not None else None
        ),
    }


def pooled_information_gain(
    windows: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """Sum of per-window information gains weighted by target count: one number for the schedule."""
    total_events = 0
    total_gain = 0.0
    for w in windows:
        comp = w.get("comparison")
        if not comp or comp["T"]["passed"] is None:
            continue
        n = int(comp["T"]["n_target_events"])
        total_events += n
        total_gain += float(comp["T"]["statistic"]) * n
    return {
        "target_events": total_events,
        "total_information_gain": total_gain,
        "information_gain_per_event": (total_gain / total_events) if total_events else None,
    }


class _WindowCache:
    """Append-only per-window score cache so an interrupted schedule resumes where it stopped.

    A row is reused only when it was produced by the same parameter snapshot, so changing the fit
    invalidates the cache rather than silently mixing two models' windows.
    """

    def __init__(self, path: Path, snapshot_hash: str) -> None:
        self.path = path
        self.snapshot_hash = snapshot_hash
        self.rows: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get("parameter_snapshot_hash") == snapshot_hash:
                    self.rows[row["issue_time"]] = row

    def get(self, issue_time: datetime, compute: Any) -> dict[str, Any]:
        key = issue_time.isoformat()
        if key in self.rows:
            return self.rows[key]
        row: dict[str, Any] = compute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        self.rows[key] = row
        return row


# ---------------------------------------------------------------------- the run
def run_region(region_id: str, paths: Paths, *, skip_ablation: bool = False) -> dict[str, Any]:
    out = paths.out(region_id)
    out.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(paths.catalogs / region_id)
    region = load_region(paths.regions / region_id)
    tracker = JsonlTracker(out / "runs.jsonl")
    evaluator = PyCSEPEvaluator()
    started = utc_now()

    log.info("[%s] hyperparameter search", region_id)
    config, search_table = search_hyperparameters(catalog, region, out)
    log.info("[%s] frozen config %s (%s)", region_id, config.as_dict(), config.hash()[:12])
    tracker.log(
        RunRecord(
            run_id=f"gridded-config-{region_id}",
            kind="hyperparameters",
            at=utc_now(),
            region_id=region_id,
            model_id=GriddedChallenger.model_id,
            inputs={"search_cutoff": SEARCH_CUTOFF.isoformat(), "grid": list(SEARCH_GRID)},
            outputs={"config": config.as_dict(), "config_hash": config.hash()},
        )
    )

    log.info("[%s] weight-fitting block", region_id)
    gridded_val = fit_gridded_cached(
        catalog, region, WEIGHTS_CUTOFF, config, paths.baselines, canonical=False
    )
    etas_val = fit_etas_at(catalog, region, WEIGHTS_CUTOFF, paths.baselines)
    etas_mc = (
        etas_val.fit_result.mc if etas_val.fit_result is not None else region.target_min_magnitude
    )
    val_times = issue_times(WEIGHTS_CUTOFF, TEST_CUTOFF, HORIZON, HORIZON)
    ensemble = LogLinearEnsemble(
        {
            "etas": live_etas_provider(
                etas_val,
                region_id,
                etas_mc,
                n_simulations=N_SIMULATIONS,
                seed=SEED,
                cache=out / "validation-forecasts",
            ),
            "gridded": gridded_provider(gridded_val),
        },
        validation_issue_times=val_times,
        horizon=HORIZON,
    )
    weight_fit = ensemble.fit(catalog, region, TEST_CUTOFF)
    log.info("[%s] weights %s", region_id, weight_fit.parameters)
    tracker.log(
        RunRecord(
            run_id=f"ensemble-weights-{region_id}",
            kind="fit",
            at=utc_now(),
            region_id=region_id,
            model_id=LogLinearEnsemble.model_id,
            parameter_snapshot_hash=weight_fit.parameter_snapshot_hash,
            inputs={"validation_windows": [t.isoformat() for t in val_times]},
            outputs={"parameters": weight_fit.parameters},
        )
    )

    log.info("[%s] test fit", region_id)
    gridded_test = fit_gridded_cached(
        catalog, region, TEST_CUTOFF, config, paths.baselines, canonical=True
    )
    test_fit = gridded_test.fit_result
    assert test_fit is not None

    etas_store = ZarrGridStore(paths.etas_store)
    etas_component = stored_etas_provider(etas_store, region_id)
    test_ensemble = LogLinearEnsemble(
        {"etas": etas_component, "gridded": gridded_provider(gridded_test)},
        validation_issue_times=val_times,
        horizon=HORIZON,
    )
    fitted_weights = ensemble.weights
    assert fitted_weights is not None
    test_ensemble.load_weights(fitted_weights, weight_fit)

    schedule = issue_times(TEST_CUTOFF, SCHEDULE_END, HORIZON, HORIZON)
    log.info("[%s] scoring %d windows", region_id, len(schedule))
    gridded_cache = _WindowCache(out / "windows-gridded.jsonl", test_fit.parameter_snapshot_hash)
    ensemble_cache = _WindowCache(
        out / "windows-ensemble.jsonl", weight_fit.parameter_snapshot_hash
    )
    gridded_windows: list[dict[str, Any]] = []
    ensemble_windows: list[dict[str, Any]] = []
    for i, t in enumerate(schedule):
        history = catalog.before(t)
        etas_grid = etas_component(history, t, HORIZON)
        gridded_windows.append(
            gridded_cache.get(
                t,
                lambda t=t, h=history, e=etas_grid: score_window(
                    evaluator, gridded_test.forecast(h, t, HORIZON), e, catalog, region
                ),
            )
        )
        ensemble_windows.append(
            ensemble_cache.get(
                t,
                lambda t=t, h=history, e=etas_grid: score_window(
                    evaluator, test_ensemble.forecast(h, t, HORIZON), e, catalog, region
                ),
            )
        )
        log.info("[%s] window %d/%d %s", region_id, i + 1, len(schedule), t.date())

    etas_published = _etas_published(paths.repo, region_id)
    report = {
        "region_id": region_id,
        "generated_at": started.isoformat(),
        "catalog_id": catalog.id,
        "catalog_event_hash": catalog.event_hash(),
        "protocol": {
            "search_cutoff": SEARCH_CUTOFF.isoformat(),
            "weights_cutoff": WEIGHTS_CUTOFF.isoformat(),
            "test_cutoff": TEST_CUTOFF.isoformat(),
            "schedule_end": SCHEDULE_END.isoformat(),
            "horizon": "30d",
            "step": "30d",
            "seed": SEED,
            "n_simulations": N_SIMULATIONS,
            "alpha": 0.05,
            "refit_policy": "none (the gridded model is fitted once, at the test cutoff)",
        },
        "hyperparameters": {
            "frozen_config": config.as_dict(),
            "config_hash": config.hash(),
            "search": search_table,
        },
        "gridded_fit": {
            "parameter_snapshot_hash": test_fit.parameter_snapshot_hash,
            "weights_sha256": test_fit.diagnostics["weights_sha256"],
            "n_weights": test_fit.diagnostics["n_weights"],
            "n_cells": test_fit.diagnostics["n_cells"],
            "n_magnitude_bins": test_fit.diagnostics["n_magnitude_bins"],
            "train_windows": test_fit.diagnostics["train_windows"],
            "validation_windows": test_fit.diagnostics["validation_windows"],
            "train_target_events": test_fit.diagnostics["train_target_events"],
            "validation_target_events": test_fit.diagnostics["validation_target_events"],
            "seam_source": test_fit.diagnostics["seam_source"],
            "fault_density_available": test_fit.diagnostics["static_covariates"][
                "fault_density_available"
            ],
            "faults": test_fit.diagnostics["static_covariates"]["faults"],
            "b_value": test_fit.parameters["b_value"],
            "mc": test_fit.mc,
        },
        "ensemble_fit": {
            "parameter_snapshot_hash": weight_fit.parameter_snapshot_hash,
            "parameters": weight_fit.parameters,
            "diagnostics": weight_fit.diagnostics,
        },
        "etas_baseline": etas_published,
        "models": {
            "gridded-convlstm": {
                "pass_rates": pass_rates(gridded_windows),
                "comparison_vs_etas": comparison_summary(gridded_windows),
                "pooled_information_gain": pooled_information_gain(gridded_windows),
                "pooled_paired_test": pooled_paired_test(gridded_windows),
                "pooled_sensitivity": pooled_sensitivity(gridded_windows),
                "promotion": promotion_decision(
                    pass_rates(gridded_windows),
                    etas_published,
                    pooled_paired_test(gridded_windows),
                    len(schedule),
                ),
                "windows": gridded_windows,
            },
            "ensemble-loglinear": {
                "pass_rates": pass_rates(ensemble_windows),
                "comparison_vs_etas": comparison_summary(ensemble_windows),
                "pooled_information_gain": pooled_information_gain(ensemble_windows),
                "pooled_paired_test": pooled_paired_test(ensemble_windows),
                "pooled_sensitivity": pooled_sensitivity(ensemble_windows),
                "promotion": promotion_decision(
                    pass_rates(ensemble_windows),
                    etas_published,
                    pooled_paired_test(ensemble_windows),
                    len(schedule),
                ),
                "windows": ensemble_windows,
            },
        },
        "note": (
            "A pass means a consistency test did not reject the forecast at alpha; it is not a "
            "skill claim. Skill is only ever claimed from the paired comparison against ETAS. "
            "rupture does not predict earthquakes."
        ),
    }
    report["uniform_component_ablation"] = uniform_component_ablation(
        catalog,
        region,
        validation_times=val_times,
        schedule=schedule,
        etas_validation=ensemble.components["etas"],
        etas_component=etas_component,
        gridded_val=gridded_val,
        gridded_test=gridded_test,
        evaluator=evaluator,
    )
    if not skip_ablation:
        report["leaky_ablation"] = leaky_ablation(
            catalog,
            region,
            config,
            schedule=schedule,
            etas_component=etas_component,
            honest=gridded_test,
        )
    path = out / f"schedule-{region_id}-challengers.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log.info("[%s] wrote %s", region_id, path)
    return report


def _etas_published(repo: Path, region_id: str) -> dict[str, Any]:
    path = (
        repo
        / "reports"
        / "protocol"
        / region_id
        / "eval"
        / f"schedule-{region_id}-etas-mizrahi.json"
    )
    if not path.exists():
        return {"available": False, "reason": f"no published ETAS schedule at {path}"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "available": True,
        "source": str(path),
        "pass_rates": payload["pass_rates"],
        "n_issued": payload["n_issued"],
        "n_scored": payload["n_scored"],
        "catalog_event_hash": payload["catalog_event_hash"],
        "refits": len(payload["refits"]),
        "seed": payload["schedule"]["seed"],
    }


def leaky_ablation(
    catalog: Catalog,
    region: Region,
    config: GriddedConfig,
    *,
    schedule: Sequence[datetime],
    etas_component: Any,
    honest: GriddedChallenger,
) -> dict[str, Any]:
    """ADR-0022 § 6. A gridded fit whose training windows run through the end of the test period.

    The leak is deliberate and total: the model is fitted with a cutoff at the schedule end, so its
    training samples, its static covariates and its normalisation statistics all contain the very
    windows it is then scored on. Its ``fit_cutoff`` is then rewritten to the test cutoff so that
    the ``forecast`` guard, which exists precisely to stop this, can be stepped over on purpose.
    Reported as the Poisson log-likelihood of the observed cell-magnitude counts over the test
    schedule, against the honest fit and against ETAS. It is a measurement of what the leakage
    discipline is worth, never a result.
    """
    leaky = GriddedChallenger(config)
    true_cutoff = SCHEDULE_END
    leaky_fit = leaky.fit(catalog, region, true_cutoff)
    leaky._fit = leaky_fit.model_copy(
        update={
            "fit_cutoff": TEST_CUTOFF,
            "notes": "LEAKY ABLATION: really fitted to " + true_cutoff.isoformat(),
        }
    )

    rows: list[dict[str, Any]] = []
    ll = {"leaky": 0.0, "honest": 0.0, "etas": 0.0}
    n_events = 0
    for t in schedule:
        history = catalog.before(t)
        target = catalog.between(t, t + HORIZON)
        grids = {
            "leaky": leaky.forecast(history, t, HORIZON),
            "honest": honest.forecast(history, t, HORIZON),
            "etas": etas_component(history, t, HORIZON),
        }
        counts = observed_counts(target, grids["honest"])
        n_events += int(counts.sum())
        row: dict[str, Any] = {"issue_time": t.isoformat(), "n_target_events": int(counts.sum())}
        for name, grid in grids.items():
            value = poisson_log_likelihood(grid.counts(), counts)
            ll[name] += value
            row[name] = value
        rows.append(row)
    return {
        "what": (
            "a gridded fit whose cutoff is the schedule end, so its training windows, static "
            "covariates and normalisation statistics contain the scored windows"
        ),
        "leaky_fit_true_cutoff": true_cutoff.isoformat(),
        "honest_fit_cutoff": TEST_CUTOFF.isoformat(),
        "target_events": n_events,
        "poisson_log_likelihood": ll,
        "apparent_gain_from_leakage_per_event": (
            (ll["leaky"] - ll["honest"]) / n_events if n_events else None
        ),
        "windows": rows,
        "warning": (
            "This is not a result. It quantifies the apparent skill a leaked fit buys, so that "
            "the honest numbers can be read against it."
        ),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", required=True)
    parser.add_argument("--repo", default=".")
    parser.add_argument("--skip-ablation", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    run_region(args.region, Paths(Path(args.repo).resolve()), skip_ablation=args.skip_ablation)
    return 0


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
