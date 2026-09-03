"""Pseudo-prospective validation of aftershock forecasts against what actually happened.

For one sequence: issue at a set of elapsed times, and for each issue time score every horizon
whose window closed inside the catalogue's coverage. Two scores, because the product has two
faces:

* the **gridded** forecast is scored with the existing
  :class:`~rupture.adapters.evaluation.pycsep.PyCSEPEvaluator` (N/M/S/L/CL, protocol section 4);
* the **magnitude-threshold probabilities** are scored directly: for each rung of the ladder, the
  expected count ``lambda``, the reported ``P = 1 - exp(-lambda)``, the number of events that
  actually occurred, and the two Poisson tail probabilities ``P(N >= n_obs)`` and ``P(N <= n_obs)``
  under the same Poisson assumption the probability was reported with. A rung is flagged
  inconsistent when the smaller tail is below ``alpha / 2``.

Leakage (protocol section 7) is enforced twice: the fit refuses training data at or after its
cutoff, and the issuance refuses a history that reaches the issue time. Nothing here filters a
target slice by anything except the window it belongs to.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from scipy import stats

from rupture.adapters.evaluation.pycsep import CONSISTENCY_TESTS, PyCSEPEvaluator
from rupture.adapters.forecasting.grid import build_lattice
from rupture.domain import (
    AftershockForecast,
    Catalog,
    EvaluationResult,
    EventType,
    FitResult,
    ForecastGrid,
    Region,
    format_horizon,
    utc_now,
)
from rupture.services.aftershock.forecaster import (
    DEFAULT_HORIZONS,
    POISSON_NOTE,
    AftershockForecaster,
    Issuance,
    scheduled_fit_cutoff,
)
from rupture.services.aftershock.sequences import (
    ISSUE_OFFSETS,
    Mainshock,
    SequenceSpec,
    check_against_catalog,
    fixture_coverage_end,
    load_committed_fits,
    load_parent_region,
    load_sequence_catalog,
    sequence_spec,
)
from rupture.services.aftershock.window import aftershock_zone_radius_km

ALPHA = 0.05


@dataclass(frozen=True, slots=True)
class ThresholdOutcome:
    """One rung of the magnitude ladder, scored against the closed window."""

    magnitude: float
    expected_count: float
    probability: float
    observed_count: int
    occurred: bool
    poisson_p_at_least_observed: float
    poisson_p_at_most_observed: float
    consistent: bool


@dataclass(frozen=True, slots=True)
class CsepOutcome:
    """One CSEP consistency test applied to the gridded forecast."""

    test: str
    statistic: float
    quantile: float | None
    quantile_low: float | None
    quantile_high: float | None
    passed: bool | None
    n_target_events: int


@dataclass(frozen=True, slots=True)
class WindowOutcome:
    """One (issue time, horizon) pair: the forecast, and what the closed window contained."""

    sequence_id: str
    issue_label: str
    issue_time: str
    horizon: str
    window_end: str
    elapsed: str
    forecast_id: str
    forecast_grid_id: str
    fit_cutoff: str
    n_training_events: int
    n_sequence_events: int
    branching_ratio: float | None
    b_value: float
    b_value_fixed: bool
    total_expected_above_target: float
    n_observed_above_target: int
    thresholds: list[ThresholdOutcome] = field(default_factory=list)
    csep: list[CsepOutcome] = field(default_factory=list)
    largest_observed_magnitude: float | None = None
    largest_observed_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class SequenceOutcome:
    """Everything the validation produced for one sequence."""

    sequence_id: str
    description: str
    mainshock_event_id: str
    mainshock_time: str
    mainshock_magnitude: float
    region_id: str
    zone_radius_km: float
    n_cells: int
    mc: float
    target_min_magnitude: float
    catalog_coverage_end: str
    n_catalog_events: int
    windows: list[WindowOutcome] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    evaluated_at: str = ""


def observed_in_window(
    catalog: Catalog,
    region: Region,
    grid: ForecastGrid,
    start: datetime,
    end: datetime,
) -> Catalog:
    """Earthquakes in ``[start, end)`` that fall inside a cell of ``grid`` and the depth range.

    The spatial test is the grid's own lattice, so the target slice contains exactly the events
    the forecast could have placed. Events without a homogenised Mw are kept here and counted out
    by the evaluator (which reports them), never dropped silently.
    """
    lattice = build_lattice(region)
    window = catalog.between(start, end).of_type(EventType.EARTHQUAKE)
    if not window.events:
        return window
    lons = np.fromiter((e.longitude for e in window.events), dtype=np.float64, count=len(window))
    lats = np.fromiter((e.latitude for e in window.events), dtype=np.float64, count=len(window))
    cells = lattice.cell_indices(lons, lats)
    kept = tuple(
        e
        for e, cell in zip(window.events, cells.tolist(), strict=True)
        if cell >= 0
        and (e.depth_km is None or region.depth_min_km <= e.depth_km <= region.depth_max_km)
    )
    return window.model_copy(update={"events": kept, "id": f"{window.id}/in-grid"})


def score_thresholds(
    forecast: AftershockForecast, target: Catalog, *, alpha: float = ALPHA
) -> list[ThresholdOutcome]:
    """Score each rung of the ladder against the events in the closed window."""
    magnitudes = np.asarray([e.mw for e in target.events if e.mw is not None], dtype=np.float64)
    out: list[ThresholdOutcome] = []
    for rung in forecast.probabilities:
        observed = int(np.sum(magnitudes >= rung.magnitude - 1e-9))
        lam = rung.expected_count
        p_ge = float(stats.poisson.sf(observed - 1, lam)) if observed > 0 else 1.0
        p_le = float(stats.poisson.cdf(observed, lam))
        out.append(
            ThresholdOutcome(
                magnitude=rung.magnitude,
                expected_count=lam,
                probability=rung.probability,
                observed_count=observed,
                occurred=observed > 0,
                poisson_p_at_least_observed=p_ge,
                poisson_p_at_most_observed=p_le,
                consistent=min(p_ge, p_le) >= alpha / 2.0,
            )
        )
    return out


def evaluate_window(
    *,
    issuance: Issuance,
    catalog: Catalog,
    sequence_id: str,
    issue_label: str,
    evaluator: PyCSEPEvaluator,
    alpha: float = ALPHA,
    csep_simulations: int = 1000,
    seed: int | None = 11,
) -> WindowOutcome:
    """Score one issued forecast against its closed window."""
    forecast, grid, fit, region = (
        issuance.forecast,
        issuance.grid,
        issuance.fit,
        issuance.region,
    )
    target = observed_in_window(catalog, region, grid, grid.issue_time, grid.window_end)
    csep_results: Sequence[EvaluationResult] = evaluator.evaluate(
        grid,
        target,
        CONSISTENCY_TESTS,
        n_simulations=csep_simulations,
        alpha=alpha,
        seed=seed,
    )
    with_mw = [e for e in target.events if e.mw is not None]
    above = [e for e in with_mw if e.mw is not None and e.mw >= region.target_min_magnitude - 1e-9]
    largest = max(above, key=lambda e: e.mw or 0.0) if above else None
    return WindowOutcome(
        sequence_id=sequence_id,
        issue_label=issue_label,
        issue_time=forecast.issue_time.isoformat(),
        horizon=format_horizon(forecast.horizon),
        window_end=forecast.window_end.isoformat(),
        elapsed=format_horizon(forecast.elapsed) if forecast.elapsed else "0d",
        forecast_id=forecast.id,
        forecast_grid_id=grid.id,
        fit_cutoff=fit.fit_cutoff.isoformat(),
        n_training_events=fit.n_events,
        n_sequence_events=forecast.n_sequence_events,
        branching_ratio=fit.diagnostics.get("branching_ratio"),
        b_value=float(fit.diagnostics["b_value"]),
        b_value_fixed=bool(fit.diagnostics.get("beta_fixed", False)),
        total_expected_above_target=grid.total_expected(),
        n_observed_above_target=len(above),
        thresholds=score_thresholds(forecast, target, alpha=alpha),
        csep=[_csep_row(r) for r in csep_results],
        largest_observed_magnitude=largest.mw if largest is not None else None,
        largest_observed_event_id=largest.source_event_id if largest is not None else None,
    )


def _csep_row(result: EvaluationResult) -> CsepOutcome:
    return CsepOutcome(
        test=result.test_name.value,
        statistic=result.statistic,
        quantile=result.quantile,
        quantile_low=result.quantile_low,
        quantile_high=result.quantile_high,
        passed=result.passed,
        n_target_events=result.n_target_events,
    )


def run_sequence(
    spec: SequenceSpec,
    catalog: Catalog,
    parent_region: Region,
    *,
    forecaster: AftershockForecaster,
    coverage_end: datetime,
    issue_offsets: tuple[tuple[str, timedelta], ...] = ISSUE_OFFSETS,
    horizons: tuple[timedelta, ...] = DEFAULT_HORIZONS,
    fits: dict[str, FitResult] | None = None,
    alpha: float = ALPHA,
    csep_simulations: int = 1000,
) -> SequenceOutcome:
    """Issue and score the whole (issue time x horizon) matrix for one sequence.

    ``fits`` maps an ISO fit cutoff to a persisted :class:`~rupture.domain.FitResult`, so a caller
    with committed fits (the gate) does not refit. A window whose end is after ``coverage_end`` is
    not closed by the catalogue and is skipped with a printed reason rather than scored against
    a slice that is missing its tail.
    """
    mainshock = spec.mainshock
    region = forecaster.zone(mainshock, parent_region)
    lattice = build_lattice(region)
    evaluator = PyCSEPEvaluator()
    outcome_windows: list[WindowOutcome] = []
    skipped: list[str] = []
    mc = region.mc.mc if region.mc is not None else float("nan")

    for issue_label, offset in issue_offsets:
        issue_time = mainshock.origin_time + offset
        cutoff = scheduled_fit_cutoff(mainshock.origin_time, issue_time)
        key = cutoff.isoformat()
        fit = (fits or {}).get(key)
        if fit is None:
            fit = forecaster.fit(catalog, region, cutoff)
        history = catalog.before(issue_time)
        for horizon in horizons:
            if issue_time + horizon > coverage_end:
                skipped.append(
                    f"{spec.id} issue+{issue_label} horizon {format_horizon(horizon)}: window "
                    f"ends {(issue_time + horizon).isoformat()}, after catalogue coverage "
                    f"{coverage_end.isoformat()}"
                )
                continue
            issuance = forecaster.issue(
                history=history,
                region=region,
                mainshock=mainshock,
                fit=fit,
                issue_time=issue_time,
                horizon=horizon,
            )
            outcome_windows.append(
                evaluate_window(
                    issuance=issuance,
                    catalog=catalog,
                    sequence_id=spec.id,
                    issue_label=issue_label,
                    evaluator=evaluator,
                    alpha=alpha,
                    csep_simulations=csep_simulations,
                )
            )
    return SequenceOutcome(
        sequence_id=spec.id,
        description=spec.description,
        mainshock_event_id=mainshock.event_id,
        mainshock_time=mainshock.origin_time.isoformat(),
        mainshock_magnitude=mainshock.magnitude,
        region_id=region.id,
        zone_radius_km=round(_zone_radius(mainshock), 1),
        n_cells=lattice.n_cells,
        mc=mc,
        target_min_magnitude=region.target_min_magnitude,
        catalog_coverage_end=coverage_end.isoformat(),
        n_catalog_events=len(catalog),
        windows=outcome_windows,
        skipped=skipped,
        evaluated_at=utc_now().isoformat(),
    )


def _zone_radius(mainshock: Mainshock) -> float:
    return aftershock_zone_radius_km(mainshock.magnitude)


def validate_sequence(
    name: str,
    repo_root: Path,
    *,
    forecaster: AftershockForecaster | None = None,
    use_committed_fits: bool = True,
    issue_offsets: tuple[tuple[str, timedelta], ...] = ISSUE_OFFSETS,
    horizons: tuple[timedelta, ...] = DEFAULT_HORIZONS,
    csep_simulations: int = 1000,
) -> SequenceOutcome:
    """Load the committed slice for ``name`` and run the whole validation, offline."""
    spec = sequence_spec(name)
    catalog = load_sequence_catalog(spec, repo_root)
    problems = check_against_catalog(spec, catalog)
    if problems:
        msg = "; ".join(problems)
        raise ValueError(f"declared mainshock disagrees with the catalogue: {msg}")
    parent = load_parent_region(spec, repo_root)
    fits = load_committed_fits(spec, repo_root) if use_committed_fits else {}
    return run_sequence(
        spec,
        catalog,
        parent,
        forecaster=forecaster or AftershockForecaster(),
        coverage_end=fixture_coverage_end(spec, repo_root),
        issue_offsets=issue_offsets,
        horizons=horizons,
        fits=fits,
        csep_simulations=csep_simulations,
    )


# ---------------------------------------------------------------------- reporting
def write_report(outcome: SequenceOutcome, out_dir: Path) -> tuple[Path, Path]:
    """Write ``<sequence>.json`` and ``<sequence>.md``; return both paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{outcome.sequence_id}.json"
    json_path.write_text(
        json.dumps(asdict(outcome), indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    md_path = out_dir / f"{outcome.sequence_id}.md"
    md_path.write_text(render_markdown(outcome), encoding="utf-8")
    return json_path, md_path


def render_markdown(outcome: SequenceOutcome) -> str:
    """A table of the real numbers, poor ones included."""
    lines = [
        f"# Aftershock forecast validation - {outcome.sequence_id}",
        "",
        f"{outcome.description}",
        "",
        f"- mainshock: `{outcome.mainshock_event_id}` "
        f"M{outcome.mainshock_magnitude:.1f} at {outcome.mainshock_time}",
        f"- zone: region `{outcome.region_id}`, radius {outcome.zone_radius_km:.0f} km, "
        f"{outcome.n_cells} cells",
        f"- Mc {outcome.mc}, target threshold M{outcome.target_min_magnitude}",
        f"- catalogue: {outcome.n_catalog_events} events, coverage ends "
        f"{outcome.catalog_coverage_end}",
        f"- probabilities are `1 - exp(-lambda)`: {POISSON_NOTE}",
        f"- evaluated at {outcome.evaluated_at}",
        "",
        "## Magnitude-threshold probabilities against the closed windows",
        "",
        "| issue | horizon | M>= | lambda | P | observed | P(N>=obs) | P(N<=obs) | consistent |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for w in outcome.windows:
        for t in w.thresholds:
            lines.append(
                f"| +{w.issue_label} | {w.horizon} | {t.magnitude:.1f} | "
                f"{t.expected_count:.4g} | {t.probability:.4f} | {t.observed_count} | "
                f"{t.poisson_p_at_least_observed:.4f} | {t.poisson_p_at_most_observed:.4f} | "
                f"{'yes' if t.consistent else '**no**'} |"
            )
    lines += [
        "",
        "## Gridded forecast: CSEP consistency tests",
        "",
        "| issue | horizon | fit cutoff | n_train | total expected | observed | test | statistic "
        "| quantile | passed |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for w in outcome.windows:
        for row in w.csep:
            if row.quantile is None:
                quantile = f"lo={row.quantile_low}, hi={row.quantile_high}"
            else:
                quantile = f"{row.quantile:.4f}"
            lines.append(
                f"| +{w.issue_label} | {w.horizon} | {w.fit_cutoff} | {w.n_training_events} | "
                f"{w.total_expected_above_target:.2f} | {w.n_observed_above_target} | "
                f"{row.test} | {row.statistic:.4g} | {quantile} | {row.passed} |"
            )
    lines += ["", "## Fits used", "", "| issue | fit cutoff | n_train | b | b fixed | branching |"]
    lines.append("|---|---|---|---|---|---|")
    seen: set[str] = set()
    for w in outcome.windows:
        if w.fit_cutoff in seen:
            continue
        seen.add(w.fit_cutoff)
        branching = "n/a" if w.branching_ratio is None else f"{w.branching_ratio:.3f}"
        lines.append(
            f"| +{w.issue_label} | {w.fit_cutoff} | {w.n_training_events} | {w.b_value:.3f} | "
            f"{'yes' if w.b_value_fixed else 'no'} | {branching} |"
        )
    if outcome.skipped:
        lines += ["", "## Windows not scored", ""]
        lines += [f"- {reason}" for reason in outcome.skipped]
    lines.append("")
    return "\n".join(lines)
