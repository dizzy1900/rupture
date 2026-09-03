"""``ForecastModel`` implementation for the neural temporal point process, plus its persistence.

This is the seam between the torch model and the rest of rupture. It does four things and nothing
else: it fits on events strictly before a cutoff, it issues a :class:`~rupture.domain.ForecastGrid`
of expected counts on the **same lattice and magnitude bins as the ETAS baseline**, it hashes the
trained weights into the parameter snapshot so the protocol's constancy check (§ 7 rule 4) has
something to check, and it persists a fit in the layout ``baselines/etas/<region>/`` already uses.

rupture does not predict earthquakes. Every number leaving this module is an expected count over a
window, on a grid, with the uncertainty that implies.
"""

from __future__ import annotations

import copy
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import torch
from shapely.geometry import Point

from rupture.adapters.forecasting.etas_mizrahi import cell_areas_km2, gr_bin_probabilities
from rupture.adapters.forecasting.grid import Lattice, build_lattice, region_polygon
from rupture.adapters.forecasting.leakage import assert_all_before, assert_issue_after_fit
from rupture.domain import (
    Catalog,
    FitResult,
    ForecastGrid,
    Region,
    sha256_hex,
    snapshot_hash,
    utc_now,
)
from rupture.models.challengers.ntpp.model import (
    FeatureBuilder,
    LogLikelihood,
    NeuralKernelHawkes,
    NTPPConfig,
    sequence_tensors,
)
from rupture.models.challengers.ntpp.simulate import (
    SimulationDiagnostics,
    history_batch,
    simulate_window,
)
from rupture.models.data import (
    EventSequence,
    Projection,
    Standardiser,
    build_sequence,
    causal_slice,
)

_F8 = npt.NDArray[np.float64]

MODEL_ID = "ntpp-neural-hawkes"
NTPP_VERSION = "0.1.0"

FIT_RESULT_FILE = "fit_result.json"
PARAMETERS_FILE = "parameters.json"
DIAGNOSTICS_FILE = "diagnostics.json"
WEIGHTS_FILE = "weights.json"

# Scalar learned parameters that are meaningful on their own and worth publishing as numbers.
SCALAR_KEYS: tuple[str, ...] = (
    "log_mu",
    "k0",
    "alpha",
    "beta",
    "log_beta",
    "branching_ratio",
    "alpha_raw",
    "branch_raw",
)
# The trained weights enter the snapshot as eight exactly-representable 32-bit chunks of a
# SHA-256 digest. ``FitResult.parameters`` is ``dict[str, float]``, so the digest cannot be stored
# as text there; splitting it into 8-hex-digit pieces keeps it exact and reversible.
DIGEST_CHUNKS = 8
DIGEST_CHUNK_HEX = 8


def digest_to_floats(digest: str, prefix: str = "snapshot") -> dict[str, float]:
    """Split a 64-character hex digest into ``DIGEST_CHUNKS`` exactly representable floats."""
    if len(digest) != DIGEST_CHUNKS * DIGEST_CHUNK_HEX:
        msg = f"expected a {DIGEST_CHUNKS * DIGEST_CHUNK_HEX}-character hex digest"
        raise ValueError(msg)
    return {
        f"{prefix}_{i}": float(int(digest[i * DIGEST_CHUNK_HEX : (i + 1) * DIGEST_CHUNK_HEX], 16))
        for i in range(DIGEST_CHUNKS)
    }


def floats_to_digest(parameters: dict[str, float], prefix: str = "snapshot") -> str:
    """Inverse of :func:`digest_to_floats`; used to verify a persisted fit against its weights."""
    return "".join(
        f"{int(parameters[f'{prefix}_{i}']):0{DIGEST_CHUNK_HEX}x}" for i in range(DIGEST_CHUNKS)
    )


def snapshot_digest(config: NTPPConfig, net: NeuralKernelHawkes, features: FeatureBuilder) -> str:
    """SHA-256 over the frozen configuration, the trained weights and the feature statistics.

    All three matter. The weights alone would miss a retuned hyperparameter that happened to land
    on the same optimum; the configuration alone would miss a retrain; the feature statistics alone
    would miss both. Any of the three changing changes this digest, and so changes the fit's
    ``parameter_snapshot_hash`` — which is what the protocol's constancy check watches.
    """
    return sha256_hex(
        "\n".join(
            [
                f"config={config.config_hash()}",
                f"weights={net.weight_digest()}",
                f"features={features.standardiser.digest()}",
                f"clip={features.clip:.6f}",
                f"depth_fill={features.depth_fill:.12e}",
                f"mc={features.mc:.6f}",
            ]
        )
    )


