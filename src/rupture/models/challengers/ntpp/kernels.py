"""Triggering-kernel bases for the neural point process, and their exact integrals.

The model's conditional intensity is a Hawkes process whose triggering kernel is a **mixture over
fixed basis functions with neural mixture weights**. The bases are chosen so that every integral
the log-likelihood needs is available in closed form:

- **time** — modified-Omori densities on ``(0, inf)``,
  ``h_c(dt) = (p - 1) / c * (1 + dt / c)^-p``, one per characteristic time ``c``. Each integrates
  to 1 over ``(0, inf)`` for ``p > 1``, and its integral over ``[a, b]`` is a difference of two
  powers. This is the ETAS temporal kernel; using a *mixture* of them with learned, mark-dependent
  weights is the generalisation.
- **space** — isotropic power-law densities on ``R^2``,
  ``q_d(r) = (s - 1) / (pi d^2) * (1 + r^2 / d^2)^-s``, one per characteristic distance ``d``.
  Each integrates to 1 over the plane for ``s > 1``, its mass inside radius ``R`` is closed form,
  and it can be sampled by inverting that expression.

Because each basis element is a normalised density, a convex mixture of them is a normalised
density too, and the compensator of the whole process is a sum of scalars rather than a numerical
quadrature. That matters more than it sounds: an approximate compensator is a silent way to
manufacture likelihood, and the point of this exercise is to *not* manufacture anything.

Exponents ``p`` and ``s`` are fixed hyperparameters, not learned. Learning them alongside the
mixture weights makes the parameterisation badly non-identifiable on a few hundred events.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import torch

_F8 = npt.NDArray[np.float64]

# Smallest inter-event time the temporal kernel is evaluated at (~0.09 s). Real catalogues carry
# rounded origin times, so exact ties happen; without a floor the density diverges.
MIN_DT_DAYS = 1e-6


def geometric_scales(low: float, high: float, n: int) -> _F8:
    """``n`` characteristic scales spaced geometrically over ``[low, high]``."""
    if n < 1:
        msg = "need at least one basis element"
        raise ValueError(msg)
    if not (0.0 < low <= high):
        msg = "scales must satisfy 0 < low <= high"
        raise ValueError(msg)
    if n == 1:
        out: _F8 = np.array([float(np.sqrt(low * high))], dtype=np.float64)
        return out
    return np.geomspace(low, high, n, dtype=np.float64)


# ---------------------------------------------------------------------- temporal basis
def omori_density(dt: torch.Tensor, c: torch.Tensor, p: float) -> torch.Tensor:
    """``h_c(dt)`` for each ``(…, 1)`` delay against each ``(n_basis,)`` scale; shape ``(…, n)``."""
    d = torch.clamp(dt, min=MIN_DT_DAYS).unsqueeze(-1)
    return (p - 1.0) / c * torch.pow(1.0 + d / c, -p)


def omori_integral(a: torch.Tensor, b: torch.Tensor, c: torch.Tensor, p: float) -> torch.Tensor:
    """``int_a^b h_c`` for delays ``a <= b``; shape ``(…, n_basis)``. Exact, not quadrature."""
    lo = torch.clamp(a, min=0.0).unsqueeze(-1)
    hi = torch.clamp(b, min=0.0).unsqueeze(-1)
    hi = torch.maximum(hi, lo)
    return torch.pow(1.0 + lo / c, -(p - 1.0)) - torch.pow(1.0 + hi / c, -(p - 1.0))


def sample_omori(u: npt.NDArray[np.float64], c: _F8, p: float, *, upper: _F8 | None = None) -> _F8:
    """Inverse-CDF sample of the Omori density, optionally truncated to ``[0, upper]``.

    ``u`` are uniforms in ``[0, 1)``. With ``upper`` given the draw is conditioned on falling
    inside the window, which is what a forecast over a finite horizon needs.
    """
    mass = 1.0 if upper is None else 1.0 - (1.0 + upper / c) ** (-(p - 1.0))
    uu = np.clip(u * mass, 0.0, 1.0 - 1e-12)
    out: _F8 = c * ((1.0 - uu) ** (-1.0 / (p - 1.0)) - 1.0)
    return out


# ---------------------------------------------------------------------- spatial basis
def powerlaw_density(r: torch.Tensor, d: torch.Tensor, s: float) -> torch.Tensor:
    """``q_d(r)`` per unit area for each ``(…, 1)`` distance and ``(n_basis,)`` scale."""
    rr = r.unsqueeze(-1)
    d2 = d * d
    return (s - 1.0) / (np.pi * d2) * torch.pow(1.0 + (rr * rr) / d2, -s)


def powerlaw_mass_within(radius: float, d: _F8, s: float) -> _F8:
    """Probability mass of ``q_d`` inside ``radius``. Used to report the edge effect ignored."""
    out: _F8 = 1.0 - (1.0 + (radius**2) / (d**2)) ** (-(s - 1.0))
    return out


def sample_powerlaw_radius(u: npt.NDArray[np.float64], d: _F8, s: float) -> _F8:
    """Inverse-CDF sample of the radial marginal of ``q_d`` (``u`` uniform in ``[0, 1)``)."""
    uu = np.clip(u, 0.0, 1.0 - 1e-12)
    out: _F8 = d * np.sqrt((1.0 - uu) ** (-1.0 / (s - 1.0)) - 1.0)
    return out


# ---------------------------------------------------------------------- magnitudes
def gr_log_density(mw: torch.Tensor, mc_lower: float, log_beta: torch.Tensor) -> torch.Tensor:
    """Log Gutenberg-Richter density for magnitudes at or above ``mc_lower``.

    The mark distribution is independent of time and place, as in ETAS. That is a modelling
    choice, not a finding; it is what makes the magnitude term separable from the kernel fit.
    """
    beta = torch.exp(log_beta)
    return log_beta - beta * (mw - mc_lower)
