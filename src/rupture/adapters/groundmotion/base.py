"""What a native GSIM is given and what it returns.

A GSIM here is a pure function of a rupture, a set of sites and an intensity measure type. It
returns the natural logarithm of the median ground motion together with the inter-event (tau),
intra-event (phi) and total standard deviations, all in natural-log units, exactly as the
published equations define them. Nothing in this module fetches, samples or writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

from rupture.adapters.groundmotion.imt import Imt

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


class GsimError(ValueError):
    """The GSIM cannot be evaluated for this input."""


@dataclass(frozen=True, slots=True)
class GsimContext:
    """Rupture-level scalars plus one value per site for every site and distance parameter.

    ``ztor`` is the depth to the top of rupture (km) and ``rhypo`` the hypocentral distance;
    both are carried even when the GSIM in hand does not use them, because the cross-check
    between engines compares the same context.
    """

    mag: float
    rake: float
    hypo_depth: float
    ztor: float
    rjb: FloatArray
    rrup: FloatArray
    rx: FloatArray
    rhypo: FloatArray
    vs30: FloatArray
    backarc: BoolArray
    z1pt0: FloatArray | None = None

    def __post_init__(self) -> None:
        n = self.vs30.size
        for name in ("rjb", "rrup", "rx", "rhypo", "backarc"):
            value: FloatArray | BoolArray = getattr(self, name)
            if value.size != n:
                msg = f"{name} has {value.size} values but there are {n} sites"
                raise GsimError(msg)
        if self.z1pt0 is not None and self.z1pt0.size != n:
            msg = f"z1pt0 has {self.z1pt0.size} values but there are {n} sites"
            raise GsimError(msg)

    @property
    def n_sites(self) -> int:
        return int(self.vs30.size)


@dataclass(frozen=True, slots=True)
class GsimResult:
    """Median and dispersion, in natural-log units of the IMT's own unit."""

    mean_ln: FloatArray
    tau: FloatArray
    phi: FloatArray
    sigma: FloatArray


@runtime_checkable
class Gsim(Protocol):
    """One published ground-shaking intensity model, verified against OpenQuake's own vectors."""

    name: str
    """rupture's identifier, which is OpenQuake's class name, e.g. ``BooreEtAl2014``."""
    tectonic_region: str
    reference: str
    """Full citation of the published model."""
    requires_distances: tuple[str, ...]
    requires_site_parameters: tuple[str, ...]

    def supports(self, imt: Imt) -> bool: ...

    def compute(self, ctx: GsimContext, imt: Imt) -> GsimResult: ...
