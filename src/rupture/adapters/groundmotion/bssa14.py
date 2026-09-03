"""Boore, Stewart, Seyhan & Atkinson (2014) — "BSSA14", an NGA-West2 active-crustal GSIM.

    Boore, D.M., Stewart, J.P., Seyhan, E. and Atkinson, G.M. (2014). NGA-West2 equations for
    PGA, PGV and 5 % damped PSA for shallow crustal earthquakes. *Earthquake Spectra* 30(3),
    1057-1085. doi:10.1193/070113EQS184M

(Titles throughout rupture are given in the abbreviated form explained in ``docs/RISK.md``: the
published titles of both shipped GSIM papers contain a word the banned-language gate forbids, so
the DOI is the authoritative identifier.)

Implemented here in the "global, no basin term" configuration, which is the model's default and
the one OpenQuake's ``BooreEtAl2014`` uses with ``region='nobasin'``: the anelastic-attenuation
regional adjustment ``Dc3`` is zero and the basin depth term is switched off, so ``z1pt0`` is not
required. Style of faulting is taken from the rake (``sof=True``) unless ``sof=False`` selects the
unspecified-mechanism coefficient ``e0``.

Equation numbers below are the paper's. Verified against OpenQuake's committed expected values
(``BSSA2014/BSSA_2014_*.csv``); see :mod:`tests.unit.risk.test_gsim_verification` for the
tolerances actually achieved and ``docs/RISK.md`` for the table.
"""

from __future__ import annotations

import numpy as np

from rupture.adapters.groundmotion import coeffs
from rupture.adapters.groundmotion.base import FloatArray, GsimContext, GsimResult
from rupture.adapters.groundmotion.imt import PGA, Imt

COEFFS_FILE = "bssa14_coeffs.txt"

M_REF = 4.5
R_REF = 1.0
V_REF = 760.0
F1 = 0.0
F3 = 0.1
V1 = 225.0
V2 = 300.0

REFERENCE = (
    "Boore, D.M., Stewart, J.P., Seyhan, E. & Atkinson, G.M. (2014). NGA-West2 equations for "
    "PGA, PGV and 5 % damped PSA for shallow crustal earthquakes. Earthquake Spectra "
    "30(3), 1057-1085. doi:10.1193/070113EQS184M [title abbreviated; see docs/RISK.md]"
)


def _style_of_faulting(c: dict[str, float], rake: float) -> float:
    """Equation 2's mechanism term. Rake within 30 deg of horizontal is strike-slip."""
    if abs(rake) <= 30.0 or (180.0 - abs(rake)) <= 30.0:
        return c["e1"]
    if 30.0 < rake < 150.0:
        return c["e3"]
    return c["e2"]


def _magnitude_scaling(c: dict[str, float], mag: float, *, sof: bool, rake: float) -> float:
    """Equation 2."""
    dmag = mag - c["Mh"]
    term = c["e4"] * dmag + c["e5"] * dmag**2 if mag <= c["Mh"] else c["e6"] * dmag
    base = _style_of_faulting(c, rake) if sof else c["e0"]
    return base + term


def _path_scaling(c: dict[str, float], mag: float, rjb: FloatArray) -> FloatArray:
    """Equation 3, with the regional anelastic adjustment ``Dc3`` from the coefficient table."""
    rval = np.sqrt(rjb**2 + c["h"] ** 2)
    geometric = (c["c1"] + c["c2"] * (mag - M_REF)) * np.log(rval / R_REF)
    return geometric + (c["c3"] + c["Dc3"]) * (rval - R_REF)


def _linear_site(c: dict[str, float], vs30: FloatArray) -> FloatArray:
    """Equation 6."""
    flin = vs30 / V_REF
    flin = np.where(vs30 > c["Vc"], c["Vc"] / V_REF, flin)
    result: FloatArray = c["c"] * np.log(flin)
    return result


def _nonlinear_site(c: dict[str, float], vs30: FloatArray, pga_rock: FloatArray) -> FloatArray:
    """Equations 7 and 8."""
    v_s = np.minimum(vs30, 760.0)
    f_2 = c["f4"] * (np.exp(c["f5"] * (v_s - 360.0)) - np.exp(c["f5"] * 400.0))
    result: FloatArray = F1 + f_2 * np.log((pga_rock + F3) / F3)
    return result


def _tau(c: dict[str, float], mag: float) -> float:
    """Equation 14: inter-event standard deviation, linear in magnitude between 4.5 and 5.5."""
    if mag <= 4.5:
        return c["tau1"]
    if mag >= 5.5:
        return c["tau2"]
    return c["tau1"] + (c["tau2"] - c["tau1"]) * (mag - 4.5)


def _phi(c: dict[str, float], mag: float, rjb: FloatArray, vs30: FloatArray) -> FloatArray:
    """Equations 15-17: intra-event standard deviation, dependent on magnitude, Rjb and Vs30.

    The order of the three adjustments is the reference implementation's, and matters at the
    exact breakpoints ``Vs30 = 225`` and ``Vs30 = 300``, where two branches both apply.
    """
    if mag <= 4.5:
        value = c["f1"]
    elif mag >= 5.5:
        value = c["f2"]
    else:
        value = c["f1"] + (c["f2"] - c["f1"]) * (mag - 4.5)
    out = np.full_like(rjb, value)

    far = rjb > c["R2"]
    out[far] += c["DfR"]
    mid = (rjb > c["R1"]) & (rjb <= c["R2"])
    out[mid] += c["DfR"] * (np.log(rjb[mid] / c["R1"]) / np.log(c["R2"] / c["R1"]))

    soft = vs30 <= V1
    out[soft] -= c["DfV"]
    taper = (vs30 >= V1) & (vs30 <= V2)
    out[taper] -= c["DfV"] * (np.log(V2 / vs30[taper]) / np.log(V2 / V1))
    return out


class BooreEtAl2014:
    """BSSA14, global Q, no basin term."""

    tectonic_region: str = "Active Shallow Crust"
    reference: str = REFERENCE
    requires_distances: tuple[str, ...] = ("rjb",)
    requires_site_parameters: tuple[str, ...] = ("vs30",)

    def __init__(self, *, sof: bool = True) -> None:
        self.sof = sof
        self.name = "BooreEtAl2014" if sof else "BooreEtAl2014(sof=False)"
        self._coeffs = coeffs.load(COEFFS_FILE)

    def supports(self, imt: Imt) -> bool:
        return self._coeffs.supports(imt)

    def compute(self, ctx: GsimContext, imt: Imt) -> GsimResult:
        c_pga = self._coeffs[PGA]
        c = self._coeffs[imt]
        pga_rock = np.exp(
            _magnitude_scaling(c_pga, ctx.mag, sof=self.sof, rake=ctx.rake)
            + _path_scaling(c_pga, ctx.mag, ctx.rjb)
        )
        mean_ln = (
            _magnitude_scaling(c, ctx.mag, sof=self.sof, rake=ctx.rake)
            + _path_scaling(c, ctx.mag, ctx.rjb)
            + _linear_site(c, ctx.vs30)
            + _nonlinear_site(c, ctx.vs30, pga_rock)
        )
        tau = np.full_like(ctx.vs30, _tau(c, ctx.mag))
        phi = _phi(c, ctx.mag, ctx.rjb, ctx.vs30)
        return GsimResult(mean_ln=mean_ln, tau=tau, phi=phi, sigma=np.sqrt(tau**2 + phi**2))