class NeuralTPPForecaster:
    """The C1a challenger: a neural spatio-temporal point process behind ``ForecastModel``.

    Parameters
    ----------
    config:
        Architecture and optimiser settings. Frozen and hashed before any test window is scored
        (ADR-0022 decision 4); :mod:`.train` is what chooses it, on a validation window only.
    auxiliary_years:
        Length of the burn-in window at the start of the training catalogue. Events there
        condition the intensity but are not scored, matching the ``etas`` package and
        EarthquakeNPP's ETAS configuration.
    convergence_tol, patience:
        Optimisation stops when the best log-likelihood has not improved by ``convergence_tol``
        nats for ``patience`` consecutive epochs. The default of 0.01 nats is roughly five parts
        per million of a typical objective here; tightening it to 0.001 costs three times the
        epochs and moves the per-event log-likelihood by under 0.04 nats. Hitting the epoch cap
        instead yields ``converged=False``, and :meth:`forecast` then refuses the fit, exactly as
        the ETAS adapter does.
    """

    model_id: str = MODEL_ID
    model_version: str = f"ntpp-{NTPP_VERSION}+torch-{torch.__version__.split('+')[0]}"

    def __init__(
        self,
        config: NTPPConfig | None = None,
        *,
        auxiliary_years: float = 0.5,
        convergence_tol: float = 1e-2,
        patience: int = 50,
    ) -> None:
        if auxiliary_years <= 0:
            msg = "auxiliary_years must be positive"
            raise ValueError(msg)
        self.config = config or NTPPConfig()
        self.auxiliary_years = auxiliary_years
        self.convergence_tol = convergence_tol
        self.patience = patience
        self._fit: FitResult | None = None
        self._region: Region | None = None
        self._lattice: Lattice | None = None
        self._net: NeuralKernelHawkes | None = None
        self._features: FeatureBuilder | None = None
        self._projection: Projection | None = None
        self._epoch: datetime | None = None
        self._depth_pool: _F8 = np.zeros(0, dtype=np.float64)

    # ------------------------------------------------------------------ state
    @property
    def fit_result(self) -> FitResult | None:
        return self._fit

    @property
    def region(self) -> Region | None:
        return self._region

    @property
    def net(self) -> NeuralKernelHawkes | None:
        return self._net

    @property
    def features(self) -> FeatureBuilder | None:
        """The fitted feature builder: mc, the depth fill value and the standardiser."""
        return self._features

    @property
    def projection(self) -> Projection | None:
        """The projection the fit used; a later sequence must be built with the same one."""
        return self._projection

    @property
    def epoch(self) -> datetime | None:
        """The time origin the fit used; a later sequence must share it."""
        return self._epoch

    def parameter_snapshot(self) -> dict[str, Any]:
        """The parameters the next :meth:`forecast` call would use; hashed into every grid.

        Contains the interpretable scalars *and* eight floats carrying the SHA-256 digest of the
        configuration, the trained weights and the normalisation statistics together. Change any
        weight, retune any hyperparameter, or refit the standardiser, and this dictionary changes,
        so the schedule's snapshot-constancy check catches it.
        """
        if self._fit is None:
            return {}
        return dict(self._fit.parameters)

    def snapshot_digest(self) -> str:
        """:func:`snapshot_digest` for the currently loaded fit."""
        if self._net is None or self._features is None:
            msg = "no fit loaded"
            raise RuntimeError(msg)
        return snapshot_digest(self.config, self._net, self._features)

    # ------------------------------------------------------------------ fit
    @staticmethod
    def resolve_mc(catalog: Catalog, region: Region, mc: float | None) -> tuple[float, str]:
        """Same precedence as the ETAS adapter: region record, then catalogue, then the argument."""
        if region.mc is not None:
            return float(region.mc.mc), f"region.mc ({region.mc.method})"
        preferred = catalog.preferred_mc()
        if preferred is not None:
            return float(preferred.mc), f"catalog.preferred_mc ({preferred.method})"
        if mc is not None:
            return float(mc), "explicit mc argument"
        msg = (
            "no magnitude of completeness: region.mc is unset, the catalogue carries no "
            "completeness estimate and no explicit mc= was given"
        )
        raise ValueError(msg)

    @staticmethod
    def training_slice(catalog: Catalog, region: Region, cutoff: datetime, mc: float) -> Catalog:
        """Exactly the events a fit uses; the hash of this slice is ``training_catalog_hash``."""
        return causal_slice(catalog, region, cutoff, mc)

    def fit(
        self,
        catalog: Catalog,
        region: Region,
        cutoff: datetime,
        *,
        mc: float | None = None,
        epoch: datetime | None = None,
    ) -> FitResult:
        """Fit by maximum likelihood on earthquakes with ``origin_time < cutoff``.

        The likelihood is evaluated over ``[training_start + auxiliary_years, cutoff)``; events in
        the auxiliary window condition the intensity without being scored.
        """
        mc_value, mc_source = self.resolve_mc(catalog, region, mc)
        training = self.training_slice(catalog, region, cutoff, mc_value)
        assert_all_before(training, cutoff, what="ntpp fit training catalogue")
        if len(training) < 2:
            msg = f"only {len(training)} training event(s) after filtering; refusing to fit"
            raise ValueError(msg)

        sequence = build_sequence(training, region, cutoff, mc=mc_value, epoch=epoch)
        auxiliary_start = sequence.spec.epoch
        window_start = auxiliary_start + timedelta(days=365.25 * self.auxiliary_years)
        if window_start >= cutoff:
            msg = (
                f"auxiliary window of {self.auxiliary_years} y leaves no primary window before "
                f"{cutoff.isoformat()} (training starts {auxiliary_start.isoformat()})"
            )
            raise ValueError(msg)
        n_scored = int(np.count_nonzero(sequence.t >= sequence.days_of(window_start)))
        if n_scored < 2:
            msg = (
                f"only {n_scored} event(s) fall in the scored window "
                f"[{window_start.isoformat()}, {cutoff.isoformat()}); shorten auxiliary_years"
            )
            raise ValueError(msg)

        features = self._build_features(sequence, cutoff, mc_value)
        net = self._build_net(sequence, mc_value, region)
        tensors = sequence_tensors(sequence, features)
        window = {
            "window_start": sequence.days_of(window_start),
            "window_end": sequence.days_of(cutoff),
        }
        started = time.perf_counter()
        history, converged, reason = self._optimise(net, tensors, window)
        runtime_s = time.perf_counter() - started
        ll = net.log_likelihood(**tensors, **window)

        self._net = net
        self._features = features
        self._projection = sequence.spec.projection
        self._epoch = sequence.spec.epoch
        self._region = region
        self._lattice = build_lattice(region)
        self._depth_pool = sequence.depth_km[np.isfinite(sequence.depth_km)]

        scalars = self._scalars(net)
        converged = converged and all(np.isfinite(v) for v in scalars.values())
        parameters = {**scalars, **digest_to_floats(snapshot_digest(self.config, net, features))}
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
            log_likelihood=ll.total,
            diagnostics=self._diagnostics(
                sequence=sequence,
                features=features,
                net=net,
                ll=ll,
                mc_value=mc_value,
                mc_source=mc_source,
                region=region,
                auxiliary_start=auxiliary_start,
                window_start=window_start,
                cutoff=cutoff,
                loss_history=history,
                converged_reason=reason,
                runtime_s=runtime_s,
                n_scored=n_scored,
            ),
            converged=converged,
            fitted_at=utc_now(),
            notes=_fit_notes(converged, reason, _branching_ratio(net)),
        )
        self._fit = result
        return result

    # ------------------------------------------------------------------ fit internals
    def _build_features(
        self, sequence: EventSequence, cutoff: datetime, mc: float
    ) -> FeatureBuilder:
        finite = sequence.depth_km[np.isfinite(sequence.depth_km)]
        depth_fill = float(np.median(finite)) if finite.size else 0.0
        provisional = FeatureBuilder(
            mc=mc,
            depth_fill=depth_fill,
            standardiser=_identity_standardiser(),
            clip=self.config.feature_clip,
        )
        raw = provisional.raw(sequence.mw, sequence.depth_km)
        standardiser = Standardiser.fit_causal(
            raw,
            ("mw_above_mc", "depth_km"),
            times=sequence.t,
            epoch=sequence.spec.epoch,
            before=cutoff,
        )
        return FeatureBuilder(
            mc=mc,
            depth_fill=depth_fill,
            standardiser=standardiser,
            clip=self.config.feature_clip,
        )

    def _build_net(self, sequence: EventSequence, mc: float, region: Region) -> NeuralKernelHawkes:
        net = NeuralKernelHawkes(self.config)
        net.set_mc(mc)
        net.set_delta_m(region.magnitude_bin_width)
        net.set_background(sequence.x, sequence.y)
        return net

    def _optimise(
        self,
        net: NeuralKernelHawkes,
        tensors: dict[str, torch.Tensor],
        window: dict[str, float],
    ) -> tuple[list[float], bool, str]:
        """Adam on the exact negative log-likelihood, keeping the best iterate.

        Convergence is "the best loss has not improved by more than ``convergence_tol`` nats for
        ``patience`` consecutive epochs", not "the loss moved less than tol this epoch": a
        stochastic-free full-batch optimiser still oscillates around a flat optimum, and the second
        criterion never fires there. The best iterate is restored at the end, so the fit does not
        depend on where the last epoch happened to land. Only the training likelihood is consulted;
        no validation data is involved, which is what keeps this an optimisation detail rather than
        a model-selection decision.
        """
        opt = torch.optim.Adam(
            net.parameters(),
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )
        history: list[float] = []
        best = float("inf")
        best_state = copy.deepcopy(net.state_dict())
        since_improvement = 0
        for _ in range(self.config.epochs):
            opt.zero_grad()
            loss = -net.log_likelihood_tensor(**tensors, **window)
            if not torch.isfinite(loss):
                net.load_state_dict(best_state)
                return history, False, "non-finite loss"
            loss.backward()  # type: ignore[no-untyped-call]
            torch.nn.utils.clip_grad_norm_(net.parameters(), max_norm=10.0)
            opt.step()
            value = float(loss.item())
            history.append(value)
            if value < best - self.convergence_tol:
                best = value
                best_state = copy.deepcopy(net.state_dict())
                since_improvement = 0
            else:
                best = min(best, value)
                since_improvement += 1
            if since_improvement >= self.patience:
                net.load_state_dict(best_state)
                return (
                    history,
                    True,
                    f"no improvement over {self.convergence_tol} nats for {self.patience} epochs",
                )
        net.load_state_dict(best_state)
        return history, False, f"epoch cap {self.config.epochs} hit"

    @staticmethod
    def _scalars(net: NeuralKernelHawkes) -> dict[str, float]:
        with torch.no_grad():
            return {
                "log_mu": float(net.log_mu.item()),
                "k0": float(net.k0.item()),
                "alpha": float(net.alpha.item()),
                "beta": float(net.beta.item()),
                "log_beta": float(net.log_beta.item()),
                "branching_ratio": float(net.branching_ratio.item()),
                "alpha_raw": float(net.alpha_raw.item()),
                "branch_raw": float(net.branch_raw.item()),
            }

    def _diagnostics(
        self,
        *,
        sequence: EventSequence,
        features: FeatureBuilder,
        net: NeuralKernelHawkes,
        ll: LogLikelihood,
        mc_value: float,
        mc_source: str,
        region: Region,
        auxiliary_start: datetime,
        window_start: datetime,
        cutoff: datetime,
        loss_history: list[float],
        converged_reason: str,
        runtime_s: float,
        n_scored: int,
    ) -> dict[str, Any]:
        latest = sequence.t.max() if len(sequence) else None
        latest_time = (
            (sequence.spec.epoch + timedelta(days=float(latest))).isoformat()
            if latest is not None
            else None
        )
        return {
            "config": self.config.to_dict(),
            "config_hash": self.config.config_hash(),
            "weights_digest": net.weight_digest(),
            "snapshot_digest": snapshot_digest(self.config, net, features),
            "feature_builder": features.to_dict(),
            "projection": sequence.spec.projection.to_dict(),
            "epoch": sequence.spec.epoch.isoformat(),
            "auxiliary_start": auxiliary_start.isoformat(),
            "timewindow_start": window_start.isoformat(),
            "timewindow_end": cutoff.isoformat(),
            "auxiliary_years": self.auxiliary_years,
            "training_max_origin_time": latest_time,
            "n_scored_events": n_scored,
            "n_background_reference_points": int(net.bg_x.numel()),
            "depth_pool": [float(v) for v in sequence.depth_km[np.isfinite(sequence.depth_km)]],
            "mc": mc_value,
            "mc_source": mc_source,
            "delta_m": region.magnitude_bin_width,
            "log_likelihood": ll.to_dict(),
            "b_value": float(np.exp(float(net.log_beta.item()))) / float(np.log(10.0)),
            "productivity_by_magnitude": _productivity_curve(net, mc_value),
            "branching_ratio": _branching_ratio(net),
            "branching_ratio_note": (
                "expected offspring per event, k0 * beta / (beta - alpha), in closed form for "
                "this productivity law and mark distribution; comparable to the ETAS adapter's "
                "branching_ratio. At or above 1 the process is critical and its cascades do not "
                "terminate on their own"
            ),
            "epochs_run": len(loss_history),
            "converged_reason": converged_reason,
            "convergence_tol": self.convergence_tol,
            "patience": self.patience,
            "final_nll": loss_history[-1] if loss_history else None,
            "initial_nll": loss_history[0] if loss_history else None,
            "runtime_s": round(runtime_s, 3),
            "torch_version": torch.__version__,
            "benchmark_conventions": "EarthquakeNPP (Stockman, Lawson & Werner, TMLR 2026)",
        }

    # ------------------------------------------------------------------ loading
    def load_fit(self, fit: FitResult, region: Region, weights: dict[str, list[float]]) -> None:
        """Make a persisted fit the one the next :meth:`forecast` call uses."""
        if fit.model_id != self.model_id:
            msg = f"fit belongs to model {fit.model_id!r}, not {self.model_id!r}"
            raise ValueError(msg)
        if fit.region_id != region.id:
            msg = f"fit is for region {fit.region_id!r}, not {region.id!r}"
            raise ValueError(msg)
        for key in ("config", "feature_builder", "projection", "epoch", "auxiliary_start"):
            if key not in fit.diagnostics:
                msg = f"fit diagnostics lack {key!r}; cannot rebuild the model"
                raise ValueError(msg)
        self.config = NTPPConfig.from_dict(fit.diagnostics["config"])
        features = FeatureBuilder.from_dict(fit.diagnostics["feature_builder"])
        net = NeuralKernelHawkes(self.config)
        net.set_mc(fit.mc)
        net.set_delta_m(float(fit.diagnostics.get("delta_m", region.magnitude_bin_width)))
        # The weights file is flat lists (no pickle), so shapes come from the freshly built
        # network. The background reference points size a buffer, so they are installed first.
        net.set_background(weights["bg_x"], weights["bg_y"])
        reference = net.state_dict()
        missing = sorted(set(reference) - set(weights))
        if missing:
            msg = f"the weights file is missing {missing}"
            raise ValueError(msg)
        net.load_state_dict(
            {
                name: torch.tensor(weights[name], dtype=torch.float64).reshape(tensor.shape)
                for name, tensor in reference.items()
            }
        )
        self._net = net
        self._features = features
        self._projection = Projection.from_dict(fit.diagnostics["projection"])
        self._epoch = datetime.fromisoformat(fit.diagnostics["epoch"])
        self._depth_pool = np.asarray(
            fit.diagnostics.get("depth_pool", [features.depth_fill]), dtype=np.float64
        )
        self._region = region
        self._lattice = build_lattice(region)
        self._fit = fit
        recovered = floats_to_digest(fit.parameters)
        if recovered != self.snapshot_digest():
            msg = (
                "the loaded weights do not reproduce the fit's parameter snapshot digest "
                f"({recovered[:12]} on file vs {self.snapshot_digest()[:12]} from the weights); "
                "the fit record and the weights file disagree"
            )
            raise ValueError(msg)

    def state_dict_json(self) -> dict[str, list[float]]:
        """Weights as plain JSON-able lists. No pickle, so a fit stays inspectable and portable."""
        if self._net is None:
            msg = "no fit loaded"
            raise RuntimeError(msg)
        return {
            k: v.detach().to(torch.float64).reshape(-1).tolist()
            for k, v in self._net.state_dict().items()
        }

    # ------------------------------------------------------------------ forecast
    def forecast(
        self,
        history: Catalog,
        issue_time: datetime,
        horizon: timedelta,
        *,
        n_simulations: int = 200,
        seed: int | None = None,
    ) -> ForecastGrid:
        """Expected counts per cell and magnitude bin over ``[issue_time, issue_time + horizon)``.

        ``history`` must be earthquakes only, all with ``mw >= mc`` and ``origin_time <
        issue_time``; anything else is refused rather than filtered. Events outside the region
        polygon or its depth range are dropped, because the region defines the process.
        """
        fit, region, lattice, net, features = self._require_fit()
        if n_simulations < 1:
            msg = "n_simulations must be >= 1"
            raise ValueError(msg)
        if horizon <= timedelta(0):
            msg = "horizon must be positive"
            raise ValueError(msg)
        assert_issue_after_fit(issue_time, fit.fit_cutoff)
        assert_all_before(history, issue_time, what="ntpp forecast history")
        self._check_history(history, fit.mc)
        spatial = _inside_region(history, region)
        assert_all_before(spatial, issue_time, what="ntpp in-region forecast history")

        epoch, projection = self._epoch, self._projection
        if epoch is None or projection is None:  # pragma: no cover - set together with the fit
            msg = "the loaded fit carries no epoch or projection"
            raise RuntimeError(msg)
        sequence = build_sequence(
            spatial, region, issue_time, mc=fit.mc, epoch=epoch, projection=projection
        )
        delta_m = region.magnitude_bin_width
        mc_lower = fit.mc - delta_m / 2.0
        start_days = sequence.days_of(issue_time)
        end_days = sequence.days_of(issue_time + horizon)
        counts, diag = simulate_window(
            net,
            features,
            history=history_batch(
                sequence.t,
                sequence.x,
                sequence.y,
                sequence.mw,
                sequence.depth_km,
                fill_depth=features.depth_fill,
            ),
            background_x=np.asarray(net.bg_x.numpy(), dtype=np.float64),
            background_y=np.asarray(net.bg_y.numpy(), dtype=np.float64),
            depth_pool=self._depth_pool,
            window_start=start_days,
            window_end=end_days,
            lattice=lattice,
            projection=projection,
            n_simulations=n_simulations,
            seed=self.config.seed if seed is None else seed,
            mc_lower=mc_lower,
            include_background=False,
        )
        background_total = float(np.exp(fit.parameters["log_mu"])) * (end_days - start_days)
        background = background_total * background_mass(net, lattice, projection)
        edges = region.magnitude_bin_edges()
        pmf = gr_bin_probabilities(fit.parameters["beta"], mc_lower, edges, None)
        expected = np.outer(counts + background, pmf)
        expected = np.where(np.isfinite(expected) & (expected > 0.0), expected, 0.0)
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
            notes=_forecast_notes(
                diag, len(sequence), fit, mc_lower, seed, background_total=background_total
            ),
        )

    def _require_fit(
        self,
    ) -> tuple[FitResult, Region, Lattice, NeuralKernelHawkes, FeatureBuilder]:
        if (
            self._fit is None
            or self._region is None
            or self._lattice is None
            or self._net is None
            or self._features is None
        ):
            msg = "no fit loaded: call fit() or load_fit() first"
            raise RuntimeError(msg)
        if self._fit.converged is False:
            msg = "the loaded fit did not converge and must not be used"
            raise RuntimeError(msg)
        return self._fit, self._region, self._lattice, self._net, self._features

    @staticmethod
    def _check_history(history: Catalog, mc: float) -> None:
        bad = [e.id for e in history.events if e.event_type != "earthquake"]
        if bad:
            msg = f"history must be earthquakes only; found {len(bad)} other entries"
            raise ValueError(msg)
        no_mw = [e.id for e in history.events if e.mw is None]
        if no_mw:
            msg = f"history has {len(no_mw)} event(s) without mw; filter with at_least(mc) first"
            raise ValueError(msg)
        below = [e.id for e in history.events if e.mw is not None and e.mw < mc]
        if below:
            msg = f"history has {len(below)} event(s) below mc={mc}; filter with at_least(mc)"
            raise ValueError(msg)


