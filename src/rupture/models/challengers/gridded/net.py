"""The C1b network: a small ConvLSTM over rasterised seismicity history plus static covariates.

Deliberately small. The brief is a CPU-sized run, and the training signal is thin: at the
regional completeness magnitude a 30-day frame holds one or two events across a few thousand
cells, so a large network would memorise the aftershock sequences in the training block and learn
nothing transferable. One ConvLSTM layer with 8-16 hidden channels and a two-layer head is the
whole model — of the order of ten thousand parameters.

Two choices matter more than the architecture:

* **The head is initialised to zero**, and its output is *added* to a climatological log-rate
  computed from pre-cutoff seismicity. An untrained network therefore issues exactly the smoothed
  historical rate, and training only ever learns the departure from it. This is the difference
  between a model that starts somewhere sensible and one that spends its small data budget
  rediscovering where earthquakes happen.
* **The loss is the Poisson negative log-likelihood** on cell counts, which is the quantity the
  CSEP likelihood tests score. Nothing is trained on a surrogate.

the network outputs a log rate per cell.
"""

from __future__ import annotations

import hashlib

import torch
from torch import Tensor, nn

LOG_RATE_MIN = -30.0
LOG_RATE_MAX = 6.0


class ConvLSTMCell(nn.Module):
    """One ConvLSTM step (Shi et al. 2015): gates from a convolution over ``[input, hidden]``."""

    def __init__(self, in_channels: int, hidden_channels: int, kernel_size: int = 3) -> None:
        super().__init__()
        self.hidden_channels = hidden_channels
        self.conv = nn.Conv2d(
            in_channels + hidden_channels,
            4 * hidden_channels,
            kernel_size,
            padding=kernel_size // 2,
        )

    def forward(self, x: Tensor, state: tuple[Tensor, Tensor]) -> tuple[Tensor, Tensor]:
        h, c = state
        gates = self.conv(torch.cat([x, h], dim=1))
        i, f, g, o = torch.chunk(gates, 4, dim=1)
        c_next = torch.sigmoid(f) * c + torch.sigmoid(i) * torch.tanh(g)
        h_next = torch.sigmoid(o) * torch.tanh(c_next)
        return h_next, c_next


class GriddedRateNet(nn.Module):
    """``(dynamic frames, static covariates, climatological log-rate) -> log rate per cell``."""

    def __init__(
        self,
        *,
        n_dynamic: int,
        n_static: int,
        hidden_channels: int = 16,
        kernel_size: int = 3,
    ) -> None:
        super().__init__()
        self.n_dynamic = n_dynamic
        self.n_static = n_static
        self.hidden_channels = hidden_channels
        self.cell = ConvLSTMCell(n_dynamic + n_static, hidden_channels, kernel_size)
        self.head = nn.Sequential(
            nn.Conv2d(
                hidden_channels + n_static, hidden_channels, kernel_size, padding=kernel_size // 2
            ),
            nn.ReLU(),
            nn.Conv2d(hidden_channels, 1, 1),
        )
        self.log_scale = nn.Parameter(torch.zeros(1))
        final = self.head[-1]
        if not isinstance(final, nn.Conv2d) or final.bias is None:  # pragma: no cover - defensive
            msg = "the head must end in a Conv2d with a bias"
            raise TypeError(msg)
        nn.init.zeros_(final.weight)
        nn.init.zeros_(final.bias)

    def forward(self, dynamic: Tensor, static: Tensor, log_prior: Tensor) -> Tensor:
        """``dynamic`` (B, T, Cd, H, W), ``static`` (B, Cs, H, W), ``log_prior`` (B, H, W)."""
        b, t, _, h, w = dynamic.shape
        state = (
            dynamic.new_zeros((b, self.hidden_channels, h, w)),
            dynamic.new_zeros((b, self.hidden_channels, h, w)),
        )
        for k in range(t):
            state = self.cell(torch.cat([dynamic[:, k], static], dim=1), state)
        delta = self.head(torch.cat([state[0], static], dim=1)).squeeze(1)
        return torch.clamp(log_prior + self.log_scale + delta, LOG_RATE_MIN, LOG_RATE_MAX)


def poisson_nll(log_rate: Tensor, counts: Tensor, mask: Tensor) -> Tensor:
    """Sum over in-region cells of ``lambda - n log lambda`` (constant terms dropped)."""
    rate = torch.exp(log_rate)
    per_cell = rate - counts * log_rate
    return (per_cell * mask).sum()


def weights_sha256(module: nn.Module) -> str:
    """Stable hash of the trained weights: parameter names and float32 bytes, in sorted order."""
    digest = hashlib.sha256()
    for name, tensor in sorted(module.state_dict().items()):
        digest.update(name.encode("utf-8"))
        digest.update(tensor.detach().to(torch.float32).contiguous().numpy().tobytes())
    return digest.hexdigest()
