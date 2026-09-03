"""Import a user-supplied portfolio from GeoParquet or CSV, validated against the published schema.

The schema is :mod:`rupture.risk.exposure_schema` (``exposure-import.v0``). Every row is validated
before anything is built, so a bad file fails with a list of the rows that are wrong rather than
producing a portfolio that is quietly missing assets.

Geometry: a GeoParquet ``geometry`` column of points, or explicit ``longitude``/``latitude``
columns. A line, a polygon or a multi-part geometry is refused; reducing one to a centroid without
being asked would change the answer without telling the user.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import geopandas
import pandas as pd
from pydantic import ValidationError

from rupture import __version__
from rupture.domain.common import Provenance, sha256_hex
from rupture.domain.loss import Asset, ExposurePortfolio
from rupture.risk.exposure_schema import (
    LOCATION_COLUMNS,
    REQUIRED_COLUMNS,
    ExposureImport,
    ExposureImportRow,
)

SOURCE_ID = "user-geoparquet"
ADAPTER_VERSION = __version__
PARQUET_SUFFIXES = frozenset({".parquet", ".geoparquet", ".pq"})
CSV_SUFFIXES = frozenset({".csv", ".tsv"})
POINT = "Point"
DEFAULT_VS30 = 760.0


class ExposureImportError(ValueError):
    """The file cannot be read, or does not satisfy ``exposure-import.v0``."""


class GeoParquetExposureSource:
    """The ``ExposureSource`` port for a portfolio a consumer supplies."""

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        *,
        currency: str = "USD",
        price_year: int = datetime.now(tz=UTC).year,
        valuation_basis: str = "supplied by the portfolio owner",
        default_vs30: float = DEFAULT_VS30,
    ) -> None:
        self.currency = currency
        self.price_year = price_year
        self.valuation_basis = valuation_basis
        self.default_vs30 = default_vs30

    def load(
        self, path: Path | None = None, *, portfolio_id: str = "imported-portfolio"
    ) -> ExposurePortfolio:
        if path is None:
            msg = "a file path is required to import a portfolio"
            raise ExposureImportError(msg)
        frame = read_frame(path)
        record = validate(
            frame,
            portfolio_id=portfolio_id,
            currency=self.currency,
            price_year=self.price_year,
            valuation_basis=self.valuation_basis,
        )
        raw = path.read_bytes()
        return ExposurePortfolio(
            id=record.portfolio_id,
            name=record.name,
            currency=record.currency,
            valuation_date=datetime(record.price_year, 12, 31, tzinfo=UTC),
            assets=tuple(self._asset(row) for row in record.assets),
            provenance=Provenance(
                source=SOURCE_ID,
                source_url=str(path.resolve()),
                retrieved_at=datetime.now(tz=UTC),
                sha256=sha256_hex(raw),
                licence=None,
                adapter_version=ADAPTER_VERSION,
                notes=(
                    f"validated against exposure-import.v{record.schema_version}; "
                    f"valuation basis as supplied: {record.valuation_basis}; "
                    f"Vs30 defaulted to {self.default_vs30:g} m/s where the file omits it"
                ),
            ),
        )

    def _asset(self, row: ExposureImportRow) -> Asset:
        attributes: dict[str, str | float | int | bool | None] = {
            "vs30": row.vs30 if row.vs30 is not None else self.default_vs30,
            "vs30_basis": (
                "supplied by the portfolio owner"
                if row.vs30 is not None
                else "assumed reference rock; the import omitted Vs30"
            ),
            "source_refs": ", ".join(row.source_refs),
        }
        if row.component is not None:
            attributes["component"] = row.component
        if row.parent_id is not None:
            attributes["parent_id"] = row.parent_id
        if row.notes:
            attributes["notes"] = row.notes
        return Asset(
            id=row.id,
            longitude=row.longitude,
            latitude=row.latitude,
            taxonomy=row.taxonomy,
            value=row.value,
            occupants=row.occupants,
            attributes=attributes,
        )


def read_frame(path: Path) -> pd.DataFrame:
    """Read the file into a data frame, resolving a GeoParquet point geometry to lon/lat."""
    if not path.is_file():
        msg = f"exposure import not found at {path}"
        raise ExposureImportError(msg)
    suffix = path.suffix.lower()
    if suffix in PARQUET_SUFFIXES:
        frame = _read_parquet(path)
    elif suffix in CSV_SUFFIXES:
        frame = pd.read_csv(path, sep="\t" if suffix == ".tsv" else ",")
    else:
        msg = (
            f"unsupported exposure import {path.suffix!r}; "
            f"use {sorted(PARQUET_SUFFIXES | CSV_SUFFIXES)}"
        )
        raise ExposureImportError(msg)
    return _resolve_geometry(frame, path)


def _read_parquet(path: Path) -> pd.DataFrame:
    """GeoParquet first; a plain parquet file with lon/lat columns is also accepted."""
    try:
        return pd.DataFrame(geopandas.read_parquet(path))
    except (ValueError, AttributeError):
        return pd.read_parquet(path)


def _resolve_geometry(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    if all(column in frame.columns for column in LOCATION_COLUMNS):
        return frame.drop(columns=["geometry"], errors="ignore")
    if "geometry" not in frame.columns:
        msg = (
            f"{path} has neither {LOCATION_COLUMNS} columns nor a geometry column; "
            "see contracts exposure-import.v0"
        )
        raise ExposureImportError(msg)
    out = frame.copy()
    lons: list[float] = []
    lats: list[float] = []
    for index, geometry in enumerate(out["geometry"]):
        lon, lat = _point(geometry, index, path)
        lons.append(lon)
        lats.append(lat)
    out["longitude"] = lons
    out["latitude"] = lats
    return out.drop(columns=["geometry"])


def _point(geometry: Any, index: int, path: Path) -> tuple[float, float]:
    geom_type = getattr(geometry, "geom_type", None)
    if geom_type != POINT:
        msg = (
            f"{path} row {index} has geometry {geom_type or type(geometry).__name__!r}; "
            "only Point is supported (a centroid would change the answer silently)"
        )
        raise ExposureImportError(msg)
    return float(geometry.x), float(geometry.y)


def validate(
    frame: pd.DataFrame,
    *,
    portfolio_id: str,
    currency: str,
    price_year: int,
    valuation_basis: str,
) -> ExposureImport:
    """Validate every row against ``exposure-import.v0``; report all failures, not the first."""
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        msg = f"exposure import is missing required column(s): {', '.join(missing)}"
        raise ExposureImportError(msg)
    known = set(ExposureImportRow.model_fields)
    records = frame[[c for c in frame.columns if c in known]].to_dict(orient="records")
    rows: list[ExposureImportRow] = []
    problems: list[str] = []
    for index, record in enumerate(records):
        cleaned = {k: v for k, v in record.items() if not _is_missing(v)}
        if isinstance(cleaned.get("source_refs"), str):
            cleaned["source_refs"] = tuple(
                s.strip() for s in str(cleaned["source_refs"]).split(",") if s.strip()
            )
        try:
            rows.append(ExposureImportRow.model_validate(cleaned))
        except ValidationError as exc:
            problems.append(f"row {index}: {exc.errors()[0]['msg']}")
    if problems:
        msg = "exposure import failed validation:\n" + "\n".join(problems[:20])
        raise ExposureImportError(msg)
    try:
        return ExposureImport(
            portfolio_id=portfolio_id,
            currency=currency,
            price_year=price_year,
            valuation_basis=valuation_basis,
            assets=tuple(rows),
        )
    except ValidationError as exc:
        msg = f"exposure import failed validation: {exc.errors()[0]['msg']}"
        raise ExposureImportError(msg) from exc


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
