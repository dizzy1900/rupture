"""Sourced numeric and monetary intervals, shared by file contract with the sibling ``serac``.

These types are adopted **verbatim in field names and constraints** from `serac`'s
`src/serac/domain/common.py` and `forecast.py` (repository `dizzy1900/serac`, read 2026-09-03), so
that one consumer can read a money figure or a confidence tier from either project without a
translation layer. rupture does not import serac; it copies the shape, which is the coordination
rule in ADR-0014 and ADR-0021.

Every number a risk consumer acts on is an interval with a stated basis, never a bare float:
a loss figure that cannot show where it came from is not a figure an underwriter can use.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import Field, model_validator

from rupture.domain.common import RuptureModel


class ConfidenceTier(StrEnum):
    """Qualitative confidence. ``unqualified`` is the only tier a stub may claim."""

    UNQUALIFIED = "unqualified"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ModelProvenance(StrEnum):
    """How a number was produced. A published figure and a fitted model are not the same claim."""

    PUBLISHED = "published"
    FITTED = "fitted"
    ASSUMED = "assumed"
    STUB = "stub"


class AttributedEstimate(RuptureModel):
    """One published figure, attributed to exactly one source."""

    low: float
    high: float
    unit: str = Field(min_length=1)
    source_ref: str = Field(min_length=1)
    qualifier: str | None = Field(
        default=None, description="e.g. 'order of magnitude', 'preliminary', 'median only'"
    )

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.low > self.high:
            msg = f"estimate low={self.low} exceeds high={self.high}"
            raise ValueError(msg)
        return self


class Range(RuptureModel):
    """A sourced numeric interval."""

    low: float
    high: float
    best: float | None = None
    unit: str = Field(min_length=1)
    source_refs: tuple[str, ...] = Field(min_length=1)
    disputed: bool = False
    estimates: tuple[AttributedEstimate, ...] = ()
    notes: str | None = None

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        if self.low > self.high:
            msg = f"low={self.low} exceeds high={self.high}"
            raise ValueError(msg)
        if self.best is not None and not (self.low <= self.best <= self.high):
            msg = f"best={self.best} outside [{self.low}, {self.high}]"
            raise ValueError(msg)
        return self


class MoneyRange(RuptureModel):
    """A monetary interval in a stated currency and price year."""

    low: float = Field(ge=0)
    high: float = Field(ge=0)
    best: float | None = Field(default=None, ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217")
    price_year: int = Field(ge=1900, le=2100)
    basis: str = Field(min_length=1, description="How the figure was derived")
    confidence: ConfidenceTier = ConfidenceTier.UNQUALIFIED
    provenance: ModelProvenance = ModelProvenance.STUB
    source_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _consistency(self) -> Self:
        if self.low > self.high:
            msg = f"low={self.low} exceeds high={self.high}"
            raise ValueError(msg)
        if self.best is not None and not (self.low <= self.best <= self.high):
            msg = f"best={self.best} outside [{self.low}, {self.high}]"
            raise ValueError(msg)
        return self

    @property
    def width(self) -> float:
        return self.high - self.low
