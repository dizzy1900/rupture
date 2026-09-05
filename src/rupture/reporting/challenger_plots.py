"""Render the figures that back ``reports/CHALLENGER_EVALUATION.md``.

The brief asks the challenger evaluation to carry plots. This module draws them, and it draws them
**only** from evidence that is already committed to the repository:

* ``reports/challenger/<region>/schedule-<region>-challengers.json`` — the gridded and ensemble
  schedules, their per-window paired comparison against ETAS, and the leaky gridded ablation;
* ``reports/protocol/<region>/eval/schedule-<region>-ntpp.json`` — the neural point process, and
  the matched ETAS re-run it was scored against;
* ``reports/protocol/<region>/eval/ablations-<region>-ntpp.json`` — the two NTPP leaks.

No model is loaded, no forecast is issued and nothing is refitted, so the figures cannot drift away
from the numbers in the document: they *are* those numbers. A missing input is an error, never an
empty panel — a plot of nothing would be a plot of something that did not run.

Run it as::

    uv run python -m rupture.reporting.challenger_plots

Three figures per region are written under ``reports/challenger/<region>/``:

``ig-per-window-<region>.png``
    Per-window information gain per target event against ETAS for all three challengers, over the
    target count in each window. This is the figure behind the "one window in ten" argument: the
    pooled means are carried by a handful of windows, and most windows hold no target event at all.

``pass-rates-<region>.png``
    Cumulative count of windows passed, per consistency test, for each challenger against ETAS run
    through the same schedule. Promotion condition 1 is read off the end of each line.

``leakage-<region>.png``
    What the leakage controls are worth: the cumulative log-likelihood advantage over ETAS of an
    honest gridded fit against a leaked one, and the NTPP's honest and leaked information gain with
    the fraction of the apparent gain that the controls remove.

Two conventions the figures rely on. pycsep's paired T-test statistic (Rhoades et al. 2011) *is*
the information gain per target event, so the per-window points are read straight from
``comparison.T.statistic`` rather than recomputed here. And a window with no target event decides
nothing: its consistency tests report ``passed: null`` and it is dropped from that test's
denominator, exactly as the schedules' own pass rates do.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: The two regions whose challenger schedules completed. California ran 6 of 55 ETAS windows and
#: no challenger was fitted there (RELEASE_STATUS.md), so it has nothing to plot and is not faked.
REGIONS: Final[tuple[str, ...]] = ("turkiye-eaf", "nepal-himalaya")

TESTS: Final[tuple[str, ...]] = ("N", "M", "S", "L", "CL")

CHALLENGERS: Final[tuple[str, ...]] = ("ntpp", "gridded-convlstm", "ensemble-loglinear")

#: Stable colours so a reader comparing two regions is comparing the same models.
COLOURS: Final[dict[str, str]] = {
    "ntpp": "#1b6ca8",
    "gridded-convlstm": "#c1663a",
    "ensemble-loglinear": "#2f7d4f",
    "etas": "#555555",
    "leaky": "#a4243b",
}

LABELS: Final[dict[str, str]] = {
    "ntpp": "NTPP (neural point process)",
    "gridded-convlstm": "gridded ConvLSTM",
    "ensemble-loglinear": "log-linear ensemble",
    "etas": "ETAS (same schedule)",
}


class MissingEvidenceError(FileNotFoundError):
    """Raised when a committed evidence file this module draws from is absent."""


@dataclass(frozen=True)
class WindowPoint:
    """One scored 30-day window of a pseudo-prospective schedule."""

    issue_time: datetime
    n_target_events: int
    #: Information gain per target event against ETAS; ``None`` where the window decides nothing.
    information_gain: float | None
    #: ``True`` when the paired T-test's lower bound is above zero; ``None`` where undecided.
    t_test_win: bool | None
    #: Per-test pass flags; ``None`` for a test this window could not decide.
    tests: dict[str, bool | None]


@dataclass(frozen=True)
class ModelSeries:
    """One model's whole schedule in one region."""

    model_key: str
    windows: tuple[WindowPoint, ...]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MissingEvidenceError(
            f"{path} is not committed; these figures are drawn only from committed evidence, "
            "so a missing input is an error rather than an empty panel"
        )
    with path.open(encoding="utf-8") as handle:
        loaded: Any = json.load(handle)
    if not isinstance(loaded, dict):
        raise MissingEvidenceError(f"{path} is not a JSON object")
    return loaded


