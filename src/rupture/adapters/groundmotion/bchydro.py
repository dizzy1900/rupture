"""Abrahamson, Gregor & Addo — the "BC Hydro" subduction GSIM, interface branch.

    Abrahamson, N., Gregor, N. and Addo, K. (2016). BC Hydro ground motion model for subduction
    earthquakes. *Earthquake Spectra* 32(1), 23-44. doi:10.1193/051712EQS188MR
    (title abbreviated as ``docs/RISK.md`` explains; the DOI is authoritative)

Implemented here for **subduction interface** events with the central magnitude-scaling branch
(``DeltaC1`` central), which is OpenQuake's ``AbrahamsonEtAl2015SInter``. The in-slab branch, the
high/low ``DeltaC1`` branches and the ESHM20 forearc-backarc tapering are deliberately not
implemented: nothing in rupture uses them, and an unverified branch is not shipped (ADR-0020).

Applicability to the Main Himalayan Thrust is a modelling judgement, not a property of this file;
it is argued, with its limitations, in ``docs/adr/0025`` and ``docs/RISK.md``. Verified against
OpenQuake's committed expected values (``BCHYDRO/BCHYDRO_SINTER_CENTRAL_*.csv``).
"""

from __future__ import annotations

import numpy as np

from rupture.adapters.groundmotion import coeffs
from rupture.adapters.groundmotion.base import FloatArray, GsimContext, GsimResult
from rupture.adapters.groundmotion.imt import PGA, Imt

COEFFS_FILE = "bchydro_sinter_coeffs.txt"
DC1_FILE = "bchydro_sinter_dc1.txt"

# Period-independent coefficients, table 2 of the paper.
N = 1.18
C = 1.88
THETA3 = 0.1
THETA4 = 0.9
THETA5 = 0.0
THETA9 = 0.4
C4 = 10.0
C1_MAG = 7.8
V_ROCK = 1000.0
FABA_MIN_DIST_KM = 100.0

REFERENCE = (
    "Abrahamson, N., Gregor, N. & Addo, K. (2016). BC Hydro ground motion model for subduction "
    "earthquakes. Earthquake Spectra 32(1), 23-44. doi:10.1193/051712EQS188MR "
    "[title abbreviated; see docs/RISK.md]"
)


def _magnitude_term(c: dict[str, float], dc1: float, mag: float) -> float:
    """Equation 2, with the DeltaC1 epistemic adjustment applied to the hinge magnitude."""
    base = c["theta1"] + THETA4 * dc1
    hinge = C1_MAG + dc1
    slope = THETA5 if mag > hinge else THETA4
    return base + slope * (mag - hinge) + c["theta13"] * (10.0 - mag) ** 2


def _distance_term(c: dict[str, float], mag: float, rrup: FloatArray) -> FloatArray:
    """The interface distance scaling inside equation 1 (theta10 and theta14 are zero here)."""
    part1 = c["theta2"] + THETA3 * (mag - C1_MAG)
    part2 = np.log(rrup + C4 * np.exp((mag - 6.0) * THETA9))
    result: FloatArray = part1 * part2 + c["theta6"] * rrup
    return result


def _faba_term(c: dict[str, float], rrup: FloatArray, backarc: np.ndarray) -> FloatArray:
    """Forearc/back-arc term: zero at forearc sites, equation 4 at back-arc sites."""
    out = np.zeros_like(rrup)
    if not backarc.any():
        return out
    clipped = np.maximum(rrup[backarc], FABA_MIN_DIST_KM)
    out[backarc] = c["theta15"] + c["theta16"] * np.log(clipped / 40.0)
    return out


def _site_response(c: dict[str, float], vs30: FloatArray, pga1000: FloatArray) -> FloatArray:
    """Equation 5: the Walling et al. (2008) / Abrahamson & Silva (2008) site-response form."""
    vs_star = np.minimum(vs30, V_ROCK)
    arg = vs_star / c["vlin"]
    out = c["theta12"] * np.log(arg)
    linear = vs30 >= c["vlin"]
    out[linear] += c["b"] * N * np.log(arg[linear])
    nonlinear = ~linear
    out[nonlinear] += -c["b"] * np.log(pga1000[nonlinear] + C) + c["b"] * np.log(
        pga1000[nonlinear] + C * arg[nonlinear] ** N
    )
    return out


class AbrahamsonEtAl2015SInter:
    """BC Hydro, subduction interface, central DeltaC1, ergodic sigma."""

    name: str = "AbrahamsonEtAl2015SInter"
    tectonic_region: str = "Subduction Interface"
    reference: str = REFERENCE
    requires_distances: tuple[str, ...] = ("rrup",)
    requires_site_parameters: tuple[str, ...] = ("vs30", "backarc")

    def __init__(self, *, ergodic: bool = True) -> None:
        self.ergodic = ergodic
        self._coeffs = coeffs.load(COEFFS_FILE)
        self._dc1 = coeffs.load(DC1_FILE)

    def supports(self, imt: Imt) -> bool:
        return self._coeffs.supports(imt) and self._dc1.supports(imt)

    def compute(self, ctx: GsimContext, imt: Imt) -> GsimResult:
        c_pga = self._coeffs[PGA]
        dc1_pga = self._dc1[PGA]["dc1"]
        rock = (
            _magnitude_term(c_pga, dc1_pga, ctx.mag)
            + _distance_term(c_pga, ctx.mag, ctx.rrup)
            + _faba_term(c_pga, ctx.rrup, ctx.backarc)
            + (c_pga["theta12"] + c_pga["b"] * N) * np.log(V_ROCK / c_pga["vlin"])
        )
        pga1000 = np.exp(rock)

        c = self._coeffs[imt]
        dc1 = self._dc1[imt]["dc1"]
        mean_ln = (
            _magnitude_term(c, dc1, ctx.mag)
            + _distance_term(c, ctx.mag, ctx.rrup)
            + _faba_term(c, ctx.rrup, ctx.backarc)
            + _site_response(c, ctx.vs30, pga1000)
        )
        tau = np.full_like(ctx.vs30, c["tau"])
        if self.ergodic:
            sigma = np.full_like(ctx.vs30, c["sigma"])
            phi = np.full_like(ctx.vs30, c["phi"])
        else:
            sigma = np.full_like(ctx.vs30, c["sigma_ss"])
            phi = np.sqrt(sigma**2 - tau**2)
        return GsimResult(mean_ln=mean_ln, tau=tau, phi=phi, sigma=sigma)
