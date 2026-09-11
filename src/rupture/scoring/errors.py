"""Refusals. Each one names the failure it exists to prevent.

These are errors rather than warnings on purpose. ADR-0055 decision 3 makes the reference part of
the score rather than an argument to it, and a warning is something a pipeline learns to ignore.
"""

from __future__ import annotations


class ScoringError(Exception):
    """Base for everything the scorer refuses to do."""


class MissingReferenceError(ScoringError):
    """A score was requested without the reference it would be a gain over."""


class UniformReferenceRefusedError(ScoringError):
    """A spatially uniform reference was offered as the reference of record.

    Zhang et al. (2024, doi 10.1029/2023JB028037) show an LSTM alarm for M >= 5 in mainland China
    that is skilful on a Molchan diagram against a spatially uniform Poisson reference and loses
    that skill against a spatially varying one. Luen & Stark (2008) make the same point from the
    other side: a trivial rule keyed to recent large events reaches p < 0.001 on clustering alone.
    A uniform reference is scored here only as an explicitly labelled *contrast*.
    """


class RefusedMetricError(ScoringError):
    """A metric ADR-0055 decision 6 refuses to compute, with the reason it is refused."""


class ArmNotImplementedError(ScoringError):
    """The hypothesis arm has no registered scorer, and is not approximated by a nearby one."""


class LeakyReferenceError(ScoringError):
    """The reference saw something the alarm could not have seen, or vice versa."""