def _tests_from(raw: dict[str, Any], key: str) -> dict[str, bool | None]:
    block = raw.get(key) or {}
    out: dict[str, bool | None] = {}
    for test in TESTS:
        entry = block.get(test)
        # `passed: null` means the window decided nothing (no target event), not that the test
        # failed. Reading it as a failure would invent failures nobody measured.
        passed = None if entry is None else entry.get("passed")
        out[test] = None if passed is None else bool(passed)
    return out


def _window_point(raw: dict[str, Any]) -> WindowPoint:
    n_events = int(raw["n_target_events"])
    comparison = (raw.get("comparison") or {}).get("T") or {}
    statistic = comparison.get("statistic")
    gain = None if n_events == 0 or statistic is None else float(statistic)
    passed = comparison.get("passed")
    return WindowPoint(
        issue_time=datetime.fromisoformat(raw["issue_time"]),
        n_target_events=n_events,
        information_gain=gain,
        t_test_win=None if passed is None else bool(passed),
        tests=_tests_from(raw, "tests"),
    )


def load_series(region: str, *, repo_root: Path = REPO_ROOT) -> dict[str, ModelSeries]:
    """The four schedules (ETAS and three challengers) for one region, aligned by issue time."""
    reports = repo_root / "reports"
    challengers = _read_json(
        reports / "challenger" / region / f"schedule-{region}-challengers.json"
    )
    ntpp = _read_json(reports / "protocol" / region / "eval" / f"schedule-{region}-ntpp.json")

    series: dict[str, ModelSeries] = {}
    for model_key, block in challengers["models"].items():
        series[model_key] = ModelSeries(
            model_key=model_key, windows=tuple(_window_point(w) for w in block["windows"])
        )
    series["ntpp"] = ModelSeries(
        model_key="ntpp", windows=tuple(_window_point(w) for w in ntpp["windows"])
    )
    # The ETAS row is the matched re-run carried inside the NTPP schedule (no refits, 100
    # continuations), which is what the challengers were actually scored against. The published
    # baseline of record in docs/BASELINE_RESULTS.md is a different run — yearly refits, 1000
    # continuations — and is deliberately not mixed in here.
    series["etas"] = ModelSeries(
        model_key="etas",
        windows=tuple(
            WindowPoint(
                issue_time=datetime.fromisoformat(w["issue_time"]),
                n_target_events=int(w["n_target_events"]),
                information_gain=None,
                t_test_win=None,
                tests=_tests_from(w, "benchmark_tests"),
            )
            for w in ntpp["windows"]
        ),
    )
    reference = [w.issue_time for w in series["ntpp"].windows]
    for key, model in series.items():
        if [w.issue_time for w in model.windows] != reference:
            raise MissingEvidenceError(
                f"{region}: {key} was scored on different issue times from the NTPP schedule; "
                "these series are not comparable and are not drawn on one axis"
            )
    return series


def _style(ax: Any) -> None:
    ax.grid(alpha=0.25, linewidth=0.6)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)


def _year_ticks(times: list[datetime]) -> tuple[list[int], list[str]]:
    """Tick at the first window of each calendar year: a numeric axis, dated for the reader."""
    positions: list[int] = []
    labels: list[str] = []
    seen: set[int] = set()
    for index, moment in enumerate(times):
        if moment.year not in seen:
            seen.add(moment.year)
            positions.append(index)
            labels.append(str(moment.year))
    return positions, labels


