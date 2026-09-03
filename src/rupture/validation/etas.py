"""``validate-etas``: smoke-fit the ETAS baseline on the committed fixture and check it.

Runs offline in well under two minutes on the ComCat California 2018-2019 fixture: a fit with
cutoff 2019-07-01 (auxiliary window 0.5 y, Mc 3.0 = the fixture's query floor), then one 30-day
issuance. Checks:

- fit converged, diagnostics present, no parameter on an inversion bound;
- parameters inside the plausibility bands below (chosen inside ``etas.inversion.RANGES``, the
  package's hard bounds, and stated here so nobody tunes them after the fact);
- branching ratio in (0, 1) (sub-critical);
- forecast grid finite, non-negative, total > 0; same seed gives the same grid;
- ``parameter_snapshot_hash`` reproducible through save/load and by recomputation.

rupture does not predict earthquakes; the gate checks that the baseline was fitted properly.
"""

from __future__ import annotations

import math
import shutil
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from rupture.adapters.forecasting.etas_mizrahi import (
    ETAS_RANGES,
    MizrahiETAS,
    load_fit,
    save_fit,
)
from rupture.domain import Catalog, FitResult, snapshot_hash
from rupture.validation._fixture import load_fixture
from rupture.validation.result import GateResult, GateStatus

FIT_CUTOFF = datetime(2019, 7, 1, tzinfo=UTC)
AUXILIARY_YEARS = 0.5
FIXTURE_MC = 3.0  # the ComCat query floor of the fixture; a floor, not a fitted Mc
N_SIMULATIONS = 50
SEED = 7
RUNTIME_BUDGET_S = 90.0

# Plausibility bands (all inside the package's inversion RANGES). Sources: Mizrahi, Nandan &
# Wiemer (2021, SRL/JGR) California fits; the tapered Omori kernel admits p = 1 + omega < 1.
PLAUSIBLE: dict[str, tuple[float, float]] = {
    "log10_mu": (-9.0, -2.0),  # background events per km^2 per day
    "log10_k0": (-6.0, 2.0),
    "a": (0.5, 3.5),
    "log10_c": (-6.0, 0.0),  # c in [1e-6, 1] days
    "omega": (-0.9, 1.0),  # p in (0.1, 2.0]
    "log10_tau": (1.0, 5.0),  # taper 10 d to ~270 y
    "log10_d": (-4.0, 2.0),
    "gamma": (0.0, 3.0),
    "rho": (0.05, 3.0),
    "beta": (0.5 * math.log(10), 1.7 * math.log(10)),  # b in [0.5, 1.7]
}
REQUIRED_DIAGNOSTICS = (
    "iterations",
    "n_target_events",
    "n_source_events",
    "branching_ratio",
    "b_value",
    "mc",
    "auxiliary_start",
    "timewindow_start",
    "timewindow_end",
    "training_max_origin_time",
    "runtime_s",
)


def run(repo_root: Path) -> GateResult:
    out_dir = repo_root / "reports" / "validate-etas"
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    catalog, region = load_fixture(repo_root)
    findings = [f"fixture: {len(catalog)} events, region {region.id}"]

    model = MizrahiETAS(auxiliary_years=AUXILIARY_YEARS)
    t0 = time.perf_counter()
    fit = model.fit(catalog, region, FIT_CUTOFF, mc=FIXTURE_MC)
    elapsed = time.perf_counter() - t0
    findings.append(
        f"fit: cutoff {FIT_CUTOFF.date()} n_events={fit.n_events} mc={fit.mc} "
        f"iterations={fit.diagnostics.get('iterations')} runtime={elapsed:.1f}s"
    )
    if elapsed > RUNTIME_BUDGET_S:
        findings.append(f"warning: fit exceeded the {RUNTIME_BUDGET_S:.0f}s budget")

    failures = _check_fit(fit, findings)
    failures += _check_hash(fit, region.id, out_dir, findings)
    failures += _check_forecast(model, catalog, fit.mc, findings)
    status = GateStatus.PASSED if not failures else GateStatus.FAILED
    return GateResult(name="validate-etas", status=status, findings=[*failures, *findings])


def _check_fit(fit: FitResult, findings: list[str]) -> list[str]:
    failures: list[str] = []
    if fit.converged is not True:
        failures.append("fit did not converge")
    missing = [k for k in REQUIRED_DIAGNOSTICS if k not in fit.diagnostics]
    if missing:
        failures.append(f"diagnostics missing: {missing}")
    if fit.diagnostics.get("at_bound"):
        failures.append(f"parameters on an inversion bound: {fit.diagnostics['at_bound']}")
    for name, (lo, hi) in PLAUSIBLE.items():
        value = fit.parameters.get(name)
        if value is None or not math.isfinite(value):
            failures.append(f"{name}: missing or non-finite")
            continue
        hard = ETAS_RANGES.get(name)
        if hard is not None and (lo < hard[0] or hi > hard[1]):  # pragma: no cover - static
            failures.append(f"{name}: plausibility band exceeds the package range {hard}")
        if lo <= value <= hi:
            findings.append(f"{name}={value:.4f} in [{lo}, {hi}]")
        else:
            failures.append(f"{name}={value:.4f} outside plausible [{lo}, {hi}]")
    br = fit.diagnostics.get("branching_ratio")
    if br is None or not (0.0 < br < 1.0):
        failures.append(f"branching ratio {br} not in (0, 1)")
    else:
        findings.append(f"branching_ratio={br:.4f} (sub-critical)")
    findings.append(
        f"log_likelihood: {fit.log_likelihood} ({fit.diagnostics.get('log_likelihood_note')})"
    )
    return failures


def _check_hash(fit: FitResult, region_id: str, out_dir: Path, findings: list[str]) -> list[str]:
    failures: list[str] = []
    save_fit(fit, out_dir / "baselines")
    reloaded = load_fit(out_dir / "baselines", region_id)
    if reloaded.parameter_snapshot_hash != fit.parameter_snapshot_hash:
        failures.append("parameter_snapshot_hash changed through save/load")
    if snapshot_hash(reloaded.parameters) != fit.parameter_snapshot_hash:
        failures.append("parameter_snapshot_hash does not recompute from the parameters")
    else:
        findings.append(
            f"parameter_snapshot_hash={fit.parameter_snapshot_hash[:16]}... reproducible"
        )
    return failures


def _check_forecast(
    model: MizrahiETAS, catalog: Catalog, mc: float, findings: list[str]
) -> list[str]:
    failures: list[str] = []
    history = catalog.earthquakes().before(FIT_CUTOFF).at_least(mc)
    horizon = timedelta(days=30)
    grid = model.forecast(history, FIT_CUTOFF, horizon, n_simulations=N_SIMULATIONS, seed=SEED)
    counts = grid.counts()
    total = float(counts.sum())
    if not np.all(np.isfinite(counts)) or np.any(counts < 0):
        failures.append("forecast grid has non-finite or negative counts")
    if not total > 0:
        failures.append("forecast total expected count is not positive")
    findings.append(
        f"forecast {grid.id}: {counts.shape[0]} cells x {counts.shape[1]} bins, total={total:.4f}, "
        f"zero cells={int((counts.sum(axis=1) == 0).sum())}"
    )
    again = model.forecast(history, FIT_CUTOFF, horizon, n_simulations=N_SIMULATIONS, seed=SEED)
    if again.expected_counts != grid.expected_counts:
        failures.append("same seed did not reproduce the forecast grid")
    else:
        findings.append(f"seed={SEED} reproduces the grid exactly")
    return failures
