"""Observation types below the catalogue: GNSS positions, picks, and product latency.

A catalogue is a lossy summary. The prediction programme needs the continuous observations
that summary threw away, and it needs them with both clocks: ``valid_time`` (when the
phenomenon refers to) and ``available_time`` (when *this value in this revision* was readable
from the source). ``available_time`` is required and has no default. A source that cannot
supply it must refuse, not guess (ADR-0054).

This module is the data port that later adjudication (for example Bletery & Nocquet-style
GNSS tests) will read. It is not that adjudication, and a GNSS position is not a prediction.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import Field, field_validator

from rupture.domain.common import Provenance, RuptureModel, UTCDatetime


class ObservableKind(StrEnum):
    """What an observation is of. Extended by adding a member, never by a free-text field."""

    CATALOGUE_EVENT = "catalogue_event"
    COMPLETENESS_FIELD = "completeness_field"
    GNSS_POSITION = "gnss_position"
    INSAR_DISPLACEMENT = "insar_displacement"
    CONTINUOUS_WAVEFORM = "continuous_waveform"
    WAVEFORM_PICK = "waveform_pick"
    DAS_STRAIN = "das_strain"
    TREMOR_RATE = "tremor_rate"
    TILT = "tilt"
    BOREHOLE_STRAIN = "borehole_strain"
    SLIP_INVERSION = "slip_inversion"


class GnssProduct(StrEnum):
    """NGL / IGS product tier. Rapid is superseded by final; they are not interchangeable."""

    RAPID = "rapid"
    FINAL = "final"


class ProductVintage(RuptureModel):
    """Nominal lag from ``valid_time`` to ``available_time`` for one product of one source.

    The lag numbers are *documented by the provider* until Rupture measures them against its
    own snapshot series. Mixing the two in a published table is a citation error.
    """

    product_id: str
    nominal_lag: timedelta = Field(description="Documented valid_time -> available_time lag.")
    evidence: str = Field(
        description=(
            "How the lag was obtained. 'documented:<url>' when taken from the provider and "
            "never measured here; 'measured:<report>' when Rupture measured it."
        )
    )


class LatencyModel(RuptureModel):
    """Per-source product tiers and their nominal availability lags (ADR-0054 decision 4)."""

    source_id: str
    products: tuple[ProductVintage, ...]
    default_product_id: str


class GnssPosition(RuptureModel):
    """One daily (or sub-daily) GNSS position in a local east-north-up frame, with both times.

    ``east_m`` / ``north_m`` / ``up_m`` are the reconstructed tenv3 coordinates (integer portion
    plus fractional portion, metres). ``available_time`` has no default: it is stamped from a
    publish time in the payload, or from the product's declared lag, never guessed as 'now'.
    """

    station_id: str
    valid_time: UTCDatetime
    available_time: UTCDatetime
    east_m: float
    north_m: float
    up_m: float
    sigma_e: float = Field(ge=0.0)
    sigma_n: float = Field(ge=0.0)
    sigma_u: float = Field(ge=0.0)
    product: GnssProduct
    provenance: Provenance

    @field_validator("east_m", "north_m", "up_m", "sigma_e", "sigma_n", "sigma_u")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            msg = "GNSS coordinates and sigmas must be finite"
            raise ValueError(msg)
        return value


def readable_as_of(available_time: datetime, as_of: datetime) -> bool:
    """Half-open as-of rule: readable iff ``available_time < as_of`` (ADR-0054).

    Equality is excluded. A value published in the same instant as the issue is the ambiguity
    a model author would resolve in their own favour; the boundary is therefore a refusal to
    serve, not a quiet drop of a returned row — adapters filter it out of the result set, and
    tests assert it is absent.
    """
    return available_time < as_of
