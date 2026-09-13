"""Mandatory spatial aftershock comparators: the one-neuron logistic and distance-plus-slip.

Any spatial aftershock or static-stress classification claim is scored against these
(ADR-0059). They are not challengers. They are the straw-man the field already published.
"""

from __future__ import annotations

from rupture.models.comparators.alarm import alarm_from_logistic
from rupture.models.comparators.distance_slip import DistanceSlipAftershockModel
from rupture.models.comparators.errors import MissingSlipFieldError
from rupture.models.comparators.logistic import MODEL_ID, OneNeuronAftershockModel
from rupture.models.comparators.slip import SlipField, slip_field_from_subfaults

__all__ = [
    "MODEL_ID",
    "DistanceSlipAftershockModel",
    "MissingSlipFieldError",
    "OneNeuronAftershockModel",
    "SlipField",
    "alarm_from_logistic",
    "slip_field_from_subfaults",
]
