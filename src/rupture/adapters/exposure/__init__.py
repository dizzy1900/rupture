"""rupture.adapters.exposure — where an ``ExposurePortfolio`` comes from.

``SeracExposureSource`` reads the sibling project's published corridor export by file contract;
``GeoParquetExposureSource`` reads a portfolio a consumer supplies, validated against
``exposure-import.v0``. Neither invents a replacement value: the cost basis lives in
:mod:`rupture.adapters.exposure.valuation` and says what is published and what is assumed.
"""

from rupture.adapters.exposure.geoparquet_import import (
    ExposureImportError,
    GeoParquetExposureSource,
)
from rupture.adapters.exposure.serac_export import (
    SeracExportError,
    SeracExposureSource,
)
from rupture.adapters.exposure.valuation import DEFAULT_BASIS, HydropowerCostBasis

__all__ = [
    "DEFAULT_BASIS",
    "ExposureImportError",
    "GeoParquetExposureSource",
    "HydropowerCostBasis",
    "SeracExportError",
    "SeracExposureSource",
]
