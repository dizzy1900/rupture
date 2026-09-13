"""Spatial magnitude of completeness: Mc(x) on a time window, not Mc(t) and not Mc(x, t).

ADR-0060 says completeness is a field with uncertainty, Mc(x, t). Helmstetter Mc(t) already
lives in :mod:`rupture.domain.completeness`. This module is the *spatial* product: a coarse
grid of cells, each of which either carries a named-estimator Mc or is explicitly unknown
(``mc=None``). It is not a space-time cube. Combining the two into Mc(x, t) is ADR-0067's
unbuilt remainder.

``lon`` / ``lat`` on a cell are the **south-west corner** (the cell origin), not the centre.
The cell covers ``[lon, lon + cell_size_deg)`` × ``[lat, lat + cell_size_deg)``. That is the
unambiguous convention for a regular lon/lat grid; a centre would require the reader to
reconstruct the origin.

A cell with too few events has ``mc=None``. Unknown is null, never a guessed Mc.

``McMethod`` lives here because the field product and the scalar :class:`CompletenessEstimate`
share it; :mod:`rupture.domain.catalog` re-exports the enum so existing imports keep working.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from rupture.domain.common import RuptureModel, UTCDatetime


class McMethod(StrEnum):
    """Completeness-magnitude estimators rupture reports."""

    MAXIMUM_CURVATURE = "maximum_curvature"  # Wiemer & Wyss 2000; +0.2 per Woessner & Wiemer 2005
    B_VALUE_STABILITY = "b_value_stability"  # Cao & Gao 2002
    MC_KS = "mc_ks"  # Mizrahi et al. 2021 (etas package cross-check)


class CompletenessCell(RuptureModel):
    """One grid cell of a spatial completeness field.

    ``lon`` and ``lat`` are the south-west corner of the cell (the origin). ``mc`` is the
    estimate from ``method`` or ``None`` when the cell is unknown. ``n_events`` is the number
    of earthquakes with homogenised Mw that fell in the cell and were offered to the estimator;
    events without Mw are excluded from this count and tallied on the parent field's notes.
    """

    lon: float = Field(ge=-180.0, le=180.0, description="South-west corner longitude (cell origin).")
    lat: float = Field(ge=-90.0, le=90.0, description="South-west corner latitude (cell origin).")
    mc: float | None = Field(
        default=None,
        ge=0.0,
        le=9.0,
        description="Mc in this cell, or None when unknown (too few events, or the method refused).",
    )
    n_events: int = Field(ge=0, description="Earthquakes with homogenised Mw in this cell.")
    method: McMethod
    mc_low: float | None = Field(
        default=None,
        ge=0.0,
        le=9.0,
        description="Lower end of an optional interval; None when no interval is claimed.",
    )
    mc_high: float | None = Field(
        default=None,
        ge=0.0,
        le=9.0,
        description="Upper end of an optional interval; None when no interval is claimed.",
    )

    @model_validator(mode="after")
    def _unknown_is_null(self) -> CompletenessCell:
        if self.n_events == 0 and self.mc is not None:
            msg = "a cell with no events cannot have an Mc"
            raise ValueError(msg)
        if self.mc is None and (self.mc_low is not None or self.mc_high is not None):
            msg = "unknown Mc cannot carry an interval"
            raise ValueError(msg)
        if (self.mc_low is None) != (self.mc_high is None):
            msg = "mc_low and mc_high must both be set or both be None"
            raise ValueError(msg)
        if (
            self.mc_low is not None
            and self.mc_high is not None
            and self.mc_low > self.mc_high
        ):
            msg = "mc_low must be <= mc_high"
            raise ValueError(msg)
        return self


class CompletenessField(RuptureModel):
    """Mc(x) on a declared time window: a grid, an estimator, and a provenance trail.

    ``is_scalar_only`` is the ADR-0060 label: True means this object is a degenerate stand-in
    for a scalar CompletenessEstimate, not a spatial field, and must not be silently read as
    Mc(x). Estimators that actually bin space set it False even when every cell is unknown.
    """

    region_id: str | None = None
    cell_size_deg: float = Field(gt=0.0)
    cells: tuple[CompletenessCell, ...] = ()
    estimator: str = Field(min_length=1, description="Named Mc estimator used for every cell.")
    window_start: UTCDatetime
    window_end: UTCDatetime
    computed_at: UTCDatetime
    notes: str | None = Field(
        default=None,
        description="Provenance and exclusions (events without Mw, cutoff, circularity caveat).",
    )
    is_scalar_only: bool = False

    @model_validator(mode="after")
    def _window_ordered(self) -> CompletenessField:
        if self.window_start > self.window_end:
            msg = "window_start must be at or before window_end"
            raise ValueError(msg)
        return self