def _identity_standardiser() -> Standardiser:
    return Standardiser(
        names=("mw_above_mc", "depth_km"),
        mean=np.zeros(2),
        scale=np.ones(2),
        n_rows_fitted=0,
    )


def _fit_notes(converged: bool, reason: str, branching: float | None) -> str | None:
    """The one sentence a reader of the fit record most needs, if there is one."""
    if not converged:
        return f"not converged ({reason}): fit is not usable"
    if branching is None or branching >= 1.0:  # pragma: no cover - the parameterisation prevents it
        return (
            f"branching ratio {branching if branching is None else round(branching, 4)}: the "
            "fitted process is critical or supercritical, so its cascades do not die out on "
            "their own and its forecasts are unstable. The parameterisation is supposed to make "
            "this impossible; treat it as a bug, not a result"
        )
    if branching > 0.95:
        return (
            f"branching ratio {round(branching, 4)}: close to the parameterisation's ceiling, so "
            "the fit is pressing against the subcriticality constraint and the productivity law "
            "is only weakly identified"
        )
    return None


def _branching_ratio(net: NeuralKernelHawkes) -> float | None:
    """Expected direct offspring per event, integrated over the Gutenberg-Richter mark law.

    With productivity ``k0 exp(alpha (m - mc))`` and marks ``beta exp(-beta (m - mc))`` the
    integral is ``k0 beta / (beta - alpha)`` for ``alpha < beta``, and diverges otherwise. The
    model's parameterisation makes it exactly ``net.branching_ratio``; this function recomputes it
    from the published scalars instead, so the constraint is *checked* rather than asserted.
    """
    with torch.no_grad():
        k0 = float(net.k0.item())
        alpha = float(net.alpha.item())
        beta = float(net.beta.item())
    if alpha >= beta:  # pragma: no cover - excluded by the parameterisation
        return None
    return k0 * beta / (beta - alpha)


