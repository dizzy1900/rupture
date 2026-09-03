"""The published schema for a user-supplied exposure import (``exposure-import.v0``).

A consumer who wants rupture to price *their* portfolio needs a documented file format, not a
conversation. This module defines it as pydantic models so it can be exported as JSON Schema
alongside the other contracts.

**Not yet registered.** ``contracts/`` and ``domain/contracts.py`` belong to the architect, so
this file cannot add itself to ``CONTRACTS``. Until it is registered, the schema is enforced by
:mod:`rupture.adapters.exposure.geoparquet_import` at import time and rendered on demand by
:func:`json_schema`, but ``contracts/exposure-import.v0.json`` does not exist and
``schema-check`` does not police it. What the architect has to do is one line in
``domain/contracts.py``; the risk report says so.

Format. One row per asset, in GeoParquet or CSV, with the columns below. Geometry may be given
either as a GeoParquet ``geometry`` column of points or as explicit ``longitude``/``latitude``
columns; anything else (lines, polygons, multi-part geometries) is refused rather than reduced to
a centroid behind the user's back.
"""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_NAME = "exposure-import.v0.json"
SCHEMA_VERSION = "0"

REQUIRED_COLUMNS: tuple[str, ...] = ("id", "taxonomy", "value")
"""Columns that must be present in every import. Location may come from ``geometry`` instead."""

LOCATION_COLUMNS: tuple[str, ...] = ("longitude", "latitude")


class ExposureImportRow(BaseModel):
    """One asset as a consumer supplies it."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    id: str = Field(min_length=1, description="Unique within the file.")
    longitude: float = Field(ge=-180.0, le=180.0)
    latitude: float = Field(ge=-90.0, le=90.0)
    taxonomy: str = Field(
        min_length=1,
        description=(
            "GEM taxonomy string or a class rupture's vulnerability model knows "
            "(see docs/RISK.md); an unknown class is reported, never silently given a default."
        ),
    )
    value: float = Field(ge=0.0, description="Replacement value in the portfolio's currency.")
    occupants: float | None = Field(default=None, ge=0.0)
    vs30: float | None = Field(
        default=None,
        gt=0.0,
        description="Site Vs30 in m/s. When absent the caller's default is used and recorded.",
    )
    component: str | None = Field(
        default=None,
        description="For a decomposed industrial asset: the HydropowerComponent this row is.",
    )
    parent_id: str | None = Field(
        default=None, description="Set on a component row to name the asset it belongs to."
    )
    source_refs: tuple[str, ...] = Field(
        default=(), description="Where the value and the location came from."
    )
    notes: str | None = None

    @model_validator(mode="after")
    def _component_needs_a_parent(self) -> Self:
        if self.component is not None and self.parent_id is None:
            msg = f"row {self.id!r} names a component but no parent_id"
            raise ValueError(msg)
        return self


class ExposureImport(BaseModel):
    """A whole imported portfolio, before it becomes an ``ExposurePortfolio``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = SCHEMA_VERSION
    portfolio_id: str = Field(min_length=1)
    name: str | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$", description="ISO 4217.")
    price_year: int = Field(ge=1900, le=2100)
    valuation_basis: str = Field(
        min_length=1,
        description="How the values were derived. A blank basis is refused: an unexplained "
        "replacement value is not usable in an underwriting figure.",
    )
    assets: tuple[ExposureImportRow, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> Self:
        seen = [a.id for a in self.assets]
        duplicates = sorted({i for i in seen if seen.count(i) > 1})
        if duplicates:
            msg = f"duplicate asset ids in the import: {', '.join(duplicates[:5])}"
            raise ValueError(msg)
        known = set(seen)
        orphans = sorted(
            {a.parent_id for a in self.assets if a.parent_id and a.parent_id not in known}
        )
        if orphans:
            msg = f"component rows name unknown parents: {', '.join(orphans[:5])}"
            raise ValueError(msg)
        return self


def json_schema() -> dict[str, Any]:
    """JSON Schema (draft 2020-12) for the import format, shaped like the other contracts."""
    schema = ExposureImport.model_json_schema(mode="serialization")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"https://github.com/dizzy1900/rupture/contracts/{SCHEMA_NAME}",
        "title": "ExposureImport.v0",
        "description": (
            "A user-supplied exposure portfolio for rupture's loss layer: one row per asset with "
            "a location, a class rupture's vulnerability model recognises, and a replacement "
            "value whose basis is stated."
        ),
        **schema,
    }