def plot_information_gain(region: str, series: dict[str, ModelSeries], out: Path) -> Path:
    """Per-window information gain against ETAS, over the target count in each window."""
    fig, (top, bottom) = plt.subplots(
        2, 1, figsize=(11, 6.5), sharex=True, height_ratios=[3, 1], constrained_layout=True
    )
    for key in CHALLENGERS:
        model = series.get(key)
        if model is None:
            continue
        indices = [i for i, w in enumerate(model.windows) if w.information_gain is not None]
        gains = [model.windows[i].information_gain for i in indices]
        top.plot(
            indices,
            gains,
            marker="o",
            markersize=4,
            linewidth=1.1,
            color=COLOURS[key],
            label=LABELS[key],
            alpha=0.9,
        )
        wins = [i for i, w in enumerate(model.windows) if w.t_test_win]
        if wins:
            top.scatter(
                wins,
                [model.windows[i].information_gain for i in wins],
                s=120,
                facecolors="none",
                edgecolors=COLOURS[key],
                linewidths=1.6,
                zorder=5,
            )
    top.axhline(0.0, color=COLOURS["etas"], linewidth=1.2, linestyle="--")
    top.set_ylabel("information gain per target event\nvs ETAS (nats)")
    top.set_title(
        f"{region}: per-window paired comparison against ETAS.\n"
        "Circled = the paired T-test decides a win in that window. Windows with no target event "
        "decide nothing and are not drawn.",
        fontsize=10,
        loc="left",
    )
    top.legend(fontsize=8, loc="upper left", framealpha=0.9)
    _style(top)

    windows = series["ntpp"].windows
    bottom.bar(
        range(len(windows)), [w.n_target_events for w in windows], width=0.75, color="#8a8a8a"
    )
    bottom.set_ylabel("target\nevents")
    bottom.set_yscale("symlog", linthresh=1)
    positions, labels = _year_ticks([w.issue_time for w in windows])
    bottom.set_xticks(positions)
    bottom.set_xticklabels(labels)
    bottom.set_xlabel("30-day window, in issue order")
    _style(bottom)

    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def plot_pass_rates(region: str, series: dict[str, ModelSeries], out: Path) -> Path:
    """Cumulative windows passed, per consistency test — promotion condition 1, drawn."""
    fig, axes = plt.subplots(1, len(TESTS), figsize=(13, 3.4), constrained_layout=True)
    for ax, test in zip(axes, TESTS, strict=True):
        for key in ("etas", *CHALLENGERS):
            model = series.get(key)
            if model is None:
                continue
            cumulative: list[int] = []
            total = 0
            for window in model.windows:
                decided = window.tests.get(test)
                if decided is None:
                    continue
                total += 1 if decided else 0
                cumulative.append(total)
            ax.plot(
                range(1, len(cumulative) + 1),
                cumulative,
                linewidth=1.8 if key == "etas" else 1.3,
                linestyle="--" if key == "etas" else "-",
                color=COLOURS[key],
                label=LABELS[key],
            )
        ax.set_title(f"{test}-test", fontsize=10)
        ax.set_xlabel("windows that decided\nthis test")
        _style(ax)
    axes[0].set_ylabel("windows passed\n(cumulative)")
    axes[0].legend(fontsize=7, loc="lower right", framealpha=0.9)
    fig.suptitle(
        f"{region}: cumulative consistency-test passes. A pass means the test did not reject at "
        "the 0.05 significance level; it is not a skill claim.",
        fontsize=10,
        x=0.01,
        ha="left",
    )
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def _vanished_label(honest: float, leaky: float) -> str:
    """How much of the apparent gain the controls remove, phrased so it cannot mislead."""
    if leaky <= 0.0:
        return "no apparent gain\nto remove"
    fraction = (leaky - honest) / leaky
    if honest < 0.0:
        return f"{fraction:.0%} removed\n— all of it, and the sign"
    return f"{fraction:.0%} removed"