def _productivity_curve(net: NeuralKernelHawkes, mc: float) -> dict[str, float]:
    """Expected direct offspring at a few magnitudes, at the training median depth."""
    grid = np.arange(mc, mc + 4.01, 0.5)
    with torch.no_grad():
        amp = net.productivity(torch.tensor(grid, dtype=torch.float64))
    return {f"m{m:.1f}": float(v) for m, v in zip(grid, amp.tolist(), strict=True)}


def _inside_region(catalog: Catalog, region: Region) -> Catalog:
    poly = region_polygon(region)
    kept = tuple(
        e
        for e in catalog.events
        if poly.covers(Point(e.longitude, e.latitude))
        and (e.depth_km is None or region.depth_min_km <= e.depth_km <= region.depth_max_km)
    )
    return catalog.model_copy(update={"events": kept, "id": f"{catalog.id}/in-region"})


def background_mass(net: NeuralKernelHawkes, lattice: Lattice, projection: Projection) -> _F8:
    """Per-cell probability mass of the fitted background law, normalised over the lattice.

    The likelihood's background term is ``mu * b(x, y)`` with ``b`` a Gaussian kernel density over
    the training epicentres in projected kilometres. Here the same ``b`` is evaluated at each cell
    centre and multiplied by the cell's spherical area, then renormalised — the discrete analogue
    of the continuous term, and the counterpart of the ETAS adapter's ``smoothed_background_mass``.
    Renormalising also absorbs the mass the continuous law puts outside the region, which the
    likelihood ignores.
    """
    origins = np.asarray(lattice.origins, dtype=np.float64)
    half = lattice.cell_size_deg / 2.0
    xc, yc = projection.forward(origins[:, 0] + half, origins[:, 1] + half)
    with torch.no_grad():
        density = net.background_density(
            torch.tensor(xc, dtype=torch.float64), torch.tensor(yc, dtype=torch.float64)
        ).numpy()
    mass = np.asarray(density, dtype=np.float64) * cell_areas_km2(lattice)
    total = float(mass.sum())
    if not np.isfinite(total) or total <= 0.0:
        msg = "the fitted background law puts no mass on the lattice"
        raise RuntimeError(msg)
    out: _F8 = mass / total
    return out


