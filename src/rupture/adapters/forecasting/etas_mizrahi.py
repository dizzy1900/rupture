"""ETAS baseline: the ``etas`` package of Mizrahi et al. behind the ``ForecastModel`` port.

See ADR-0009 (why this package), ADR-0018 (how a forecast is issued from a stored fit without
refitting, and how expected counts are formed) and ``docs/ETAS_BASELINE.md`` (configuration,
persistence, limitations).

rupture does not predict earthquakes; this adapter produces expected counts per cell and
magnitude bin over a horizon, from parameters fitted only on events before a hard cutoff.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pandas as pd
from etas import inversion as etas_inversion
from etas import simulation as etas_sim
from scipy.special import ndtr
from shapely.geometry import Point, Polygon

from rupture.adapters.forecasting.grid import (
    Lattice,
    build_lattice,
    region_polygon,
    shape_coords_lat_lon,
)
from rupture.adapters.forecasting.leakage import (
    LeakageError,
    assert_all_before,
    assert_issue_after_fit,
)
from rupture.domain import Catalog, FitResult, ForecastGrid, Region, snapshot_hash, utc_now

log = logging.getLogger(__name__)

MODEL_ID = "etas-mizrahi"
ETAS_COMMIT = "097f08b69a4f06f9c38d14799dedfbd4543144e3"
THETA_KEYS: tuple[str, ...] = (
    "log10_mu",
    "log10_k0",
    "a",
    "log10_c",
    "omega",
    "log10_tau",
    "log10_d",
    "gamma",
    "rho",
)
PARAMETER_KEYS: tuple[str, ...] = (*THETA_KEYS, "beta")

# Fixed EM starting point so a fit is reproducible run-to-run (the package otherwise draws a
# random start, which moves the converged values at the 1e-3 level). Values are of the order
# reported for California by Mizrahi, Nandan & Wiemer (2021); mu is re-estimated at the first
# expectation step so its start value is immaterial.
DEFAULT_THETA_0: dict[str, float | None] = {
    "log10_mu": -6.0,
    "log10_iota": None,
    "log10_k0": -2.5,
    "a": 1.8,
    "log10_c": -2.5,
    "omega": -0.02,
    "log10_tau": 3.5,
    "log10_d": -0.5,
    "gamma": 1.2,
    "rho": 0.6,
}

# Inversion bounds of the package (etas.inversion.RANGES). A fitted value sitting on a bound is
# reported as ``at_bound`` in the diagnostics.
ETAS_RANGES: dict[str, tuple[float, float]] = {
    "log10_mu": etas_inversion.LOG10_MU_RANGE,
    "log10_k0": etas_inversion.LOG10_K0_RANGE,
    "a": etas_inversion.A_RANGE,
    "log10_c": etas_inversion.LOG10_C_RANGE,
    "omega": etas_inversion.OMEGA_RANGE,
    "log10_tau": etas_inversion.LOG10_TAU_RANGE,
    "log10_d": etas_inversion.LOG10_D_RANGE,
    "gamma": etas_inversion.GAMMA_RANGE,
    "rho": etas_inversion.RHO_RANGE,
}

FIT_RESULT_FILE = "fit_result.json"
PARAMETERS_FILE = "parameters.json"
DIAGNOSTICS_FILE = "diagnostics.json"

EARTH_RADIUS_KM = 6.3781e3  # the package's value
EM_TOLERANCE = 0.001  # the package's convergence criterion (summed absolute parameter change)
LL_NOTE = (
    "space-time ETAS log-likelihood of the primary window at the fitted theta, conditional on "
    "the auxiliary catalogue; magnitudes excluded (fixed beta); no spatial boundary correction, "
    "matching the package's own EM objective. See point_process_log_likelihood and ADR-0046."
)


def _etas_version() -> str:
    try:
        v = version("etas")
    except PackageNotFoundError:  # pragma: no cover - installed from the lockfile
        v = "unknown"
    return f"etas-{v}+{ETAS_COMMIT[:7]}"


def _naive_utc(ts: datetime) -> datetime:
    return ts.astimezone(UTC).replace(tzinfo=None)


def _aware(ts: pd.Timestamp | datetime) -> datetime:
    out = pd.Timestamp(ts).to_pydatetime()
    return out.replace(tzinfo=UTC) if out.tzinfo is None else out.astimezone(UTC)


def _to_float(value: Any) -> float:
    return float(np.asarray(value, dtype=np.float64))


def gr_bin_probabilities(
    beta: float, mc_lower: float, edges: tuple[float, ...], m_max_upper: float | None
) -> npt.NDArray[np.float64]:
    """P(binned magnitude falls in bin j | m >= mc_lower) for the package's GR conventions.

    The package draws continuous magnitudes m >= ``mc_lower`` (= mc - delta_m/2) from an
    exponential law with rate ``beta`` (optionally truncated at ``m_max_upper``) and rounds them
    to the nearest bin centre, so the mass of bin ``[edge_j, edge_j+1)`` is the exponential mass on
    that interval; the last bin is open. Returned probabilities sum to P(m >= edges[0]).
    """
    e = np.asarray(edges, dtype=np.float64)
    upper = np.append(e[1:], np.inf)
    norm = 1.0 if m_max_upper is None else 1.0 - math.exp(-beta * (m_max_upper - mc_lower))
    if m_max_upper is not None:
        e = np.minimum(e, m_max_upper)
        upper = np.minimum(upper, m_max_upper)
    lo = np.exp(-beta * (e - mc_lower))
    hi = np.where(np.isinf(upper), 0.0, np.exp(-beta * (upper - mc_lower)))
    out: npt.NDArray[np.float64] = np.clip((lo - hi) / norm, 0.0, None)
    return out


@dataclass(frozen=True, slots=True)
class LogLikelihood:
    """The ETAS space-time log-likelihood at one parameter vector, with its three terms.

    ``total = observed_term - background_integral - triggering_integral``. A non-finite term
    raises rather than being rounded or clipped, so a persisted ``log_likelihood`` is either a
    real number or ``null`` with the reason recorded in the diagnostics.
    """

    total: float
    observed_term: float
    background_integral: float
    triggering_integral: float
    n_targets: int
    n_sources: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "log_likelihood": self.total,
            "observed_term": self.observed_term,
            "background_integral": self.background_integral,
            "triggering_integral": self.triggering_integral,
            "n_targets": self.n_targets,
            "n_sources": self.n_sources,
        }


def point_process_log_likelihood(calc: Any) -> LogLikelihood:
    """Space-time ETAS log-likelihood of the primary window, at ``calc.theta``.

    The package minimises the EM *expected complete-data* negative log-likelihood
    (:func:`etas.inversion.neg_log_likelihood`), which is the Q function of the current
    responsibilities and is not comparable across catalogues or cut-offs. What is computed here is
    the ordinary observed-data log-likelihood of the marked point process, built from exactly the
    conditional intensity the package's own expectation step uses (ADR-0046)::

        lambda(t, x, y) = mu + sum_{j: t_j < t} (xi_j + 1) g(t - t_j, r_ij, m_j)

        LL = sum_i (zeta_i + 1) log lambda(t_i, x_i, y_i)
             - mu * area * timewindow_length
             - sum_j (xi_j + 1) G_j

    where ``g`` is :func:`etas.inversion.triggering_kernel`, ``G_j`` is
    :func:`etas.inversion.expected_aftershocks` — the integral of ``g`` over the plane and over
    the part of the primary window that follows source ``j`` — and ``xi + 1`` / ``zeta + 1`` are
    the package's completeness corrections for triggering by unobserved events and for a
    target-time completeness above the reference magnitude (both are exactly 1 when ``mc`` is a
    constant equal to ``m_ref``, which is how this adapter configures every fit).

    Conditioning, stated because it bounds what the number may be compared with:

    * the sum runs over the **primary window** targets only (auxiliary events are sources, never
      targets), so the likelihood is conditional on the auxiliary catalogue;
    * the magnitude density is not included — this is the space-time likelihood at fixed
      ``beta``, so two fits are comparable by it only at the same ``mc``, ``delta_m``, region and
      window;
    * the integral term has no spatial boundary correction: ``G_j`` integrates the kernel over
      the whole plane while targets are counted inside the region. That is the package's own
      convention (its EM objective makes the same approximation), so the number is consistent
      with the parameters that were fitted, and it is not a free-boundary-corrected likelihood.

    Raises
    ------
    ValueError
        when the calculation has not run its expectation step, when ``free_background`` /
        ``free_productivity`` / an induced-seismicity term is in use (the intensity above is then
        not the model's), or when any term is not finite.
    """
    if calc.pij is None or calc.target_events is None or calc.source_events is None:
        msg = "log-likelihood needs a completed expectation step (calc.pij is unset)"
        raise ValueError(msg)
    if calc.free_background or calc.free_productivity or calc.bg_term is not None:
        msg = (
            "log-likelihood is defined here for the homogeneous-background ETAS this adapter "
            "fits; free_background/free_productivity/bg_term change the intensity"
        )
        raise ValueError(msg)

    theta_array = etas_inversion.parameter_dict2array(calc.theta)
    mu = 10.0 ** float(theta_array[0])
    mc_min = float(calc.m_ref) - float(calc.delta_m) / 2.0

    targets = calc.target_events
    pij = calc.pij
    # Exactly the expectation step's ``tot_rates``: mu plus the completeness-corrected kernel sum
    # over the sources that precede each target. Targets with no source within the Coppersmith
    # distance cut-off carry the background rate alone.
    triggered = (pij["gij"] * pij["xi_plus_1"]).groupby(level="target_id").sum()
    lam = mu + triggered.reindex(targets.index).fillna(0.0).to_numpy(dtype=np.float64)
    zeta_plus_1 = targets["zeta_plus_1"].to_numpy(dtype=np.float64)
    if np.any(lam <= 0.0):
        msg = "log-likelihood: conditional intensity is not positive at every target"
        raise ValueError(msg)
    observed_term = float(np.sum(zeta_plus_1 * np.log(lam)))

    background_integral = mu * float(calc.area) * float(calc.timewindow_length)

    sources = calc.source_events
    g_integral = np.asarray(
        etas_inversion.expected_aftershocks(
            [
                sources["source_magnitude"],
                sources["pos_source_to_start_time_distance"],
                sources["source_to_end_time_distance"],
            ],
            [theta_array[2:], mc_min],
        ),
        dtype=np.float64,
    )
    xi_plus_1 = np.asarray(
        etas_inversion.responsibility_factor(
            theta_array, calc.beta, sources["source_completeness_above_ref"]
        ),
        dtype=np.float64,
    )
    triggering_integral = float(np.sum(xi_plus_1 * g_integral))

    total = observed_term - background_integral - triggering_integral
    terms = (total, observed_term, background_integral, triggering_integral)
    if not all(math.isfinite(v) for v in terms):
        msg = f"log-likelihood is not finite: {terms}"
        raise ValueError(msg)
    return LogLikelihood(
        total=total,
        observed_term=observed_term,
        background_integral=background_integral,
        triggering_integral=triggering_integral,
        n_targets=len(targets),
        n_sources=len(sources),
    )


def cell_areas_km2(lattice: Lattice) -> npt.NDArray[np.float64]:
    """Spherical area of every lattice cell (radius = the package's Earth radius)."""
    origins = np.asarray(lattice.origins, dtype=np.float64)
    dh = math.radians(lattice.cell_size_deg)
    lat0 = np.radians(origins[:, 1])
    band = np.sin(lat0 + dh) - np.sin(lat0)
    out: npt.NDArray[np.float64] = EARTH_RADIUS_KM**2 * dh * band
    return out


def smoothed_background_mass(
    lattice: Lattice,
    lats: npt.ArrayLike,
    lons: npt.ArrayLike,
    weights: npt.ArrayLike,
    sigma_deg: float,
) -> npt.NDArray[np.float64]:
    """Per-cell probability mass of the package's background-location law, analytically.

    The package samples background locations from past background events (weights = their
    background probability) and adds N(0, sigma) jitter to latitude and longitude independently.
    The expectation of that procedure over a cell is the weighted sum of Gaussian masses over the
    cell's lon and lat extents. Masses are renormalised over the lattice, mirroring the package's
    rejection of samples that fall outside the polygon.
    """
    origins = np.asarray(lattice.origins, dtype=np.float64)
    dh = lattice.cell_size_deg
    lat = np.asarray(lats, dtype=np.float64)
    lon = np.asarray(lons, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    if w.sum() <= 0:
        msg = "background weights sum to zero"
        raise ValueError(msg)
    w = w / w.sum()
    mass = np.zeros(len(origins), dtype=np.float64)
    chunk = 512
    for k in range(0, len(w), chunk):
        la, lo, ww = lat[k : k + chunk], lon[k : k + chunk], w[k : k + chunk]
        lon_part = ndtr((origins[:, [0]] + dh - lo) / sigma_deg) - ndtr(
            (origins[:, [0]] - lo) / sigma_deg
        )
        lat_part = ndtr((origins[:, [1]] + dh - la) / sigma_deg) - ndtr(
            (origins[:, [1]] - la) / sigma_deg
        )
        mass += (lon_part * lat_part) @ ww
    total = mass.sum()
    if total <= 0:
        msg = "background mass over the lattice is zero"
        raise ValueError(msg)
    return mass / total


@dataclass(frozen=True)
class IssuanceState:
    """Everything the simulation needs at an issue time, with parameters fixed from the fit."""

    calc: Any  # etas.inversion.ETASParameterCalculation
    sources: pd.DataFrame  # history as simulation sources; every ``time`` < issue_time
    background_lats: npt.NDArray[np.float64]
    background_lons: npt.NDArray[np.float64]
    background_weights: npt.NDArray[np.float64]
    area_km2: float


class MizrahiETAS:
    """``ForecastModel`` implementation on top of ``etas.inversion`` / ``etas.simulation``.

    Parameters
    ----------
    auxiliary_years:
        Length of the auxiliary window at the start of the training catalogue. Auxiliary events
        act as triggering sources only; events after ``timewindow_start`` are also targets.
    coppersmith_multiplier:
        Pairs farther apart than this multiple of the Wells-Coppersmith subsurface rupture
        length are treated as uncorrelated (bounds the distance matrix).
    fixed_beta:
        Fix the Gutenberg-Richter ``beta`` (= b ln 10) instead of estimating it.
    gaussian_scale:
        Smoothing (degrees) of the background-location law (the package's ``gaussian_scale``).
    m_max:
        Optional upper magnitude bound for simulated events (``None`` = unbounded, as upstream).
    theta_0:
        EM starting point; defaults to :data:`DEFAULT_THETA_0` so fits are reproducible.
    max_iterations, max_seconds:
        Caps on the EM loop (the package's own ``invert`` has none and would run until its
        tolerance is met). Hitting a cap yields ``converged=False``; the fit is still persisted
        and ``forecast`` refuses to use it.
    """

    model_id: str = MODEL_ID
    model_version: str = _etas_version()

    def __init__(
        self,
        *,
        auxiliary_years: float = 2.0,
        coppersmith_multiplier: float = 100.0,
        fixed_beta: float | None = None,
        gaussian_scale: float = 0.1,
        m_max: float | None = None,
        theta_0: Mapping[str, float | None] | None = None,
        max_iterations: int = 200,
        max_seconds: float = 1800.0,
    ) -> None:
        if auxiliary_years <= 0:
            msg = "auxiliary_years must be positive"
            raise ValueError(msg)
        if max_iterations < 1 or max_seconds <= 0:
            msg = "max_iterations must be >= 1 and max_seconds positive"
            raise ValueError(msg)
        self.max_iterations = max_iterations
        self.max_seconds = max_seconds
        self.auxiliary_years = auxiliary_years
        self.coppersmith_multiplier = coppersmith_multiplier
        self.fixed_beta = fixed_beta
        self.gaussian_scale = gaussian_scale
        self.m_max = m_max
        self.theta_0 = dict(theta_0) if theta_0 is not None else dict(DEFAULT_THETA_0)
        self._fit: FitResult | None = None
        self._region: Region | None = None
        self._lattice: Lattice | None = None

    # ------------------------------------------------------------------ state
    @property
    def fit_result(self) -> FitResult | None:
        return self._fit

    @property
    def region(self) -> Region | None:
        return self._region

    def load_fit(self, fit: FitResult, region: Region) -> None:
        """Make a persisted fit the one the next ``forecast`` call uses."""
        if fit.model_id != self.model_id:
            msg = f"fit belongs to model {fit.model_id!r}, not {self.model_id!r}"
            raise ValueError(msg)
        if fit.region_id != region.id:
            msg = f"fit is for region {fit.region_id!r}, not {region.id!r}"
            raise ValueError(msg)
        missing = [k for k in PARAMETER_KEYS if k not in fit.parameters]
        if missing:
            msg = f"fit is missing parameters {missing}"
            raise ValueError(msg)
        for key in ("auxiliary_start", "timewindow_start", "delta_m", "coppersmith_multiplier"):
            if key not in fit.diagnostics:
                msg = f"fit diagnostics lack {key!r}; cannot rebuild the issuance configuration"
                raise ValueError(msg)
        self._fit = fit
        self._region = region
        self._lattice = build_lattice(region)

    def parameter_snapshot(self) -> dict[str, Any]:
        if self._fit is None:
            return {}
        return dict(self._fit.parameters)

    # ------------------------------------------------------------------ fit
    def fit(
        self,
        catalog: Catalog,
        region: Region,
        cutoff: datetime,
        *,
        mc: float | None = None,
    ) -> FitResult:
        """Fit on ``origin_time < cutoff`` earthquakes with ``mw >= mc`` inside the region."""
        mc_value, mc_source = self._resolve_mc(catalog, region, mc)
        training = self.training_slice(catalog, region, cutoff, mc_value)
        assert_all_before(training, cutoff, what="fit training catalogue")
        if len(training) == 0:
            msg = "no training events after filtering; refusing to fit"
            raise ValueError(msg)

        start = training.min_origin_time()
        latest = training.max_origin_time()
        if start is None or latest is None:  # pragma: no cover - guarded by len check
            raise ValueError("empty training catalogue")
        auxiliary_start = start
        timewindow_start = auxiliary_start + timedelta(days=365.25 * self.auxiliary_years)
        if timewindow_start >= cutoff:
            msg = (
                f"auxiliary window of {self.auxiliary_years} y leaves no primary window before "
                f"{cutoff.isoformat()} (training starts {auxiliary_start.isoformat()})"
            )
            raise ValueError(msg)

        metadata = self._metadata(
            training,
            region,
            mc_value,
            auxiliary_start=auxiliary_start,
            timewindow_start=timewindow_start,
            timewindow_end=cutoff,
            name=f"{self.model_id}:{region.id}:{cutoff:%Y%m%dT%H%M%SZ}",
        )
        metadata["theta_0"] = dict(self.theta_0)
        if self.fixed_beta is not None:
            metadata["beta"] = float(self.fixed_beta)

        t0 = time.perf_counter()
        calc = etas_inversion.ETASParameterCalculation(metadata)
        calc.prepare()
        em_converged, em_reason = self._invert_capped(calc)
        theta = calc.theta
        try:
            loglik: LogLikelihood | None = point_process_log_likelihood(calc)
            loglik_note = LL_NOTE
        except (ValueError, KeyError, FloatingPointError) as exc:
            loglik, loglik_note = None, f"log-likelihood not computed: {exc}"
            log.warning("ETAS log-likelihood not computed for %s: %s", region.id, exc)
        runtime_s = time.perf_counter() - t0

        parameters = self._parameters_from(theta, calc.beta)
        finite = all(math.isfinite(v) for v in parameters.values())
        converged = em_converged and finite
        if not finite:
            em_reason = "non-finite parameter(s)"
        at_bound = sorted(
            k
            for k, (lo, hi) in ETAS_RANGES.items()
            if math.isclose(parameters[k], lo, abs_tol=1e-6)
            or math.isclose(parameters[k], hi, abs_tol=1e-6)
        )
        branching: float | None
        branching_note: str | None = None
        try:
            branching = _to_float(
                etas_inversion.branching_ratio(
                    etas_inversion.parameter_dict2array(theta), calc.beta
                )
            )
        except (AssertionError, ValueError, ZeroDivisionError) as exc:
            branching = None
            branching_note = f"branching ratio undefined: {exc}"

        diagnostics: dict[str, Any] = {
            "iterations": int(calc.i),
            "em_tolerance": EM_TOLERANCE,
            "max_iterations": self.max_iterations,
            "max_seconds": self.max_seconds,
            "converged_reason": em_reason,
            "n_target_events": len(calc.target_events),
            "n_source_events": len(calc.source_events),
            "n_hat_background": _to_float(calc.n_hat),
            "branching_ratio": branching,
            "branching_ratio_note": branching_note,
            "b_value": parameters["beta"] / math.log(10.0),
            "beta_fixed": self.fixed_beta is not None,
            "mc": mc_value,
            "mc_source": mc_source,
            "delta_m": region.magnitude_bin_width,
            "auxiliary_start": auxiliary_start.isoformat(),
            "timewindow_start": timewindow_start.isoformat(),
            "timewindow_end": cutoff.isoformat(),
            "training_max_origin_time": latest.isoformat(),
            "auxiliary_years": self.auxiliary_years,
            "coppersmith_multiplier": self.coppersmith_multiplier,
            "theta_0": dict(self.theta_0),
            "area_km2": _to_float(calc.area),
            "runtime_s": round(runtime_s, 3),
            "at_bound": at_bound,
            "ranges": {k: list(v) for k, v in ETAS_RANGES.items()},
            "log_likelihood_note": loglik_note,
            "log_likelihood_terms": None if loglik is None else loglik.as_dict(),
            "etas_commit": ETAS_COMMIT,
        }
        result = FitResult(
            model_id=self.model_id,
            model_version=self.model_version,
            region_id=region.id,
            fit_cutoff=cutoff,
            training_start=auxiliary_start,
            training_catalog_hash=training.event_hash(),
            n_events=len(training),
            mc=mc_value,
            parameters=parameters,
            parameter_snapshot_hash=snapshot_hash(parameters),
            log_likelihood=None if loglik is None else loglik.total,
            diagnostics=diagnostics,
            converged=converged,
            fitted_at=utc_now(),
            notes=None if converged else f"not converged ({em_reason}): fit is not usable",
        )
        self.load_fit(result, region)
        return result

    def _invert_capped(self, calc: Any) -> tuple[bool, str]:
        """The package's EM loop (``ETASParameterCalculation.invert``) with iteration/time caps.

        Mirrors upstream step for step (expectation step, parameter optimisation, summed absolute
        change < tolerance, final expectation step) but stops at ``max_iterations`` or
        ``max_seconds`` instead of running until it converges. ``free_productivity`` is not used.
        """
        theta_old = etas_inversion.parameter_dict2array(calc.theta_0)
        mc_min = calc.m_ref - calc.delta_m / 2.0
        start = time.perf_counter()
        i = 0
        converged, reason = False, ""
        while True:
            calc.pij, calc.target_events, calc.source_events, calc.n_hat, calc.i_hat = (
                calc.expectation_step(theta_old, mc_min)
            )
            theta_new = calc.optimize_parameters(theta_old)
            diff = etas_inversion.calc_diff_to_before(theta_old, theta_new)
            theta_old = theta_new
            i += 1
            if diff < EM_TOLERANCE:
                converged, reason = True, f"tolerance {EM_TOLERANCE} reached"
                break
            if i >= self.max_iterations:
                reason = f"iteration cap {self.max_iterations} hit"
                break
            if time.perf_counter() - start > self.max_seconds:
                reason = f"wall-clock cap {self.max_seconds}s hit"
                break
        calc.theta = etas_inversion.parameter_array2dict(theta_old)
        calc.i = i
        calc.pij, calc.target_events, calc.source_events, calc.n_hat, calc.i_hat = (
            calc.expectation_step(theta_old, mc_min)
        )
        calc.inversion_done = True
        return converged, reason

    # ------------------------------------------------------------------ forecast
    def forecast(
        self,
        history: Catalog,
        issue_time: datetime,
        horizon: timedelta,
        *,
        n_simulations: int = 100,
        seed: int | None = None,
    ) -> ForecastGrid:
        """Issue expected counts for ``[issue_time, issue_time + horizon)`` from the loaded fit.

        ``history`` must contain earthquakes only, all with ``mw >= mc`` and
        ``origin_time < issue_time``; anything else is refused, not filtered. Events outside the
        region polygon or depth range are dropped (the region defines the process).

        Expected counts are the expectation under the fitted model (ADR-0018): the triggered
        component is the mean over ``n_simulations`` stochastic continuations of the history; the
        background component and the magnitude distribution are analytic. With ``seed`` set the
        result is reproducible (the package draws from numpy's global RNG, which is seeded here).
        """
        fit, region, lattice = self._require_fit()
        if n_simulations < 1:
            msg = "n_simulations must be >= 1"
            raise ValueError(msg)
        if horizon <= timedelta(0):
            msg = "horizon must be positive"
            raise ValueError(msg)
        assert_issue_after_fit(issue_time, fit.fit_cutoff)
        assert_all_before(history, issue_time, what="forecast history")
        self._check_history_contents(history, fit.mc)
        spatial = self._inside_region(history, region)

        state = self.issuance_state(spatial, issue_time)
        sim = etas_sim
        # The package works in (lat, lon) order; its polygon must be built the same way.
        polygon_lat_lon = Polygon(shape_coords_lat_lon(region))
        delta_m = region.magnitude_bin_width
        mc_lower = float(state.calc.m_ref) - delta_m / 2.0
        start_naive = _naive_utc(issue_time)
        end_naive = _naive_utc(issue_time + horizon)
        horizon_days = horizon.total_seconds() / 86400.0

        triggered = np.zeros(lattice.n_cells, dtype=np.float64)
        n_simulated = 0
        dropped_outside_cells = 0
        if seed is not None:
            np.random.seed(seed)  # the package draws from numpy's global legacy RNG
        for _ in range(n_simulations):
            cont = sim.simulate_catalog_continuation(
                state.sources,
                auxiliary_start=state.calc.auxiliary_start,
                auxiliary_end=start_naive,
                polygon=polygon_lat_lon,
                simulation_end=end_naive,
                parameters=state.calc.theta,
                mc=mc_lower,
                m_max=(self.m_max + delta_m / 2.0) if self.m_max is not None else None,
                beta_main=state.calc.beta,
                background_probs=None,  # uniform placement; see ADR-0018 for why
                filter_polygon=False,
                approx_times=False,
            )
            if len(cont) == 0:
                continue
            cont = cont[
                (cont["time"] >= start_naive)
                & (cont["time"] < end_naive)
                & (cont["is_background"] == False)  # noqa: E712 - pandas mask
            ]
            if len(cont) == 0:
                continue
            cells = lattice.cell_indices(cont["longitude"].to_numpy(), cont["latitude"].to_numpy())
            keep = cells >= 0
            dropped_outside_cells += int(np.sum(~keep))
            n_simulated += len(cont)
            np.add.at(triggered, cells[keep], 1.0)
        triggered /= float(n_simulations)

        mu = 10.0 ** fit.parameters["log10_mu"]
        background_total = mu * state.area_km2 * horizon_days
        background = background_total * smoothed_background_mass(
            lattice,
            state.background_lats,
            state.background_lons,
            state.background_weights,
            self.gaussian_scale,
        )
        edges = region.magnitude_bin_edges()
        pmf = gr_bin_probabilities(
            fit.parameters["beta"],
            mc_lower,
            edges,
            (self.m_max + delta_m / 2.0) if self.m_max is not None else None,
        )
        expected = np.outer(triggered + background, pmf)
        expected = np.where(np.isfinite(expected) & (expected > 0.0), expected, 0.0)

        notes = (
            f"triggered: {n_simulated} simulated events (m >= {mc_lower:.2f}) over "
            f"{n_simulations} continuations, {dropped_outside_cells} outside every cell dropped; "
            f"background: {background_total:.4f} expected events (m >= {mc_lower:.2f}) placed by "
            f"the smoothed law over {len(state.background_weights)} past background events; "
            f"magnitudes: analytic GR with beta={fit.parameters['beta']:.4f}; "
            f"history: {len(spatial)} events inside the region; seed={seed}"
        )
        return ForecastGrid(
            id=ForecastGrid.make_id(self.model_id, region.id, issue_time, horizon),
            region_id=region.id,
            model_id=self.model_id,
            model_version=self.model_version,
            parameter_snapshot_hash=fit.parameter_snapshot_hash,
            fit_cutoff=fit.fit_cutoff,
            training_catalog_hash=fit.training_catalog_hash,
            issue_time=issue_time,
            horizon=horizon,
            cell_size_deg=region.cell_size_deg,
            cell_origins=lattice.origins,
            magnitude_bin_edges=edges,
            magnitude_bin_width=delta_m,
            expected_counts=tuple(tuple(float(v) for v in row) for row in expected),
            n_simulations=n_simulations,
            created_at=utc_now(),
            notes=notes,
        )

    # ------------------------------------------------------------------ log-likelihood
    def log_likelihood(self, catalog: Catalog) -> LogLikelihood:
        """Score the loaded fit on its own training window again, without refitting.

        The point is backfilling: a fit persisted before the likelihood existed, or one whose
        computation failed, can be scored from the same catalogue without moving a parameter.
        The rebuilt window is taken from the fit's own diagnostics, and the training slice must
        hash to ``FitResult.training_catalog_hash`` — otherwise the catalogue is not the one that
        produced the fit and the number would describe a different model, so it is refused.

        Leakage: the reconstructed window ends at ``fit.fit_cutoff`` and the slice is asserted to
        end strictly before it, exactly as in :meth:`fit`.
        """
        if self._fit is None or self._region is None:
            msg = "no fit loaded: call fit() or load_fit() first"
            raise RuntimeError(msg)
        fit, region = self._fit, self._region
        training = self.training_slice(catalog, region, fit.fit_cutoff, fit.mc)
        assert_all_before(training, fit.fit_cutoff, what="log-likelihood training catalogue")
        if training.event_hash() != fit.training_catalog_hash:
            msg = (
                "catalogue does not reproduce the fit's training slice "
                f"({training.event_hash()[:12]} != {fit.training_catalog_hash[:12]}); "
                "refusing to score this fit on a different catalogue"
            )
            raise ValueError(msg)
        theta: dict[str, Any] = {k: fit.parameters[k] for k in THETA_KEYS}
        theta["log10_iota"] = None
        metadata = self._metadata(
            training,
            region,
            fit.mc,
            auxiliary_start=datetime.fromisoformat(fit.diagnostics["auxiliary_start"]),
            timewindow_start=datetime.fromisoformat(fit.diagnostics["timewindow_start"]),
            timewindow_end=fit.fit_cutoff,
            name=f"{self.model_id}:{region.id}:loglik:{fit.fit_cutoff:%Y%m%dT%H%M%SZ}",
        )
        metadata["beta"] = float(fit.parameters["beta"])
        metadata["theta_0"] = theta
        metadata["coppersmith_multiplier"] = float(
            fit.diagnostics.get("coppersmith_multiplier", self.coppersmith_multiplier)
        )
        calc = etas_inversion.ETASParameterCalculation(metadata)
        calc.prepare()
        calc.theta = theta
        calc.pij, calc.target_events, calc.source_events, calc.n_hat, calc.i_hat = (
            calc.expectation_step(
                etas_inversion.parameter_dict2array(theta), calc.m_ref - calc.delta_m / 2.0
            )
        )
        calc.inversion_done = True
        return point_process_log_likelihood(calc)

    def issuance_state(self, history: Catalog, issue_time: datetime) -> IssuanceState:
        """Rebuild the package state at ``issue_time`` with parameters fixed from the fit.

        Public so tests can prove that no event with ``origin_time >= issue_time`` is present in
        the simulation's source catalogue. Mirrors ``ETASSimulation.prepare`` without ``invert``:
        one expectation step with the stored theta yields the background probabilities that
        define the background-location law.
        """
        fit, region, _ = self._require_fit()
        assert_all_before(history, issue_time, what="issuance history")
        theta: dict[str, Any] = {k: fit.parameters[k] for k in THETA_KEYS}
        theta["log10_iota"] = None
        metadata = self._metadata(
            history,
            region,
            fit.mc,
            auxiliary_start=datetime.fromisoformat(fit.diagnostics["auxiliary_start"]),
            timewindow_start=datetime.fromisoformat(fit.diagnostics["timewindow_start"]),
            timewindow_end=issue_time,
            name=f"{self.model_id}:{region.id}:issue:{issue_time:%Y%m%dT%H%M%SZ}",
        )
        metadata["beta"] = float(fit.parameters["beta"])
        metadata["theta_0"] = theta
        calc = etas_inversion.ETASParameterCalculation(metadata)
        calc.prepare()
        calc.theta = theta
        theta_array = etas_inversion.parameter_dict2array(theta)
        calc.pij, calc.target_events, calc.source_events, calc.n_hat, calc.i_hat = (
            calc.expectation_step(theta_array, calc.m_ref - calc.delta_m / 2.0)
        )
        calc.inversion_done = True

        sources = calc.source_events.copy()
        sources["xi_plus_1"] = 1
        sources = pd.merge(
            sources,
            calc.catalog[["latitude", "longitude", "time", "magnitude"]],
            left_index=True,
            right_index=True,
            how="left",
        )
        if len(sources) != len(calc.source_events):  # pragma: no cover - upstream invariant
            msg = "source merge changed the number of rows"
            raise RuntimeError(msg)
        if len(sources) and _aware(sources["time"].max()) >= issue_time:
            msg = "leakage: simulation source catalogue reaches the issue time"
            raise LeakageError(msg)

        targets = calc.target_events.query("magnitude >= @calc.m_ref - @calc.delta_m / 2")
        poly = region_polygon(region)
        inside = np.fromiter(
            (
                poly.covers(Point(lon, lat))
                for lon, lat in zip(targets["longitude"], targets["latitude"], strict=True)
            ),
            dtype=bool,
            count=len(targets),
        )
        targets = targets[inside]
        if len(targets) == 0:
            msg = "no target events in the primary window; background-location law undefined"
            raise ValueError(msg)
        weights = targets["P_background"] * (targets["zeta_plus_1"] / targets["zeta_plus_1"].max())
        return IssuanceState(
            calc=calc,
            sources=sources,
            background_lats=targets["latitude"].to_numpy(dtype=np.float64),
            background_lons=targets["longitude"].to_numpy(dtype=np.float64),
            background_weights=weights.to_numpy(dtype=np.float64),
            area_km2=_to_float(calc.area),
        )

    # ------------------------------------------------------------------ internals
    def _require_fit(self) -> tuple[FitResult, Region, Lattice]:
        if self._fit is None or self._region is None or self._lattice is None:
            msg = "no fit loaded: call fit() or load_fit() first"
            raise RuntimeError(msg)
        if self._fit.converged is False:
            msg = "the loaded fit did not converge and must not be used"
            raise RuntimeError(msg)
        return self._fit, self._region, self._lattice

    @staticmethod
    def _resolve_mc(catalog: Catalog, region: Region, mc: float | None) -> tuple[float, str]:
        if region.mc is not None:
            return float(region.mc.mc), f"region.mc ({region.mc.method})"
        preferred = catalog.preferred_mc()
        if preferred is not None:
            return float(preferred.mc), f"catalog.preferred_mc ({preferred.method})"
        if mc is not None:
            return float(mc), "explicit mc kwarg"
        msg = (
            "no magnitude of completeness: region.mc is unset, the catalogue carries no "
            "completeness estimate and no explicit mc= was given"
        )
        raise ValueError(msg)

    @staticmethod
    def _inside_region(catalog: Catalog, region: Region) -> Catalog:
        poly = region_polygon(region)
        kept = [
            e
            for e in catalog.events
            if poly.covers(Point(e.longitude, e.latitude))
            and (e.depth_km is None or region.depth_min_km <= e.depth_km <= region.depth_max_km)
        ]
        return catalog.model_copy(update={"events": tuple(kept), "id": f"{catalog.id}/in-region"})

    @classmethod
    def training_slice(
        cls, catalog: Catalog, region: Region, cutoff: datetime, mc: float
    ) -> Catalog:
        """Exactly the events a fit with these inputs uses (hash = ``training_catalog_hash``)."""
        return cls._inside_region(catalog.earthquakes().before(cutoff).at_least(mc), region)

    @staticmethod
    def _check_history_contents(history: Catalog, mc: float) -> None:
        bad_type = [e.id for e in history.events if e.event_type != "earthquake"]
        if bad_type:
            msg = f"history must be earthquakes only; found {len(bad_type)} other entries"
            raise ValueError(msg)
        no_mw = [e.id for e in history.events if e.mw is None]
        if no_mw:
            msg = f"history has {len(no_mw)} event(s) without mw; filter with at_least(mc) first"
            raise ValueError(msg)
        below = [e.id for e in history.events if e.mw is not None and e.mw < mc]
        if below:
            msg = f"history has {len(below)} event(s) below mc={mc}; filter with at_least(mc)"
            raise ValueError(msg)

    @staticmethod
    def _frame(catalog: Catalog) -> pd.DataFrame:
        rows = [
            (e.id, e.latitude, e.longitude, pd.Timestamp(_naive_utc(e.origin_time)), e.mw)
            for e in catalog.events
        ]
        df = pd.DataFrame(rows, columns=["id", "latitude", "longitude", "time", "magnitude"])
        return df.set_index("id")

    def _metadata(
        self,
        catalog: Catalog,
        region: Region,
        mc: float,
        *,
        auxiliary_start: datetime,
        timewindow_start: datetime,
        timewindow_end: datetime,
        name: str,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "catalog": self._frame(catalog),
            "auxiliary_start": _naive_utc(auxiliary_start),
            "timewindow_start": _naive_utc(timewindow_start),
            "timewindow_end": _naive_utc(timewindow_end),
            "mc": mc,
            "delta_m": region.magnitude_bin_width,
            "coppersmith_multiplier": self.coppersmith_multiplier,
            "shape_coords": shape_coords_lat_lon(region),
        }

    @staticmethod
    def _parameters_from(theta: Mapping[str, Any], beta: Any) -> dict[str, float]:
        params = {k: _to_float(theta[k]) for k in THETA_KEYS}
        params["beta"] = _to_float(beta)
        return params


# ---------------------------------------------------------------------- persistence
def fit_dir(baselines_dir: Path, region_id: str) -> Path:
    return Path(baselines_dir) / "etas" / region_id


def archive_dir(baselines_dir: Path, region_id: str, cutoff: datetime) -> Path:
    """Per-cutoff archive: ``baselines/etas/<region>/fits/<YYYYMMDDTHHMMSSZ>/``."""
    return fit_dir(baselines_dir, region_id) / "fits" / f"{cutoff:%Y%m%dT%H%M%SZ}"


def save_fit(fit: FitResult, baselines_dir: Path, *, canonical: bool = True) -> Path:
    """Write ``fit_result.json``, ``parameters.json`` and ``diagnostics.json``; return the dir.

    Every fit is archived under ``fits/<cutoff>/``. A **canonical** fit is additionally written at
    the top of ``baselines/etas/<region>/``, which is what :func:`load_fit` reads and what the
    ``fit_etas`` DVC stage declares as its output.

    A schedule's refits pass ``canonical=False``: they are schedule state, not the declared
    baseline. Writing them at the top level would replace the artefact that the DVC stage
    command produces, so the published baseline could no longer be reproduced from its own
    stage, and a published parameter table would silently stop matching the file it cites.
    The schedule uses the returned :class:`FitResult` directly, so nothing depends on a refit
    being at the top level.
    """
    out = fit_dir(baselines_dir, fit.region_id)
    out.mkdir(parents=True, exist_ok=True)
    previous: dict[str, str | None] = {
        name: (out / name).read_text(encoding="utf-8") if (out / name).exists() else None
        for name in (FIT_RESULT_FILE, PARAMETERS_FILE, DIAGNOSTICS_FILE)
    }
    (out / FIT_RESULT_FILE).write_text(
        json.dumps(fit.model_dump(mode="json"), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / PARAMETERS_FILE).write_text(
        json.dumps(
            {
                "model_id": fit.model_id,
                "model_version": fit.model_version,
                "region_id": fit.region_id,
                "fit_cutoff": fit.fit_cutoff.isoformat(),
                "parameters": fit.parameters,
                "parameter_snapshot_hash": fit.parameter_snapshot_hash,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / DIAGNOSTICS_FILE).write_text(
        json.dumps(fit.diagnostics, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    archive = archive_dir(baselines_dir, fit.region_id, fit.fit_cutoff)
    archive.mkdir(parents=True, exist_ok=True)
    for name in (FIT_RESULT_FILE, PARAMETERS_FILE, DIAGNOSTICS_FILE):
        (archive / name).write_text((out / name).read_text(encoding="utf-8"), encoding="utf-8")
    if not canonical:
        # restore the declared baseline: only the archive keeps this refit
        for name in (FIT_RESULT_FILE, PARAMETERS_FILE, DIAGNOSTICS_FILE):
            kept = previous[name]
            if kept is None:
                (out / name).unlink(missing_ok=True)
            else:
                (out / name).write_text(kept, encoding="utf-8")
    return out


def load_fit(baselines_dir: Path, region_id: str) -> FitResult:
    path = fit_dir(baselines_dir, region_id) / FIT_RESULT_FILE
    if not path.exists():
        msg = f"no persisted fit at {path}; run `rupture forecast fit` first"
        raise FileNotFoundError(msg)
    return FitResult.model_validate_json(path.read_text(encoding="utf-8"))