def plot_leakage(region: str, out: Path, *, repo_root: Path = REPO_ROOT) -> Path:
    """Honest against leaked: what the leakage controls remove, in the units of the result."""
    reports = repo_root / "reports"
    challengers = _read_json(
        reports / "challenger" / region / f"schedule-{region}-challengers.json"
    )
    ablations = _read_json(reports / "protocol" / region / "eval" / f"ablations-{region}-ntpp.json")
    ablation = challengers["leaky_ablation"]

    fig, (left, right) = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)

    honest_cum: list[float] = []
    leaky_cum: list[float] = []
    honest_total = 0.0
    leaky_total = 0.0
    for window in ablation["windows"]:
        honest_total += float(window["honest"]) - float(window["etas"])
        leaky_total += float(window["leaky"]) - float(window["etas"])
        honest_cum.append(honest_total)
        leaky_cum.append(leaky_total)
    left.plot(
        range(len(honest_cum)),
        honest_cum,
        color=COLOURS["gridded-convlstm"],
        linewidth=1.6,
        label="honest fit (cutoff 2022-01-01)",
    )
    left.plot(
        range(len(leaky_cum)),
        leaky_cum,
        color=COLOURS["leaky"],
        linewidth=1.6,
        label="leaked fit (cutoff = schedule end)",
    )
    left.axhline(0.0, color=COLOURS["etas"], linewidth=1.2, linestyle="--")
    positions, labels = _year_ticks(
        [datetime.fromisoformat(w["issue_time"]) for w in ablation["windows"]]
    )
    left.set_xticks(positions)
    left.set_xticklabels(labels)
    left.set_ylabel("cumulative log-likelihood\nadvantage over ETAS (nats)")
    left.set_xlabel("30-day window, in issue order")
    left.set_title(
        "gridded ConvLSTM: an honest fit against a leaked one\n"
        f"({ablation['target_events']} target events; the leaked series is not a result)",
        fontsize=10,
        loc="left",
    )
    left.legend(fontsize=8, loc="upper left", framealpha=0.9)
    _style(left)

    names = ("fit_leak", "tuning_leak")
    pretty = ("fit across the cutoff", "tuned on the test window")
    honest_ig = [float(ablations[n]["delta"]["information_gain_vs_etas"]["honest"]) for n in names]
    leaky_ig = [float(ablations[n]["delta"]["information_gain_vs_etas"]["leaky"]) for n in names]
    positions_bar = list(range(len(names)))
    right.bar(
        [p - 0.19 for p in positions_bar],
        honest_ig,
        width=0.36,
        color=COLOURS["ntpp"],
        label="honest",
    )
    right.bar(
        [p + 0.19 for p in positions_bar],
        leaky_ig,
        width=0.36,
        color=COLOURS["leaky"],
        label="leaked",
    )
    for position, honest, leaky in zip(positions_bar, honest_ig, leaky_ig, strict=True):
        right.annotate(
            _vanished_label(honest, leaky),
            xy=(position, max(honest, leaky, 0.0)),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            fontsize=8,
        )
    right.axhline(0.0, color=COLOURS["etas"], linewidth=1.2)
    right.set_xticks(positions_bar)
    right.set_xticklabels(pretty, fontsize=9)
    right.set_ylabel("information gain per\ntarget event vs ETAS (nats)")
    right.set_title(
        "NTPP: the gain each leak appears to buy, and the\nfraction the leakage controls remove",
        fontsize=10,
        loc="left",
    )
    right.margins(y=0.22)
    right.legend(fontsize=8, framealpha=0.9)
    _style(right)

    fig.suptitle(
        f"{region}: what the anti-leakage engineering is worth. Neither leaked series is a result.",
        fontsize=10,
        x=0.01,
        ha="left",
    )
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def render_all(*, repo_root: Path = REPO_ROOT) -> list[Path]:
    """Draw every figure for every region with a completed challenger schedule."""
    written: list[Path] = []
    for region in REGIONS:
        out_dir = repo_root / "reports" / "challenger" / region
        out_dir.mkdir(parents=True, exist_ok=True)
        series = load_series(region, repo_root=repo_root)
        written.append(
            plot_information_gain(region, series, out_dir / f"ig-per-window-{region}.png")
        )
        written.append(plot_pass_rates(region, series, out_dir / f"pass-rates-{region}.png"))
        written.append(plot_leakage(region, out_dir / f"leakage-{region}.png", repo_root=repo_root))
    return written


def main() -> int:
    """Entry point for ``python -m rupture.reporting.challenger_plots``."""
    for path in render_all():
        relative = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
        sys.stdout.write(f"wrote {relative}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