def _forecast_notes(
    diag: SimulationDiagnostics,
    n_history: int,
    fit: FitResult,
    mc_lower: float,
    seed: int | None,
    *,
    background_total: float,
) -> str:
    return (
        f"neural Hawkes continuation: {diag.n_triggered} triggered events (m >= {mc_lower:.2f}) "
        f"sampled over {diag.n_simulations} simulations, {diag.n_outside_cells} outside every "
        f"cell dropped, cascade depth {diag.max_generation}; background: {background_total:.4f} "
        f"expected events placed analytically by the fitted kernel-density law over "
        f"{int(net_points(fit))} training epicentres; magnitudes: analytic GR with "
        f"beta={fit.parameters['beta']:.4f}; history: {n_history} events inside the region; "
        f"seed={seed}"
    )


def net_points(fit: FitResult) -> int:
    return int(fit.diagnostics.get("n_background_reference_points", 0))


# ---------------------------------------------------------------------- persistence
def fit_dir(baselines_dir: Path, region_id: str) -> Path:
    return Path(baselines_dir) / "ntpp" / region_id


def archive_dir(baselines_dir: Path, region_id: str, cutoff: datetime) -> Path:
    """Per-cutoff archive: ``baselines/ntpp/<region>/fits/<YYYYMMDDTHHMMSSZ>/``."""
    return fit_dir(baselines_dir, region_id) / "fits" / f"{cutoff:%Y%m%dT%H%M%SZ}"


