"""Deliberately leaky variants. **Nothing produced here is a result.**

ADR-0022 decision 6 requires one labelled leaky ablation, so that the cost of the discipline is a
number rather than an assertion. Two are run, because they leak in different places and the
difference between them is itself informative:

``tuning_leak``
    The configuration is chosen by scoring candidates **on the test window** instead of on a
    validation window before the cutoff. The model is still fitted only on pre-cutoff data, so
    this isolates the effect of hyperparameter selection seeing the future — the subtle leak, the
    one that survives code review because the training code looks impeccable.

``fit_leak``
    The parameters are fitted on the **whole catalogue**, test period included, and then used to
    "forecast" windows inside it. The conditioning history at each issue time is still clean, so
    this isolates the effect of the parameters having seen the target events. The gross leak, and
    the one whose size tells you what an unguarded pipeline could claim.

Every artefact from this module carries the model id ``ntpp-LEAKY-ABLATION`` in its forecast ids,
its run-log records and its report, so a leaky grid cannot be mistaken for an honest one anywhere
downstream. Leaky fits are never persisted to ``baselines/``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from rupture.adapters.evaluation.pycsep import PyCSEPEvaluator
from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS
from rupture.domain import Catalog, FitResult, ForecastGrid, Region
from rupture.models.challengers.ntpp.adapter import NeuralTPPForecaster
from rupture.models.challengers.ntpp.model import NTPPConfig
from rupture.models.challengers.ntpp.schedule import run_ntpp_schedule
from rupture.models.challengers.ntpp.train import Trial, candidate_configs, score_config
from rupture.ports import Tracker

LEAKY_MODEL_ID = "ntpp-LEAKY-ABLATION"
TUNING_LEAK_MODEL_ID = f"{LEAKY_MODEL_ID}-tuning"
FIT_LEAK_MODEL_ID = f"{LEAKY_MODEL_ID}-fit"
LEAKY_BANNER = (
    "LEAKY ABLATION - NOT A RESULT: this forecast was produced by a model that was allowed to "
    "see data from inside its own target window, to quantify what the leakage rules are worth."
)


class _LeakyForecaster(NeuralTPPForecaster):
    """Shared labelling for the ablations. Each variant gets its own model id, and it matters.

    A distinct id is not cosmetic. ``ForecastGrid.make_id`` is built from the model id, the
    evaluation bundle is keyed by the forecast id, and ``evaluate_forecast`` skips a window whose
    results file already exists. A leaky variant sharing the honest model's id would therefore
    silently *reuse the honest results* and report them as the ablation's — the exact failure the
    ablation exists to measure, committed by the measuring apparatus.
    """

    model_id: str = LEAKY_MODEL_ID

    def load_fit(self, fit: FitResult, region: Region, weights: dict[str, list[float]]) -> None:
        """Accept an honestly produced fit and relabel it as the ablation's.

        The honest loader refuses a fit whose ``model_id`` is not its own, which is the right
        default. Relabelling here rather than loosening that check means the leaky id propagates
        into every forecast id and run-log record from the moment the fit is loaded.
        """
        super().load_fit(fit.model_copy(update={"model_id": self.model_id}), region, weights)

    @staticmethod
    def _stamp(grid: ForecastGrid, detail: str) -> ForecastGrid:
        return grid.model_copy(update={"notes": f"{LEAKY_BANNER} {detail} {grid.notes}"})


class LeakyTunedForecaster(_LeakyForecaster):
    """The ``tuning_leak`` variant: an honest fit of a configuration chosen on the test window.

    Nothing about the forecasting path is altered — the leak happened before the fit, when the
    configuration was selected. The class exists to carry the label.
    """

    model_id: str = TUNING_LEAK_MODEL_ID

    def forecast(
        self,
        history: Catalog,
        issue_time: datetime,
        horizon: timedelta,
        *,
        n_simulations: int = 200,
        seed: int | None = None,
    ) -> ForecastGrid:
        grid = super().forecast(
            history, issue_time, horizon, n_simulations=n_simulations, seed=seed
        )
        return self._stamp(
            grid, "the hyperparameters were chosen by scoring candidates on the test window."
        )


class LeakyFitForecaster(_LeakyForecaster):
    """The ``fit_leak`` variant: parameters fitted past the issue time, guard deliberately lifted.

    The honest adapter refuses this through ``assert_issue_after_fit``. Rather than weaken that
    guard, this subclass hands ``forecast`` a copy of the fit whose recorded cutoff is the issue
    time — so the assertion still runs and still passes on what it is shown, and the lie is
    confined to one clearly named class that stamps every grid it produces.
    """

    model_id: str = FIT_LEAK_MODEL_ID

    def forecast(
        self,
        history: Catalog,
        issue_time: datetime,
        horizon: timedelta,
        *,
        n_simulations: int = 200,
        seed: int | None = None,
    ) -> ForecastGrid:
        real = self._fit
        if real is None:
            msg = "no fit loaded"
            raise RuntimeError(msg)
        self._fit = real.model_copy(update={"fit_cutoff": issue_time})
        try:
            grid = super(_LeakyForecaster, self).forecast(
                history, issue_time, horizon, n_simulations=n_simulations, seed=seed
            )
        finally:
            self._fit = real
        return self._stamp(
            grid.model_copy(update={"fit_cutoff": real.fit_cutoff}),
            f"the parameters were fitted on data up to {real.fit_cutoff.isoformat()}, "
            "which is inside this window.",
        )


def leaky_select_config(
    catalog: Catalog,
    region: Region,
    *,
    mc: float,
    train_cutoff: datetime,
    test_start: datetime,
    test_end: datetime,
    candidates: Sequence[NTPPConfig] | None = None,
    auxiliary_years: float = 0.5,
) -> tuple[NTPPConfig, list[Trial]]:
    """Choose a configuration by scoring candidates on the **test** window. Never do this."""
    configs = list(candidates) if candidates is not None else candidate_configs()
    trials = [
        Trial(
            config=config,
            folds=(
                score_config(
                    catalog,
                    region,
                    config,
                    mc=mc,
                    train_cutoff=train_cutoff,
                    score_start=test_start,
                    score_end=test_end,
                    auxiliary_years=auxiliary_years,
                    fold=-1,
                ),
            ),
        )
        for config in configs
    ]
    usable = [t for t in trials if t.n_events > 0]
    if not usable:
        msg = "no candidate scored on the test window"
        raise ValueError(msg)
    return min(usable, key=lambda t: t.mean_nll).config, trials


def run_ablations(
    catalog: Catalog,
    region: Region,
    *,
    honest_report: dict[str, Any],
    frozen_config: NTPPConfig,
    mc: float,
    cutoff: datetime,
    start: datetime,
    end: datetime,
    step: timedelta,
    horizon: timedelta,
    baselines_dir: Path,
    forecasts_dir: Path,
    reports_dir: Path,
    benchmark: MizrahiETAS | None = None,
    benchmark_cache: dict[datetime, ForecastGrid] | None = None,
    evaluator: PyCSEPEvaluator | None = None,
    tracker: Tracker | None = None,
    candidates: Sequence[NTPPConfig] | None = None,
    auxiliary_years: float = 0.5,
    n_simulations: int = 200,
    eval_simulations: int = 1000,
    seed: int | None = None,
) -> dict[str, Any]:
    """Run both leaky variants over the same schedule and quantify what the leaks bought.

    ``honest_report`` is the disciplined run's report, produced by
    :func:`~rupture.models.challengers.ntpp.schedule.run_ntpp_schedule`. Every number returned is
    a *difference from* that run, which is the only form in which a leaky score should ever be
    written down.

    ``benchmark_cache`` should be the dictionary the honest run filled, so the ablations are
    compared against the *identical* ETAS grids rather than against a resimulation of them. The
    difference would otherwise carry the benchmark's Monte Carlo noise as well as the leak.
    """
    catalogue_end = catalog.bounds.end_time if catalog.bounds else catalog.max_origin_time()
    if catalogue_end is None:
        msg = "the catalogue has no events, so there is nothing to leak"
        raise ValueError(msg)
    test_end = min(end, catalogue_end)

    # ---- tuning leak: configuration chosen on the test window, fit still pre-cutoff.
    tuned_config, tuning_trials = leaky_select_config(
        catalog,
        region,
        mc=mc,
        train_cutoff=cutoff,
        test_start=start,
        test_end=test_end,
        candidates=candidates,
        auxiliary_years=auxiliary_years,
    )
    tuning_model = LeakyTunedForecaster(tuned_config, auxiliary_years=auxiliary_years)
    tuning_model.fit(catalog, region, cutoff, mc=mc)
    tuning_report = run_ntpp_schedule(
        catalog,
        region,
        tuning_model,
        start=start,
        end=end,
        step=step,
        horizon=horizon,
        baselines_dir=baselines_dir,
        forecasts_dir=forecasts_dir,
        reports_dir=reports_dir,
        benchmark=benchmark,
        benchmark_cache=benchmark_cache,
        evaluator=evaluator,
        tracker=tracker,
        n_simulations=n_simulations,
        eval_simulations=eval_simulations,
        seed=seed,
        mc=mc,
        label="ntpp-ABLATION-tuning-leak",
    )

    # ---- fit leak: parameters fitted on the whole catalogue, including every target window.
    leaky = LeakyFitForecaster(frozen_config, auxiliary_years=auxiliary_years)
    leaky_cutoff = catalogue_end + timedelta(seconds=1)
    leaky_fit = leaky.fit(catalog, region, leaky_cutoff, mc=mc)
    fit_report = run_ntpp_schedule(
        catalog,
        region,
        leaky,
        start=start,
        end=end,
        step=step,
        horizon=horizon,
        baselines_dir=baselines_dir,
        forecasts_dir=forecasts_dir,
        reports_dir=reports_dir,
        benchmark=benchmark,
        benchmark_cache=benchmark_cache,
        evaluator=evaluator,
        tracker=tracker,
        n_simulations=n_simulations,
        eval_simulations=eval_simulations,
        seed=seed,
        mc=mc,
        label="ntpp-ABLATION-fit-leak",
    )

    return {
        "banner": LEAKY_BANNER,
        "honest_label": honest_report.get("label"),
        "tuning_leak": {
            "what_leaked": (
                "the hyperparameter configuration was chosen by scoring candidates on the test "
                "window itself; the fit still used only events before the cutoff"
            ),
            "chosen_config_hash": tuned_config.config_hash(),
            "honest_config_hash": frozen_config.config_hash(),
            "same_config_as_honest": tuned_config.config_hash() == frozen_config.config_hash(),
            "n_candidates": len(tuning_trials),
            "report": tuning_report,
            "delta": _delta(honest_report, tuning_report),
        },
        "fit_leak": {
            "what_leaked": (
                "the parameters were fitted on the whole catalogue, target windows included, and "
                "then used to issue forecasts for windows inside the fitting period; the "
                "conditioning history at each issue time was still strictly before it"
            ),
            "leaky_fit_cutoff": leaky_cutoff.isoformat(),
            "leaky_fit_n_events": leaky_fit.n_events,
            "honest_fit_cutoff": cutoff.isoformat(),
            "report": fit_report,
            "delta": _delta(honest_report, fit_report),
        },
        "note": (
            "These are ablations, never results. They exist to say how much apparent skill "
            "leakage buys on this catalogue and this schedule, and nothing else."
        ),
    }


def _delta(honest: dict[str, Any], leaky: dict[str, Any]) -> dict[str, Any]:
    """Leaky minus honest, per test and on the paired comparison against ETAS."""
    out: dict[str, Any] = {"pass_rate_change": {}}
    for test, detail in leaky.get("pass_rates", {}).items():
        base = honest.get("pass_rates", {}).get(test, {})
        mine, theirs = detail.get("rate"), base.get("rate")
        out["pass_rate_change"][test] = {
            "honest": theirs,
            "leaky": mine,
            "change": None if (mine is None or theirs is None) else mine - theirs,
            "scored": detail.get("scored"),
        }
    honest_gain = honest.get("comparison_summary", {}).get("mean_information_gain_per_event")
    leaky_gain = leaky.get("comparison_summary", {}).get("mean_information_gain_per_event")
    out["information_gain_vs_etas"] = {
        "honest": honest_gain,
        "leaky": leaky_gain,
        "change": (
            None if (honest_gain is None or leaky_gain is None) else leaky_gain - honest_gain
        ),
        "units": "nats per target event",
    }
    out["t_test_wins"] = {
        "honest": honest.get("comparison_summary", {}).get("t_test_wins"),
        "leaky": leaky.get("comparison_summary", {}).get("t_test_wins"),
    }
    out["total_expected_events"] = {
        "honest": sum(w["total_expected"] for w in honest.get("windows", [])),
        "leaky": sum(w["total_expected"] for w in leaky.get("windows", [])),
    }
    return out


def write_ablation_report(
    result: dict[str, Any],
    reports_dir: Path,
    region_id: str,
    *,
    label: str = "ntpp",
) -> Path:
    """Write ``ablations-<region>-<label>.json`` — the committed shape, not the whole run.

    :func:`run_ablations` returns each leaky variant's *entire* schedule report nested under
    ``report``. Committing that would duplicate the two ``schedule-<region>-ntpp-ABLATION-*.json``
    files it already wrote, so what is written here is what a reader needs to judge the ablation:
    the leaky variant's pass rates, its comparison against ETAS, how many windows were scored, and
    the deltas from the honest run. This is the shape of the files committed on 2026-09-03; the
    driver that wrote them was not in the tree, which is why it is here now.
    """
    trimmed: dict[str, Any] = {}
    for key, value in result.items():
        if not isinstance(value, dict) or "report" not in value:
            trimmed[key] = value
            continue
        report = value["report"]
        trimmed[key] = {
            **{k: v for k, v in value.items() if k != "report"},
            "pass_rates": report.get("pass_rates"),
            "comparison_summary": report.get("comparison_summary"),
            "n_scored": report.get("n_scored"),
        }
    out = Path(reports_dir) / "eval" / f"ablations-{region_id}-{label}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(trimmed, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out
