"""C1b: the gridded spatio-temporal challenger behind the ``ForecastModel`` port (ADR-0031).

What it does, in one paragraph. On the region's own 0.1-degree lattice the model rasterises the
catalogue into ``n_frames`` causal lookback frames of ``frame_days`` each, stacks four static
covariates (mapped fault density from the GEM Global Active Faults database, historical rate, mean
depth and shallow fraction), runs a small ConvLSTM over the sequence and adds its output to a
climatological log-rate. The result is an expected count of ``mw >= mc`` events per cell over one
``horizon_days`` window (independent of ``frame_days``, so the model may look back at a finer
resolution than it forecasts at); scaling to the horizon and multiplying by the analytic
Gutenberg-Richter bin probabilities
gives expected counts per cell per magnitude bin on exactly the bins ``Region.magnitude_bin_edges``
defines, which is the ETAS baseline's contract too, so pycsep compares the two directly.

What it does not do. It does not learn the magnitude distribution: that is Gutenberg-Richter with
a b-value fitted by Aki maximum likelihood on the training block, the same family of assumption
the baseline makes. It is trained at one horizon (``horizon_days``) and rescales linearly in time
to any other, which is only defensible for horizons near the trained one.

Leakage (ADR-0022). The fit refuses a catalogue that reaches the cutoff; every sample's target
window ends at or before the cutoff; the train/validation cut is blocked and time-forward with no
shuffle anywhere; and the static covariates *and* the normalisation statistics are computed from
events before the **training-block end**, not merely before the cutoff, so the early-stopping
decision cannot see the validation block either. ``forecast`` refuses a history containing an
event at or after the issue time.

rupture does not predict earthquakes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import torch
from torch import nn

from rupture import __version__ as rupture_version
from rupture.adapters.forecasting.etas_mizrahi import gr_bin_probabilities
from rupture.adapters.forecasting.leakage import (
    assert_all_before,
    assert_issue_after_fit,
)
from rupture.domain import Catalog, FitResult, ForecastGrid, Region, snapshot_hash, utc_now
from rupture.models.challengers.gridded import features as feat
from rupture.models.challengers.gridded._data import (
    SEAM_SOURCE,
    TrainOnlyScaler,
    blocked_time_forward_split,
)
from rupture.models.challengers.gridded.net import GriddedRateNet, poisson_nll, weights_sha256
from rupture.pipelines.completeness import b_value_aki

log = logging.getLogger(__name__)

MODEL_ID = "gridded-convlstm"
MODEL_VERSION = f"gridded-convlstm-0.1.0+torch-{torch.__version__.split('+')[0]}"

FIT_RESULT_FILE = "fit_result.json"
PARAMETERS_FILE = "parameters.json"
DIAGNOSTICS_FILE = "diagnostics.json"
WEIGHTS_FILE = "weights.pt"
STATE_FILE = "model_state.json"
HYPERPARAMETERS_FILE = "hyperparameters.json"


@dataclass(frozen=True)
class GriddedConfig:
    """Every hyperparameter. Frozen and hashed before any test window is scored (ADR-0022 § 4)."""

    n_frames: int = 6
    frame_days: float = 30.0
    horizon_days: float = 30.0
    hidden_channels: int = 8
    kernel_size: int = 3
    learning_rate: float = 3e-3
    weight_decay: float = 1e-4
    max_epochs: int = 80
    patience: int = 15
    batch_size: int = 32
    smoothing_sigma_cells: float = 1.5
    training_years: float = 20.0
    inner_validation_years: float = 3.0
    seed: int = 20220101
    torch_num_threads: int = 4

    def as_dict(self) -> dict[str, Any]:
        return dict(asdict(self))

    def hash(self) -> str:
        return snapshot_hash({k: float(v) for k, v in self.as_dict().items()})


@dataclass
class _FittedState:
    """Everything ``forecast`` needs that is not in the ``FitResult`` numbers."""

    config: GriddedConfig
    net: GriddedRateNet
    dynamic_scaler: Any
    static_scaler: Any
    static_values: npt.NDArray[np.float32]
    log_prior: npt.NDArray[np.float32]
    mc: float
    mc_lower: float
    beta: float


class GriddedChallenger:
    """``ForecastModel``: fit on a catalogue before a cutoff, then issue gridded rate forecasts."""

    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION

    def __init__(
        self,
        config: GriddedConfig | None = None,
        *,
        faults_path: Path | None = feat.DEFAULT_FAULTS_PARQUET,
    ) -> None:
        self.config = config or GriddedConfig()
        self.faults_path = faults_path
        self._fit: FitResult | None = None
        self._region: Region | None = None
        self._raster: feat.Raster | None = None
        self._state: _FittedState | None = None

    # ------------------------------------------------------------------ state
    @property
    def fit_result(self) -> FitResult | None:
        return self._fit

    @property
    def region(self) -> Region | None:
        return self._region

    def parameter_snapshot(self) -> dict[str, Any]:
        """The parameters the next ``forecast`` call would use, weights included by hash."""
        if self._fit is None or self._state is None:
            return {}
        return {
            "weights_sha256": self._fit.diagnostics["weights_sha256"],
            "config_hash": self.config.hash(),
            "config": self.config.as_dict(),
            "beta": self._state.beta,
            "mc": self._state.mc,
            "n_weights": self._fit.diagnostics["n_weights"],
        }

    # ------------------------------------------------------------------ fit
    def fit(
        self,
        catalog: Catalog,
        region: Region,
        cutoff: datetime,
        *,
        mc: float | None = None,
    ) -> FitResult:
        cfg = self.config
        torch.manual_seed(cfg.seed)
        torch.set_num_threads(cfg.torch_num_threads)

        training = catalog.before(cutoff)
        assert_all_before(training, cutoff, what="gridded fit training catalogue")
        mc_value = self._resolve_mc(region, mc)
        delta_m = region.magnitude_bin_width
        mc_lower = mc_value - delta_m / 2.0

        raster = feat.build_raster(region)
        events = feat.event_arrays(training, raster, region)
        if len(events) == 0:
            msg = "no usable training events inside the region; refusing to fit"
            raise ValueError(msg)

        issue_times, train_end = self._schedule(events, cutoff)
        if len(issue_times) < 8:
            msg = (
                f"only {len(issue_times)} training windows fit between the catalogue start and "
                f"{cutoff.isoformat()}; refusing to fit"
            )
            raise ValueError(msg)

        # ADR-0022 § 5: static covariates and scalers see the training block only.
        static = feat.static_covariates(
            events,
            raster,
            region,
            train_end,
            mc=mc_value,
            frame_days=cfg.horizon_days,
            smoothing_sigma_cells=cfg.smoothing_sigma_cells,
            faults_path=self.faults_path,
        )
        samples = feat.sample_set(
            events,
            raster,
            issue_times,
            horizon_days=cfg.horizon_days,
            n_frames=cfg.n_frames,
            frame_days=cfg.frame_days,
            mc=mc_value,
            mc_lower=mc_lower,
            cutoff=cutoff,
        )
        train_idx, val_idx = blocked_time_forward_split(
            list(samples.window_ends), train_end=train_end, validation_end=cutoff
        )
        if len(train_idx) == 0 or len(val_idx) == 0:
            msg = (
                f"blocked split left {len(train_idx)} training and {len(val_idx)} validation "
                f"windows; widen training_years or shorten inner_validation_years"
            )
            raise ValueError(msg)

        dyn_scaler = TrainOnlyScaler.fit(
            samples.dynamic[train_idx].astype(np.float64),
            axis=(0, 1, 3, 4),
            fitted_on=f"windows ending <= {train_end.isoformat()}",
        )
        static_scaler = TrainOnlyScaler.fit(
            static.values.astype(np.float64)[:, raster.mask].T,
            axis=(0,),
            fitted_on=f"events before {train_end.isoformat()}",
        )

        dyn = self._scale_dynamic(samples.dynamic, dyn_scaler, raster)
        stat = self._scale_static(static.values, static_scaler, raster)

        mask_t = torch.from_numpy(raster.mask.astype(np.float32))
        stat_t = torch.from_numpy(stat)
        prior_t = torch.from_numpy(static.log_prior)
        counts_t = torch.from_numpy(samples.counts)
        dyn_t = torch.from_numpy(dyn)

        net = GriddedRateNet(
            n_dynamic=len(feat.DYNAMIC_CHANNELS),
            n_static=len(feat.STATIC_CHANNELS),
            hidden_channels=cfg.hidden_channels,
            kernel_size=cfg.kernel_size,
        )
        history = self._train(
            net=net,
            dyn=dyn_t,
            counts=counts_t,
            static=stat_t,
            log_prior=prior_t,
            mask=mask_t,
            train_idx=train_idx,
            val_idx=val_idx,
            cfg=cfg,
        )

        b_value, b_sigma, n_b = self._b_value(events, cutoff, mc_value, delta_m)
        beta = float(b_value * np.log(10.0))
        state = _FittedState(
            config=cfg,
            net=net,
            dynamic_scaler=dyn_scaler,
            static_scaler=static_scaler,
            static_values=static.values,
            log_prior=static.log_prior,
            mc=mc_value,
            mc_lower=mc_lower,
            beta=beta,
        )
        sha = weights_sha256(net)
        n_weights = int(sum(p.numel() for p in net.parameters()))
        parameters = {
            "beta": beta,
            "b_value": float(b_value),
            "mc": float(mc_value),
            "log_scale": float(net.log_scale.detach().item()),
            "n_weights": float(n_weights),
            "config_hash_hi": float(int(cfg.hash()[:12], 16)),
            "weights_digest_hi": float(int(sha[:12], 16)),
            "weights_digest_lo": float(int(sha[12:24], 16)),
        }
        start = training.min_origin_time()
        diagnostics: dict[str, Any] = {
            "config": cfg.as_dict(),
            "config_hash": cfg.hash(),
            "weights_sha256": sha,
            "n_weights": n_weights,
            "seam_source": SEAM_SOURCE,
            "torch_version": torch.__version__,
            "rupture_version": rupture_version,
            "n_cells": raster.n_cells,
            "raster_shape": [raster.ny, raster.nx],
            "n_magnitude_bins": len(region.magnitude_bin_edges()),
            "mc_source": "region.mc" if mc is None else "explicit mc kwarg",
            "b_value_uncertainty": float(b_sigma),
            "b_value_n_events": int(n_b),
            "train_windows": len(train_idx),
            "validation_windows": len(val_idx),
            "train_block_end": train_end.isoformat(),
            "training_max_origin_time": (
                latest.isoformat() if (latest := training.max_origin_time()) else None
            ),
            "first_issue_time": issue_times[0].isoformat(),
            "last_issue_time": issue_times[-1].isoformat(),
            "train_target_events": float(samples.counts[train_idx].sum()),
            "validation_target_events": float(samples.counts[val_idx].sum()),
            "training": history,
            "dynamic_scaler": dyn_scaler.as_dict(),
            "static_scaler": static_scaler.as_dict(),
            "static_covariates": static.provenance,
            "dynamic_channels": list(feat.DYNAMIC_CHANNELS),
            "static_channels": list(feat.STATIC_CHANNELS),
            "horizon_note": (
                f"trained at a {cfg.horizon_days:g} d horizon with {cfg.n_frames} lookback frames "
                f"of {cfg.frame_days:g} d; other horizons are rescaled linearly in time"
            ),
        }
        result = FitResult(
            model_id=self.model_id,
            model_version=self.model_version,
            region_id=region.id,
            fit_cutoff=cutoff,
            training_start=start if start is not None else cutoff,
            training_catalog_hash=training.event_hash(),
            n_events=len(training),
            mc=mc_value,
            parameters=parameters,
            parameter_snapshot_hash=snapshot_hash(parameters),
            log_likelihood=-float(history["best_validation_nll"]),
            diagnostics=diagnostics,
            converged=bool(history["early_stopped"]),
            fitted_at=utc_now(),
            notes=(
                "Poisson negative log-likelihood on cell counts; the reported log_likelihood is "
                "the best validation-block value, not a full point-process likelihood."
            ),
        )
        self._fit = result
        self._region = region
        self._raster = raster
        self._state = state
        return result

    # ------------------------------------------------------------------ forecast
    def forecast(
        self,
        history: Catalog,
        issue_time: datetime,
        horizon: timedelta,
    ) -> ForecastGrid:
        fit, region, raster, state = self._require_fit()
        if horizon <= timedelta(0):
            msg = "horizon must be positive"
            raise ValueError(msg)
        assert_issue_after_fit(issue_time, fit.fit_cutoff)
        assert_all_before(history, issue_time, what="gridded forecast history")

        events = feat.event_arrays(history, raster, region)
        frames = feat.dynamic_frames(
            events,
            raster,
            issue_time,
            n_frames=state.config.n_frames,
            frame_days=state.config.frame_days,
            mc=state.mc,
        )
        dyn = self._scale_dynamic(frames[None, ...], state.dynamic_scaler, raster)
        stat = self._scale_static(state.static_values, state.static_scaler, raster)
        state.net.eval()
        with torch.no_grad():
            log_rate = state.net(
                torch.from_numpy(dyn),
                torch.from_numpy(stat)[None, ...],
                torch.from_numpy(state.log_prior)[None, ...],
            )
        per_frame = np.asarray(torch.exp(log_rate)[0].numpy(), dtype=np.float64)
        scale = horizon.total_seconds() / (state.config.horizon_days * 86400.0)
        cell_rate = raster.to_cells(per_frame * raster.mask) * scale

        edges = region.magnitude_bin_edges()
        pmf = gr_bin_probabilities(state.beta, state.mc_lower, edges, None)
        expected = np.outer(cell_rate, pmf)
        expected = np.where(np.isfinite(expected) & (expected > 0.0), expected, 0.0)
        notes = (
            f"ConvLSTM rate model: {len(events)} events inside the region before the issue time, "
            f"{state.config.n_frames} causal frames of {state.config.frame_days:g} d; "
            f"expected {float(cell_rate.sum()):.4f} events with m >= {state.mc_lower:.2f} over "
            f"the horizon; magnitudes analytic Gutenberg-Richter with beta={state.beta:.4f}; "
            f"weights {fit.diagnostics['weights_sha256'][:12]}"
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
            cell_origins=raster.lattice.origins,
            magnitude_bin_edges=edges,
            magnitude_bin_width=region.magnitude_bin_width,
            expected_counts=tuple(tuple(float(v) for v in row) for row in expected),
            n_simulations=None,
            created_at=utc_now(),
            notes=notes,
        )

    # ------------------------------------------------------------------ internals
    def _require_fit(self) -> tuple[FitResult, Region, feat.Raster, _FittedState]:
        if self._fit is None or self._region is None or self._raster is None or self._state is None:
            msg = "no fit loaded: call fit() or load_fit() first"
            raise RuntimeError(msg)
        return self._fit, self._region, self._raster, self._state

    @staticmethod
    def _resolve_mc(region: Region, mc: float | None) -> float:
        if mc is not None:
            return float(mc)
        if region.mc is None:
            msg = (
                f"region {region.id!r} has no fitted mc and no mc was given; "
                f"the gridded model will not guess one"
            )
            raise ValueError(msg)
        return float(region.mc.mc)

    def _schedule(
        self, events: feat.EventArrays, cutoff: datetime
    ) -> tuple[list[datetime], datetime]:
        """Issue times anchored backwards from the cutoff, plus the blocked split boundary."""
        cfg = self.config
        step = timedelta(days=cfg.horizon_days)
        earliest_data = datetime.fromtimestamp(float(events.epoch_s.min()), tz=cutoff.tzinfo)
        earliest_allowed = earliest_data + timedelta(days=cfg.frame_days * cfg.n_frames)
        window_start = cutoff - timedelta(days=365.25 * cfg.training_years)
        first_allowed = max(earliest_allowed, window_start)
        times: list[datetime] = []
        t = cutoff - step
        while t >= first_allowed:
            times.append(t)
            t -= step
        times.reverse()
        train_end = cutoff - timedelta(days=365.25 * cfg.inner_validation_years)
        return times, train_end

    @staticmethod
    def _scale_dynamic(
        dynamic: npt.NDArray[np.float32], scaler: Any, raster: feat.Raster
    ) -> npt.NDArray[np.float32]:
        arr = dynamic.astype(np.float64)
        mean = np.asarray(scaler.mean).reshape(1, 1, -1, 1, 1)
        std = np.asarray(scaler.std).reshape(1, 1, -1, 1, 1)
        out = (arr - mean) / std
        out *= raster.mask.astype(np.float64)
        return np.ascontiguousarray(out, dtype=np.float32)

    @staticmethod
    def _scale_static(
        static: npt.NDArray[np.float32], scaler: Any, raster: feat.Raster
    ) -> npt.NDArray[np.float32]:
        arr = static.astype(np.float64)
        mean = np.asarray(scaler.mean).reshape(-1, 1, 1)
        std = np.asarray(scaler.std).reshape(-1, 1, 1)
        out = (arr - mean) / std
        out *= raster.mask.astype(np.float64)
        return np.ascontiguousarray(out, dtype=np.float32)

    @staticmethod
    def _b_value(
        events: feat.EventArrays, cutoff: datetime, mc: float, delta_m: float
    ) -> tuple[float, float, int]:
        sel = (events.epoch_s < cutoff.timestamp()) & (events.mw >= mc - delta_m / 2.0)
        mags = events.mw[sel]
        if mags.size < 30:
            msg = f"only {mags.size} events at or above mc={mc}; refusing to fit a b-value"
            raise ValueError(msg)
        return b_value_aki(mags, mc, delta_m)

    @staticmethod
    def _train(
        *,
        net: GriddedRateNet,
        dyn: torch.Tensor,
        counts: torch.Tensor,
        static: torch.Tensor,
        log_prior: torch.Tensor,
        mask: torch.Tensor,
        train_idx: npt.NDArray[np.int64],
        val_idx: npt.NDArray[np.int64],
        cfg: GriddedConfig,
    ) -> dict[str, Any]:
        """Deterministic full-order mini-batch Adam with early stopping on the validation block.

        Batches are taken in time order and never shuffled: ADR-0022 forbids a shuffled split, and
        a deterministic order also makes the run reproducible under a fixed seed.

        The **untrained** network is scored first, as epoch -1. Its head is zero, so that state is
        exactly the climatological prior, and it is a legitimate candidate: if no amount of
        training improves the held-out likelihood, the honest answer is to keep the climatology and
        to be able to say that the selected model *is* the climatology.
        """
        opt = torch.optim.Adam(
            net.parameters(), lr=cfg.learning_rate, weight_decay=cfg.weight_decay
        )
        n_train = len(train_idx)
        curve: list[dict[str, float]] = []
        stale = 0
        early = False

        def validation_nll() -> float:
            net.eval()
            with torch.no_grad():
                vidx = torch.from_numpy(val_idx)
                vlog = net(
                    dyn[vidx],
                    static.expand(len(vidx), *static.shape),
                    log_prior.expand(len(vidx), -1, -1),
                )
                return float(poisson_nll(vlog, counts[vidx], mask) / len(vidx))

        best = validation_nll()
        best_epoch = -1
        best_state: dict[str, torch.Tensor] = {
            k: v.detach().clone() for k, v in net.state_dict().items()
        }
        curve.append({"epoch": -1, "train_nll": float("nan"), "validation_nll": best})
        for epoch in range(cfg.max_epochs):
            net.train()
            total = 0.0
            for start in range(0, n_train, cfg.batch_size):
                idx = torch.from_numpy(train_idx[start : start + cfg.batch_size])
                opt.zero_grad()
                log_rate = net(
                    dyn[idx],
                    static.expand(len(idx), *static.shape),
                    log_prior.expand(len(idx), -1, -1),
                )
                loss = poisson_nll(log_rate, counts[idx], mask) / len(idx)
                loss.backward()  # type: ignore[no-untyped-call]
                torch.nn.utils.clip_grad_norm_(net.parameters(), 5.0)
                opt.step()
                total += float(loss.detach()) * len(idx)
            vloss = validation_nll()
            curve.append({"epoch": epoch, "train_nll": total / n_train, "validation_nll": vloss})
            if vloss < best - 1e-9:
                best, best_epoch, stale = vloss, epoch, 0
                best_state = {k: v.detach().clone() for k, v in net.state_dict().items()}
            else:
                stale += 1
                if stale >= cfg.patience:
                    early = True
                    break
        net.load_state_dict(best_state)
        return {
            "epochs_run": len(curve) - 1,
            "best_epoch": best_epoch,
            "best_validation_nll": best,
            "untrained_validation_nll": curve[0]["validation_nll"],
            "selected_the_untrained_climatology": best_epoch == -1,
            "early_stopped": early,
            "curve": curve[:: max(1, len(curve) // 40)],
            "loss": "Poisson negative log-likelihood per window, summed over in-region cells",
            "epoch_minus_one": (
                "epoch -1 is the untrained network, whose zero-initialised head makes it exactly "
                "the climatological prior"
            ),
        }


# ---------------------------------------------------------------------- persistence
def fit_dir(baselines_dir: Path, region_id: str) -> Path:
    return Path(baselines_dir) / "gridded" / region_id


def archive_dir(baselines_dir: Path, region_id: str, cutoff: datetime) -> Path:
    """Per-cutoff archive: ``baselines/gridded/<region>/fits/<YYYYMMDDTHHMMSSZ>/``."""
    return fit_dir(baselines_dir, region_id) / "fits" / f"{cutoff:%Y%m%dT%H%M%SZ}"


_FILES = (
    FIT_RESULT_FILE,
    PARAMETERS_FILE,
    DIAGNOSTICS_FILE,
    WEIGHTS_FILE,
    STATE_FILE,
    HYPERPARAMETERS_FILE,
)


def save_fit(
    model: GriddedChallenger,
    baselines_dir: Path,
    *,
    canonical: bool = True,
    search_provenance: dict[str, Any] | None = None,
) -> Path:
    """Persist a fitted model, mirroring the ETAS layout; every fit is archived per cutoff.

    ``canonical=False`` writes the archive only and restores whatever was at the top of
    ``baselines/gridded/<region>/`` — the same rule the ETAS adapter uses so that a schedule's
    refits never replace a declared baseline.

    ``hyperparameters.json`` records the frozen configuration, its hash, and the window the choice
    was made on, so that the ``validate-challengers`` gate can check the freezing claim against the
    fit rather than take the documentation's word for it. ``search_provenance`` carries the
    hyperparameter search that chose the configuration, when the caller ran one.
    """
    fit, region, raster, state = model._require_fit()
    out = fit_dir(baselines_dir, fit.region_id)
    out.mkdir(parents=True, exist_ok=True)
    previous = {
        name: (out / name).read_bytes() if (out / name).exists() else None for name in _FILES
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
                "weights_sha256": fit.diagnostics["weights_sha256"],
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
    (out / HYPERPARAMETERS_FILE).write_text(
        json.dumps(
            {
                "config": state.config.as_dict(),
                "config_hash": state.config.hash(),
                "frozen_before_scoring": True,
                "validation_start": fit.diagnostics["train_block_end"],
                "validation_end": fit.fit_cutoff.isoformat(),
                "validation_windows": fit.diagnostics["validation_windows"],
                "criterion": (
                    "lowest Poisson negative log-likelihood on the blocked, time-forward inner "
                    "validation block, which ends at the fit cutoff; the untrained network is a "
                    "candidate (epoch -1)"
                ),
                "selected_the_untrained_climatology": fit.diagnostics["training"][
                    "selected_the_untrained_climatology"
                ],
                "search": search_provenance,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    torch.save(state.net.state_dict(), out / WEIGHTS_FILE)
    (out / STATE_FILE).write_text(
        json.dumps(
            {
                "region": region.model_dump(mode="json"),
                "config": state.config.as_dict(),
                "mc": state.mc,
                "mc_lower": state.mc_lower,
                "beta": state.beta,
                "dynamic_scaler": state.dynamic_scaler.as_dict(),
                "static_scaler": state.static_scaler.as_dict(),
                "static_values": state.static_values.tolist(),
                "log_prior": state.log_prior.tolist(),
                "raster_shape": [raster.ny, raster.nx],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    archive = archive_dir(baselines_dir, fit.region_id, fit.fit_cutoff)
    archive.mkdir(parents=True, exist_ok=True)
    for name in _FILES:
        (archive / name).write_bytes((out / name).read_bytes())
    if not canonical:
        for name in _FILES:
            kept = previous[name]
            if kept is None:
                (out / name).unlink(missing_ok=True)
            else:
                (out / name).write_bytes(kept)
    return out


def load_fit(
    baselines_dir: Path, region_id: str, *, cutoff: datetime | None = None
) -> GriddedChallenger:
    """Rebuild a fitted model from ``baselines/gridded/<region>/`` (or one of its archives)."""
    src = (
        fit_dir(baselines_dir, region_id)
        if cutoff is None
        else archive_dir(baselines_dir, region_id, cutoff)
    )
    path = src / FIT_RESULT_FILE
    if not path.exists():
        msg = f"no persisted gridded fit at {path}"
        raise FileNotFoundError(msg)
    fit = FitResult.model_validate_json(path.read_text(encoding="utf-8"))
    payload = json.loads((src / STATE_FILE).read_text(encoding="utf-8"))
    region = Region.model_validate(payload["region"])
    config = GriddedConfig(**payload["config"])
    model = GriddedChallenger(config)
    raster = feat.build_raster(region)
    net = GriddedRateNet(
        n_dynamic=len(feat.DYNAMIC_CHANNELS),
        n_static=len(feat.STATIC_CHANNELS),
        hidden_channels=config.hidden_channels,
        kernel_size=config.kernel_size,
    )
    net.load_state_dict(torch.load(src / WEIGHTS_FILE, weights_only=True))
    net.eval()
    model._fit = fit
    model._region = region
    model._raster = raster
    model._state = _FittedState(
        config=config,
        net=net,
        dynamic_scaler=TrainOnlyScaler.from_dict(payload["dynamic_scaler"]),
        static_scaler=TrainOnlyScaler.from_dict(payload["static_scaler"]),
        static_values=np.asarray(payload["static_values"], dtype=np.float32),
        log_prior=np.asarray(payload["log_prior"], dtype=np.float32),
        mc=float(payload["mc"]),
        mc_lower=float(payload["mc_lower"]),
        beta=float(payload["beta"]),
    )
    return model


def with_config(model: GriddedChallenger, **changes: Any) -> GriddedChallenger:
    """A fresh, unfitted model with the same faults source and a modified config."""
    return GriddedChallenger(replace(model.config, **changes), faults_path=model.faults_path)


def count_parameters(net: nn.Module) -> int:
    return int(sum(p.numel() for p in net.parameters()))