_FILES = (FIT_RESULT_FILE, PARAMETERS_FILE, DIAGNOSTICS_FILE, WEIGHTS_FILE)


def save_fit(
    fit: FitResult,
    weights: dict[str, list[float]],
    baselines_dir: Path,
    *,
    canonical: bool = True,
) -> Path:
    """Write the fit under ``baselines/ntpp/<region>/``, archiving it under ``fits/<cutoff>/``.

    The semantics mirror ``rupture.adapters.forecasting.etas_mizrahi.save_fit`` deliberately:
    every fit is archived per cutoff, and only a **canonical** fit is written at the top level. A
    schedule's refits pass ``canonical=False`` so they cannot overwrite the declared baseline —
    if they could, a published parameter table would silently stop matching the file it cites.
    """
    out = fit_dir(baselines_dir, fit.region_id)
    out.mkdir(parents=True, exist_ok=True)
    previous = {
        name: (out / name).read_text(encoding="utf-8") if (out / name).exists() else None
        for name in _FILES
    }
    payload = {
        FIT_RESULT_FILE: fit.model_dump(mode="json"),
        PARAMETERS_FILE: {
            "model_id": fit.model_id,
            "model_version": fit.model_version,
            "region_id": fit.region_id,
            "fit_cutoff": fit.fit_cutoff.isoformat(),
            "parameters": fit.parameters,
            "parameter_snapshot_hash": fit.parameter_snapshot_hash,
            "snapshot_digest": floats_to_digest(fit.parameters),
        },
        DIAGNOSTICS_FILE: fit.diagnostics,
        WEIGHTS_FILE: weights,
    }
    for name, body in payload.items():
        (out / name).write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    archive = archive_dir(baselines_dir, fit.region_id, fit.fit_cutoff)
    archive.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        (archive / name).write_text((out / name).read_text(encoding="utf-8"), encoding="utf-8")
    if not canonical:
        for name in _FILES:
            kept = previous[name]
            if kept is None:
                (out / name).unlink(missing_ok=True)
            else:
                (out / name).write_text(kept, encoding="utf-8")
    return out


def load_saved_fit(baselines_dir: Path, region_id: str) -> tuple[FitResult, dict[str, list[float]]]:
    """Read a persisted fit and its weights."""
    directory = fit_dir(baselines_dir, region_id)
    path = directory / FIT_RESULT_FILE
    if not path.exists():
        msg = f"no persisted ntpp fit at {path}; run `rupture challenger ntpp fit` first"
        raise FileNotFoundError(msg)
    fit = FitResult.model_validate_json(path.read_text(encoding="utf-8"))
    weights = json.loads((directory / WEIGHTS_FILE).read_text(encoding="utf-8"))
    return fit, weights
