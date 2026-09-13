"""Three-parameter logistic on log-distance and log mean slip.

This is the sibling of :class:`~rupture.models.comparators.logistic.OneNeuronAftershockModel`
that Mignan & Broccardo reported at 0.86 on the pooled cells of DeVries et al. 2018 Nature doi
10.1038/s41586-018-0438-y — `rebutted`; Meade et al. Reply Nature 574 E4-E5 doi
10.1038/s41586-019-1583-7 is on the record. It will not silently drop the slip feature:
construction without a :class:`SlipField` raises
:class:`~rupture.models.comparators.errors.MissingSlipFieldError` naming the finite-fault /
slip field that is missing.

On a single sequence a spatially constant mean slip is collinear with the intercept; the
:class:`SlipField` must vary by cell (a finite-fault model sampled onto the lattice).
"""

from __future__ import annotations

from rupture.models.comparators._fit import DISTANCE_FLOOR_KM
from rupture.models.comparators.errors import MissingSlipFieldError
from rupture.models.comparators.logistic import OneNeuronAftershockModel
from rupture.models.comparators.slip import SlipField

MODEL_ID = "distance-slip-logistic"
MODEL_VERSION = "0.1.0"


class DistanceSlipAftershockModel(OneNeuronAftershockModel):
    """Three-parameter logistic. A slip field is required, not optional."""

    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION

    def __init__(
        self,
        *,
        slip_field: SlipField | None = None,
        m_main: float = 6.0,
        distance_floor_km: float = DISTANCE_FLOOR_KM,
        mc: float | None = None,
    ) -> None:
        if slip_field is None:
            msg = (
                "distance-slip-logistic requires a finite-fault / slip field (SlipField with "
                "mean_slip_m per lattice cell); none was supplied. It will not fall back to the "
                "two-parameter distance logistic."
            )
            raise MissingSlipFieldError(msg)
        super().__init__(
            m_main=m_main,
            distance_floor_km=distance_floor_km,
            slip_field=slip_field,
            mc=mc,
            require_slip=True,
        )
