"""Typed failures for the spatial aftershock comparators."""

from __future__ import annotations


class MissingSlipFieldError(ValueError):
    """The three-parameter logistic was asked to run without a usable finite-fault / slip field.

    Naming what is missing is the point. Silently dropping log-slip and fitting the two-parameter
    distance logistic under a three-parameter name is how a straw man gets dressed as a result.
    """
