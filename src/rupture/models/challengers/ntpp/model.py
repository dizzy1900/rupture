"""The neural spatio-temporal point process itself: architecture, features, log-likelihood.

**What it is.** A marked Hawkes process whose conditional intensity is

    lambda(t, x, y) = mu * b(x, y)
                      + sum_{t_i < t} A_i * h_i(t - t_i) * g_i(||(x, y) - (x_i, y_i)||)

with the mark (magnitude) drawn from a Gutenberg-Richter law. What makes it *neural* rather than
ETAS is where the kernel shapes come from: ``h_i`` and ``g_i`` are convex mixtures over the fixed
Omori and power-law bases of :mod:`.kernels`, and **a small MLP maps event i's own mark and depth
to the mixture weights**. So the temporal decay and the spatial spread of an event's aftershock
cloud are learned, smooth functions of that event's magnitude and depth, rather than the single
fixed exponent pair ETAS gives every event.

Productivity is deliberately *not* neural, and it is **subcritical by construction**.
``A_i = k0 exp(alpha (m_i - mc))`` is the ETAS form, but neither ``k0`` nor ``alpha`` is learned
directly. What is learned is the pair *(branching ratio, magnitude sensitivity)*:

    alpha     = beta * max_alpha_fraction * sigmoid(alpha_raw)      (so alpha < beta always)
    n         = max_branching_ratio * sigmoid(branch_raw)           (so 0 < n < 1 always)
    k0        = n * (beta - alpha) / beta

The branching ratio — expected direct offspring per event, integrated over the Gutenberg-Richter
mark law — is exactly ``n``, so it cannot reach 1. This is not a tuning choice. Fitted without it,
maximum likelihood drove the model supercritical on every catalogue tried: 1.00 on a two-year
California fixture, 0.96 on Nepal, **1.83** on Türkiye, where ``alpha`` had climbed to within nine
percent of ``beta`` and the productivity integral was close to diverging. A supercritical Hawkes
process has cascades that never die out and forecasts that are not merely wrong but unstable, and
every operational ETAS implementation constrains its parameters for exactly this reason (the
``etas`` package has explicit inversion ranges). The constraint was added after seeing the
*training-set* branching ratio, never a test score.

An earlier version also let the MLP add a bounded offset to productivity; on a few hundred events
that produced a curve oscillating by a factor of fifty between neighbouring half-magnitude steps,
and it made ``alpha`` non-identifiable because the offset was itself a function of magnitude.
Bounding the neural part to the *shape* of the kernel — a softmax over densities, so any output is
still a valid density — keeps the model honest where it is extrapolating, which for a catalogue
whose test window opens with a mainshock larger than anything in training is not a hypothetical
concern. Standardised features are additionally clipped to ``config.feature_clip``, so an event
far outside the training range is treated as the most extreme event the model actually saw rather
than extrapolated.

**Why this shape and not a recurrent or attention-based one.** Three reasons, in order of weight.
(1) The compensator ``int lambda`` stays exact and closed-form, so the likelihood is the real
likelihood; a model whose normalisation is itself approximated can improve its score by getting
the approximation wrong. (2) It runs on a CPU in seconds on a few hundred events, which is the
size of catalogue actually available here. (3) It degenerates gracefully towards ETAS, so a
negative result is interpretable — it says the extra flexibility did not pay, not that the
optimiser failed.

**What it is not.** It does not model magnitude dependence in the mark distribution, aftershock
anisotropy, finite-fault geometry, or time-varying completeness.
this produces expected counts per cell and magnitude bin
over a horizon, and nothing more.

Conventions follow the EarthquakeNPP benchmark (Stockman, Lawson & Werner, TMLR 2026;
``ss15859/EarthquakeNPP``, MIT) where they apply — time in float days, locations in projected
kilometres, a hard magnitude cut with no censored likelihood, log-likelihood per test event split
into temporal and spatial parts. ``docs/CHALLENGER_NTPP.md`` lists what was adopted and what was
deliberately departed from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import numpy.typing as npt
import torch
from torch import nn

from rupture.domain import sha256_hex
from rupture.models.challengers.ntpp.kernels import (
    geometric_scales,
    gr_log_density,
    omori_density,
    omori_integral,
    powerlaw_density,
)
from rupture.models.data import EventSequence, Standardiser

_F8 = npt.NDArray[np.float64]

FEATURE_NAMES: tuple[str, ...] = ("mw_above_mc", "depth_km")
TARGET_CHUNK = 256  # rows of the (target x source) pair matrix built at once


@dataclass(frozen=True)
class NTPPConfig:
    """Every architectural and optimisation choice, in one hashable record.

    The hash of this record is what "the frozen configuration" means in ADR-0022 decision 4: it is
    written down before any test window is scored, and it appears in the model's parameter
    snapshot, so a schedule that silently retuned would change the snapshot hash and fail the
    protocol's constancy check.
    """

    n_time_basis: int = 6
    time_scale_min_days: float = 1e-3
    time_scale_max_days: float = 100.0
    omori_p: float = 1.15
    n_space_basis: int = 5
    space_scale_min_km: float = 0.5
    space_scale_max_km: float = 50.0
    spatial_s: float = 1.5
    hidden: int = 16
    feature_clip: float = 3.0
    #: ``alpha`` is capped at this fraction of ``beta``. Above 1 the productivity integral
    #: diverges; approaching 1 it explodes, which is where unconstrained fitting went.
    max_alpha_fraction: float = 0.95
    #: hard ceiling on the branching ratio, so the fitted process is always subcritical.
    max_branching_ratio: float = 0.98
    background_sigma_km: float = 10.0
    learning_rate: float = 0.05
    # Generous: the whole fit is seconds on a CPU, and the optimiser stops early on its own
    # convergence test. A cap that bites leaves ``converged=False``, and the adapter then refuses
    # to forecast from the fit, which is the right failure but a wasteful way to discover it.
    epochs: int = 8000
    weight_decay: float = 0.0
    seed: int = 20220101

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> NTPPConfig:
        known = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        return cls(**known)

    def config_hash(self) -> str:
        items = sorted((k, repr(v)) for k, v in self.to_dict().items())
        return sha256_hex("\n".join(f"{k}={v}" for k, v in items))

    def with_(self, **changes: Any) -> NTPPConfig:
        return replace(self, **changes)


@dataclass(frozen=True)
class FeatureBuilder:
    """Turns raw marks into the MLP's input, using training-only statistics.

    ``depth_fill`` is the training-set median depth, used where a catalogue reports none, and
    ``clip`` bounds the standardised features. Both are normalisation statistics in the sense of
    ADR-0022 decision 5, fitted on training data only and carried with the model.
    """

    mc: float
    depth_fill: float
    standardiser: Standardiser
    clip: float = 3.0

    def raw(self, mw: npt.ArrayLike, depth_km: npt.ArrayLike) -> _F8:
        m = np.asarray(mw, dtype=np.float64) - self.mc
        d = np.asarray(depth_km, dtype=np.float64)
        d = np.where(np.isfinite(d), d, self.depth_fill)
        return np.column_stack([m, d])

    def transform(self, mw: npt.ArrayLike, depth_km: npt.ArrayLike) -> _F8:
        """Standardise, then clip. Clipping is what stops a mainshock larger than anything in
        training being extrapolated far outside the range the MLP was fitted on."""
        z = self.standardiser.transform(self.raw(mw, depth_km))
        return np.clip(z, -self.clip, self.clip)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mc": self.mc,
            "depth_fill": self.depth_fill,
            "clip": self.clip,
            "standardiser": self.standardiser.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> FeatureBuilder:
        return cls(
            mc=float(raw["mc"]),
            depth_fill=float(raw["depth_fill"]),
            clip=float(raw.get("clip", 3.0)),
            standardiser=Standardiser.from_dict(raw["standardiser"]),
        )


@dataclass(frozen=True)
class LogLikelihood:
    """The EarthquakeNPP reporting split: per-event temporal and spatial log-likelihood.

    ``total`` is the joint log-likelihood over the window in nats (including the mark term);
    ``tll`` and ``sll`` are per-event and exclude the mark term, so ``nll = -(tll + sll)``
    reproduces the benchmark's headline number. ``mll`` reports the mark term separately, because
    rupture needs magnitudes and the benchmark's models discard them.
    """

    total: float
    tll: float
    sll: float
    mll: float
    n_events: int
    compensator: float

    @property
    def nll(self) -> float:
        return -(self.tll + self.sll)

    def to_dict(self) -> dict[str, float | int]:
        return {
            "total": self.total,
            "tll": self.tll,
            "sll": self.sll,
            "mll": self.mll,
            "nll": self.nll,
            "n_events": self.n_events,
            "compensator": self.compensator,
        }


class NeuralKernelHawkes(nn.Module):
    """Mixture-of-basis Hawkes kernels with neural, mark-dependent mixture weights."""

    # Registered buffers, declared so they type as tensors rather than ``Tensor | Module``.
    time_scales: torch.Tensor
    space_scales: torch.Tensor
    bg_x: torch.Tensor
    bg_y: torch.Tensor
    #: Completeness magnitude; set once from the fit, never learned.
    mc_tensor: torch.Tensor

    def __init__(self, config: NTPPConfig) -> None:
        super().__init__()
        self.config = config
        torch.manual_seed(config.seed)
        self.register_buffer(
            "time_scales",
            torch.tensor(
                geometric_scales(
                    config.time_scale_min_days, config.time_scale_max_days, config.n_time_basis
                ),
                dtype=torch.float64,
            ),
        )
        self.register_buffer(
            "space_scales",
            torch.tensor(
                geometric_scales(
                    config.space_scale_min_km, config.space_scale_max_km, config.n_space_basis
                ),
                dtype=torch.float64,
            ),
        )
        self.log_mu = nn.Parameter(torch.tensor(-1.0, dtype=torch.float64))
        # The productivity law is parameterised by (branching ratio, magnitude sensitivity), both
        # through a sigmoid, so the fitted process is subcritical and ``alpha < beta`` by
        # construction rather than by hope. ``k0`` is derived, not learned.
        self.alpha_raw = nn.Parameter(torch.tensor(0.0, dtype=torch.float64))
        self.branch_raw = nn.Parameter(torch.tensor(0.0, dtype=torch.float64))
        self.log_beta = nn.Parameter(torch.tensor(float(np.log(np.log(10.0))), dtype=torch.float64))
        n_out = config.n_time_basis + config.n_space_basis
        self.head = nn.Sequential(
            nn.Linear(len(FEATURE_NAMES), config.hidden, dtype=torch.float64),
            nn.Tanh(),
            nn.Linear(config.hidden, config.hidden, dtype=torch.float64),
            nn.Tanh(),
            nn.Linear(config.hidden, n_out, dtype=torch.float64),
        )
        # Background reference points (training epicentres, projected km); set by set_background.
        self.register_buffer("bg_x", torch.zeros(0, dtype=torch.float64))
        self.register_buffer("bg_y", torch.zeros(0, dtype=torch.float64))

    # ------------------------------------------------------------------ background
    def set_background(self, x: npt.ArrayLike, y: npt.ArrayLike) -> None:
        """Fix the background reference points. Training epicentres only, never later ones."""
        self.bg_x = torch.tensor(np.asarray(x, dtype=np.float64), dtype=torch.float64)
        self.bg_y = torch.tensor(np.asarray(y, dtype=np.float64), dtype=torch.float64)

    def background_density(self, x: torch.Tensor, y: torch.Tensor) -> torch.Tensor:
        """Gaussian kernel density (per km^2) over the background reference points.

        Edge effects are ignored: the density is not renormalised for the mass that falls outside
        the region polygon. For a region a few hundred kilometres across and a bandwidth of tens of
        kilometres the missing mass is small, and the same simplification is made in the
        compensator so the likelihood stays internally consistent. ``docs/CHALLENGER_NTPP.md``
        lists it among the limitations.
        """
        if self.bg_x.numel() == 0:
            msg = "background reference points are not set; call set_background() first"
            raise RuntimeError(msg)
        sigma = self.config.background_sigma_km
        dx = x.unsqueeze(-1) - self.bg_x.unsqueeze(0)
        dy = y.unsqueeze(-1) - self.bg_y.unsqueeze(0)
        norm = 1.0 / (2.0 * np.pi * sigma * sigma)
        w = torch.exp(-(dx * dx + dy * dy) / (2.0 * sigma * sigma)) * norm
        return w.mean(dim=-1)

    # ------------------------------------------------------------------ neural head
    def kernel_weights(self, features: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Temporal and spatial mixture weights for each event, from its mark and depth.

        Both are softmax outputs, so each mixture is convex and the resulting kernel is a proper
        density however badly the MLP behaves on an input it has not seen.
        """
        raw = self.head(features)
        k, ell = self.config.n_time_basis, self.config.n_space_basis
        return torch.softmax(raw[:, :k], dim=-1), torch.softmax(raw[:, k : k + ell], dim=-1)

    @property
    def beta(self) -> torch.Tensor:
        """Gutenberg-Richter ``beta`` (= b ln 10)."""
        return torch.exp(self.log_beta)

    @property
    def alpha(self) -> torch.Tensor:
        """Productivity exponent, in ``[0, max_alpha_fraction * beta)``. The ETAS ``a``."""
        return self.beta * self.config.max_alpha_fraction * torch.sigmoid(self.alpha_raw)

    @property
    def branching_ratio(self) -> torch.Tensor:
        """Expected direct offspring per event, integrated over the mark law. Always below 1."""
        return self.config.max_branching_ratio * torch.sigmoid(self.branch_raw)

    @property
    def k0(self) -> torch.Tensor:
        """Productivity at ``m = mc``, derived so the branching ratio comes out as parameterised."""
        return self.branching_ratio * (self.beta - self.alpha) / self.beta

    def productivity(self, mw: torch.Tensor) -> torch.Tensor:
        """Expected direct offspring of each event: ``k0 exp(alpha (m - mc))``."""
        return self.k0 * torch.exp(self.alpha * (mw - self.mc_tensor))

    def set_mc(self, mc: float) -> None:
        self.register_buffer("mc_tensor", torch.tensor(float(mc), dtype=torch.float64))

    # ------------------------------------------------------------------ likelihood
    _delta_m: float = 0.1

    def set_delta_m(self, delta_m: float) -> None:
        """Magnitude bin width, used to place the GR lower edge at ``mc - delta_m / 2``."""
        self._delta_m = float(delta_m)

    def log_likelihood_terms(
        self,
        *,
        t: torch.Tensor,
        x: torch.Tensor,
        y: torch.Tensor,
        mw: torch.Tensor,
        features: torch.Tensor,
        window_start: float,
        window_end: float,
    ) -> dict[str, torch.Tensor]:
        """Differentiable pieces of the joint log-likelihood over ``[window_start, window_end)``.

        Every event in the arrays acts as a triggering source; only those inside the window are
        scored as targets. Events before ``window_start`` are the auxiliary (burn-in) history —
        the convention the ``etas`` package and EarthquakeNPP's ETAS configuration both use, and a
        departure from the neural baselines in that benchmark, which condition on as few as twenty
        prior events.

        The temporal / spatial factorisation is the benchmark's: ``lambda = lambda_t * f(x, y|t)``
        where ``lambda_t`` integrates the intensity over the plane. Because every basis element is
        a normalised density, ``lambda_t`` is exact rather than a quadrature.
        """
        if window_end <= window_start:
            msg = "window_end must be after window_start"
            raise ValueError(msg)
        w_time, w_space = self.kernel_weights(features)
        amp = self.productivity(mw)
        mu = torch.exp(self.log_mu)
        c, d = self.time_scales, self.space_scales
        p, s = self.config.omori_p, self.config.spatial_s

        target = torch.nonzero((t >= window_start) & (t < window_end), as_tuple=False).flatten()
        n_target = int(target.numel())
        if n_target == 0:
            msg = "no events inside the likelihood window"
            raise ValueError(msg)

        log_temporal: list[torch.Tensor] = []
        log_conditional_space: list[torch.Tensor] = []
        for start in range(0, n_target, TARGET_CHUNK):
            idx = target[start : start + TARGET_CHUNK]
            dt = t[idx].unsqueeze(1) - t.unsqueeze(0)
            causal = dt > 0.0
            h_mix = (omori_density(dt, c, p) * w_time.unsqueeze(0)).sum(-1) * causal
            temporal = torch.clamp(mu + (amp.unsqueeze(0) * h_mix).sum(-1), min=1e-300)
            r = torch.sqrt(
                (x[idx].unsqueeze(1) - x.unsqueeze(0)) ** 2
                + (y[idx].unsqueeze(1) - y.unsqueeze(0)) ** 2
            )
            g_mix = (powerlaw_density(r, d, s) * w_space.unsqueeze(0)).sum(-1)
            triggered = (amp.unsqueeze(0) * h_mix * g_mix).sum(-1)
            background = mu * self.background_density(x[idx], y[idx])
            full = torch.clamp(triggered + background, min=1e-300)
            log_temporal.append(torch.log(temporal))
            log_conditional_space.append(torch.log(full) - torch.log(temporal))

        # Compensator: background over the window plus each source's kernel mass inside it. Both
        # terms are closed form; nothing here is a Monte Carlo estimate.
        before_end = t < window_end
        lower = torch.clamp(torch.tensor(window_start, dtype=t.dtype) - t, min=0.0)
        upper = torch.clamp(torch.tensor(window_end, dtype=t.dtype) - t, min=0.0)
        integ = (omori_integral(lower, upper, c, p) * w_time).sum(-1)
        compensator = mu * (window_end - window_start) + (amp * integ * before_end).sum()
        mark = gr_log_density(
            mw[target], float(self.mc_tensor.item()) - self._delta_m / 2.0, self.log_beta
        ).sum()
        return {
            "sum_log_temporal": torch.cat(log_temporal).sum(),
            "sum_log_spatial": torch.cat(log_conditional_space).sum(),
            "compensator": compensator,
            "mark": mark,
            "n_events": torch.tensor(float(n_target), dtype=torch.float64),
        }

    def log_likelihood_tensor(self, **kwargs: Any) -> torch.Tensor:
        """Scalar joint log-likelihood, differentiable. What the optimiser maximises."""
        terms = self.log_likelihood_terms(**kwargs)
        return (
            terms["sum_log_temporal"]
            + terms["sum_log_spatial"]
            - terms["compensator"]
            + terms["mark"]
        )

    def log_likelihood(self, **kwargs: Any) -> LogLikelihood:
        """Reporting form: the benchmark's per-event temporal / spatial / mark split."""
        with torch.no_grad():
            terms = self.log_likelihood_terms(**kwargs)
        n = float(terms["n_events"].item())
        st = float(terms["sum_log_temporal"].item())
        ss = float(terms["sum_log_spatial"].item())
        comp = float(terms["compensator"].item())
        mark = float(terms["mark"].item())
        return LogLikelihood(
            total=st + ss - comp + mark,
            tll=(st - comp) / n,
            sll=ss / n,
            mll=mark / n,
            n_events=int(n),
            compensator=comp,
        )

    # ------------------------------------------------------------------ snapshot
    def weight_digest(self) -> str:
        """SHA-256 over every parameter and buffer, in a fixed order.

        This is what makes the protocol's snapshot-constancy check (§ 7 rule 4) meaningful for a
        model with thousands of weights: any change to any weight changes the digest, so a
        schedule that quietly retrained between windows fails.
        """
        parts: list[str] = []
        for name, tensor in sorted(self.state_dict().items()):
            flat = tensor.detach().to(torch.float64).reshape(-1).tolist()
            parts.append(name + "=" + ",".join(f"{v:.12e}" for v in flat))
        return sha256_hex("\n".join(parts))


def sequence_tensors(sequence: EventSequence, features: FeatureBuilder) -> dict[str, torch.Tensor]:
    """The tensors :meth:`NeuralKernelHawkes.log_likelihood` expects, from an event sequence."""
    return {
        "t": torch.tensor(sequence.t, dtype=torch.float64),
        "x": torch.tensor(sequence.x, dtype=torch.float64),
        "y": torch.tensor(sequence.y, dtype=torch.float64),
        "mw": torch.tensor(sequence.mw, dtype=torch.float64),
        "features": torch.tensor(
            features.transform(sequence.mw, sequence.depth_km), dtype=torch.float64
        ),
    }
