"""Finite-fault / slip field sampled onto a forecast lattice.

Mignan & Broccardo's third parameter was log mean slip of the source. Across a pooled set of
ruptures that scalar varies by mainshock and is identified; on a single sequence it is absorbed
into the intercept. This type is the per-cell sampling of a finite-fault slip model onto the
forecast lattice, which *does* vary in space on one grid. Unknowns are not imputed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt

from rupture.models.comparators.errors import MissingSlipFieldError
from rupture.models.data.geo import Projection

if TYPE_CHECKING:
    from collections.abc import Sequence

_F8 = npt.NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class SlipField:
    """Mean slip (metres) at each forecast cell, in lattice order.

    ``cell_origins`` are the lower-left corners of the same squares :class:`ForecastGrid` uses.
    Every value must be finite and strictly positive: a missing sub-fault is a missing field, not
    a zero to take the log of.
    """

    cell_origins: tuple[tuple[float, float], ...]
    mean_slip_m: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.mean_slip_m) != len(self.cell_origins):
            msg = (
                f"slip field has {len(self.mean_slip_m)} slip value(s) and "
                f"{len(self.cell_origins)} cell(s); they must match the forecast lattice"
            )
            raise MissingSlipFieldError(msg)
        if not self.cell_origins:
            msg = "slip field has no cells"
            raise MissingSlipFieldError(msg)
        for i, value in enumerate(self.mean_slip_m):
            if not math.isfinite(value) or value <= 0.0:
                lon, lat = self.cell_origins[i]
                msg = (
                    "finite-fault / slip field is missing a usable mean_slip_m at cell "
                    f"{i} ({lon}, {lat}): got {value!r}. Unknowns are not imputed and non-positive "
                    "slip is not logged."
                )
                raise MissingSlipFieldError(msg)

    def as_array(self) -> _F8:
        return np.asarray(self.mean_slip_m, dtype=np.float64)


def slip_field_from_subfaults(
    cell_origins: tuple[tuple[float, float], ...],
    cell_size_deg: float,
    subfault_lons: Sequence[float],
    subfault_lats: Sequence[float],
    subfault_slip_m: Sequence[float],
    *,
    projection: Projection | None = None,
) -> SlipField:
    """Nearest-subfault sampling of a finite-fault table onto the lattice.

    Each cell centre takes the slip of the nearest sub-fault with strictly positive slip. A table
    with no positive slip is a missing field.
    """
    lons = np.asarray(subfault_lons, dtype=np.float64)
    lats = np.asarray(subfault_lats, dtype=np.float64)
    slips = np.asarray(subfault_slip_m, dtype=np.float64)
    if lons.shape != lats.shape or lons.shape != slips.shape:
        msg = "sub-fault lon, lat and slip arrays must have the same shape"
        raise MissingSlipFieldError(msg)
    positive = np.isfinite(slips) & (slips > 0.0)
    if not np.any(positive):
        msg = (
            "finite-fault / slip field has no strictly positive sub-fault slip; the "
            "three-parameter logistic cannot be identified from an empty table"
        )
        raise MissingSlipFieldError(msg)
    lons, lats, slips = lons[positive], lats[positive], slips[positive]
    if projection is None:
        lon0 = float(np.mean([lon for lon, _ in cell_origins]))
        lat0 = float(np.mean([lat for _, lat in cell_origins]))
        projection = Projection(lon0=lon0, lat0=lat0)
    half = cell_size_deg / 2.0
    cell_lon = np.asarray([lon + half for lon, _ in cell_origins], dtype=np.float64)
    cell_lat = np.asarray([lat + half for _, lat in cell_origins], dtype=np.float64)
    cx, cy = projection.forward(cell_lon, cell_lat)
    sx, sy = projection.forward(lons, lats)
    dx = cx[:, None] - sx[None, :]
    dy = cy[:, None] - sy[None, :]
    nearest = np.argmin(dx * dx + dy * dy, axis=1)
    sampled = slips[nearest]
    return SlipField(
        cell_origins=cell_origins,
        mean_slip_m=tuple(float(v) for v in sampled),
    )
