"""Re-export of the published exposure-import contract, which lives in the domain.

The models moved to :mod:`rupture.domain.exposure_import` when the contract was registered: a
published schema is domain, and ``domain/contracts.py`` cannot import from ``rupture.risk``
without breaking the hexagonal rule. This module keeps the import path the risk adapters use.
"""

from __future__ import annotations

from rupture.domain.exposure_import import (
    LOCATION_COLUMNS,
    REQUIRED_COLUMNS,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    ExposureImport,
    ExposureImportRow,
    json_schema,
)

__all__ = [
    "LOCATION_COLUMNS",
    "REQUIRED_COLUMNS",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "ExposureImport",
    "ExposureImportRow",
    "json_schema",
]
