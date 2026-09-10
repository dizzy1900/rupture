"""The hypothesis sum type: what a claim *is*, before anything tries to score it.

ADR-0055 makes a hypothesis a discriminated union with five arms, because rupture could
previously express exactly one shape — a gridded rate forecast — and several of the claims a
prediction project has to adjudicate are not that shape. An alarm has no rate; asking it for a
likelihood means inventing a probability model, and the invented model is then the thing under
test rather than the alarm.

This module holds the *tags* only. An arm is implemented when an experiment needs it, and the
unimplemented arms are named here rather than left out so that nobody encodes them as degenerate
rate grids in the meantime. :mod:`rupture.scoring.registry` maps an arm to its scorer and reports
``NOT_IMPLEMENTED`` for an arm that has none.
"""

from __future__ import annotations

from enum import StrEnum


class HypothesisArm(StrEnum):
    """The five shapes a rupture hypothesis may take (ADR-0055 decision 1)."""

    RATE_FORECAST = "rate_forecast"
    """Expected rate per cell, magnitude bin and window: today's ``ForecastGrid``."""

    SIMULATED_CATALOGUES = "simulated_catalogues"
    """An ensemble of synthetic catalogues for the window. Not implemented."""

    ALARM_SET = "alarm_set"
    """Region x window x declare/do not declare. :class:`~rupture.domain.alarm.AlarmSet`."""

    HAZARD_FUNCTION = "hazard_function"
    """Instantaneous rate as a function of time from the issue instant. Not implemented."""

    STATE_ESTIMATE = "state_estimate"
    """A latent (stress, slip rate, coupling, time-to-failure) with uncertainty. Not implemented."""


ARM_DESCRIPTION: dict[HypothesisArm, str] = {
    HypothesisArm.RATE_FORECAST: "expected rate per cell, magnitude bin and window",
    HypothesisArm.SIMULATED_CATALOGUES: "an ensemble of synthetic catalogues for the window",
    HypothesisArm.ALARM_SET: "region x window x declare/do not declare",
    HypothesisArm.HAZARD_FUNCTION: "instantaneous rate as a function of time from issue",
    HypothesisArm.STATE_ESTIMATE: "a latent with uncertainty, checked by interval coverage",
}

MANDATORY_REFERENCE: dict[HypothesisArm, str] = {
    HypothesisArm.RATE_FORECAST: "ETAS; ETAS-I where sub-completeness events are used",
    HypothesisArm.SIMULATED_CATALOGUES: "ETAS; ETAS-I where sub-completeness events are used",
    HypothesisArm.ALARM_SET: (
        "a clustering-aware reference (ETAS or spatially varying Poisson) and a random alarm "
        "set matched on alarm rate and spatial footprint"
    ),
    HypothesisArm.HAZARD_FUNCTION: "the same reference expressed as a hazard function",
    HypothesisArm.STATE_ESTIMATE: "a persistence or climatological estimator of the same latent",
}
