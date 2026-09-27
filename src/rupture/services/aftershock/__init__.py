"""Operational aftershock forecasting (component C4).

Given a mainshock and a catalogue, this service issues the probability of at least one further
event of magnitude at least *m* within a horizon, together with the gridded rate forecast it
summarises. It is a rate-and-probability statement about a sequence, conditioned on what has
already happened; and this service makes no claim about any
individual event. See ``docs/AFTERSHOCK.md`` and ``reports/MODEL_CARD_aftershock.md``.
"""

from __future__ import annotations

from rupture.services.aftershock.forecaster import (
    DEFAULT_HORIZONS,
    DEFAULT_LADDER_OFFSETS,
    POISSON_NOTE,
    REFIT_SCHEDULE,
    AftershockForecaster,
    Issuance,
    RateModel,
    magnitude_ladder,
    probabilities_from_grid,
    rescaled_to_total,
    scheduled_fit_cutoff,
)
from rupture.services.aftershock.generic import (
    GENERIC_RJ,
    GENERIC_SOURCE,
    SETTING_TO_REGIME,
    APosterior,
    GenericRJParameters,
    SequenceObservation,
    expected_count,
    generic_for_region,
    generic_prior,
    omori_integral,
    productivity_exposure,
    regime_for_region,
    sequence_observation,
    update,
)
from rupture.services.aftershock.sequences import (
    ISSUE_OFFSETS,
    SEQUENCES,
    FixtureError,
    Mainshock,
    SequenceSpec,
    check_against_catalog,
    load_parent_region,
    load_sequence_catalog,
    mainshock_from_catalog,
    sequence_spec,
)
from rupture.services.aftershock.window import (
    ZONE_MULTIPLIER,
    aftershock_zone_radius_km,
    epicentral_distance_km,
    sequence_catalog,
    sequence_region,
    subsurface_rupture_length_km,
    zone_polygon,
)

__all__ = [
    "DEFAULT_HORIZONS",
    "DEFAULT_LADDER_OFFSETS",
    "GENERIC_RJ",
    "GENERIC_SOURCE",
    "ISSUE_OFFSETS",
    "POISSON_NOTE",
    "REFIT_SCHEDULE",
    "SEQUENCES",
    "SETTING_TO_REGIME",
    "ZONE_MULTIPLIER",
    "APosterior",
    "AftershockForecaster",
    "FixtureError",
    "GenericRJParameters",
    "Issuance",
    "Mainshock",
    "RateModel",
    "SequenceObservation",
    "SequenceSpec",
    "aftershock_zone_radius_km",
    "check_against_catalog",
    "epicentral_distance_km",
    "expected_count",
    "generic_for_region",
    "generic_prior",
    "load_parent_region",
    "load_sequence_catalog",
    "magnitude_ladder",
    "mainshock_from_catalog",
    "omori_integral",
    "probabilities_from_grid",
    "productivity_exposure",
    "regime_for_region",
    "rescaled_to_total",
    "scheduled_fit_cutoff",
    "sequence_catalog",
    "sequence_observation",
    "sequence_region",
    "sequence_spec",
    "subsurface_rupture_length_km",
    "update",
    "zone_polygon",
]
