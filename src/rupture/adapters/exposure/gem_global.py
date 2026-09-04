"""GEM's Global Exposure Model as an ``ExposureSource`` — and why none of it is committed here.

**The licence answer first, because it is the answer to the brief's "where openly licensed".**
GEM's Global Exposure Model (``github.com/gem/global_exposure_model``) and its companion Global
Vulnerability Model (``github.com/gem/global_vulnerability_model``) are both released under
**Creative Commons Attribution-NonCommercial-ShareAlike 4.0** (read from each repository's
``LICENSE.txt``, 2026-09-03). That is not an open licence by the Open Definition or the OSI: the
NonCommercial term restricts a field of use, and ShareAlike would propagate to derived works.
rupture is Apache-2.0. So:

* rupture **does not redistribute** any GEM exposure or vulnerability data. Nothing from either
  repository is committed to this tree — no fixture, no slice, no derived table. There is
  therefore no offline GEM test, and the gate does not exercise this adapter against real data.
* rupture **does** ship the adapter, because a consumer who has obtained the model under GEM's
  own terms should not have to write a loader. :meth:`GemExposureSource.load` reads a copy the
  consumer already holds; it never fetches and never caches.
* :func:`fetch_summary` exists for the *public summary tables only*, prints the licence before it
  writes anything, and writes outside the repository by default. The summary tables carry no
  coordinates, so they can be reported but cannot become a portfolio; see
  :func:`read_summary`.

**The second half of the requirement is declined, and here is the reason.** Pairing GEM exposure
with a building-class fragility set needs an openly licensed one. GEM's own vulnerability
database is CC BY-NC-SA, the same problem. HAZUS 5.1 (a US Government work, already the source of
rupture's hydropower component curves) does publish general building-stock fragility, but those
tables are not among the blocks committed under ``tests/fixtures/risk/vulnerability/hazus51/``
and transcribing them from memory would be exactly the fabrication this project refuses. So a GEM
portfolio imported through this adapter is reported **wholly unmodelled**, asset by asset, with
the reason — which is the honest outcome, not a silent zero. ``docs/RISK.md`` records it as an
open gap with the work it needs.

The file format is OpenQuake's exposure CSV, which is what GEM distributes the disaggregated
model in: one row per asset with ``id``, ``lon``, ``lat``, ``taxonomy``, ``number`` and one
column per loss type (``structural`` at minimum). Columns rupture does not use are carried into
``Asset.attributes`` rather than dropped.
"""

from __future__ import annotations

import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from rupture import __version__
from rupture.domain.common import Provenance, sha256_hex
from rupture.domain.loss import Asset, ExposurePortfolio

SOURCE_ID = "gem-global-exposure-model"
ADAPTER_VERSION = __version__
LICENCE = "CC-BY-NC-SA-4.0"
LICENCE_NOTICE = (
    "GEM's Global Exposure Model is licensed CC BY-NC-SA 4.0 (Attribution, NonCommercial, "
    "ShareAlike). rupture is Apache-2.0 and does not redistribute it: this data is yours, "
    "obtained under GEM's terms, and rupture only reads it. Attribution: GEM Foundation, Global "
    "Exposure Model, https://github.com/gem/global_exposure_model"
)
NOT_OPEN_LICENSED = (
    "the GEM Global Exposure Model is CC BY-NC-SA 4.0, which is not an open licence (the "
    "NonCommercial term restricts a field of use and ShareAlike propagates), so rupture commits "
    "no GEM data and has no offline fixture for this adapter"
)
NO_BUILDING_FRAGILITY = (
    "rupture ships no building-class fragility model, so every asset imported from GEM's "
    "taxonomy is reported as not modelled with that reason. Pairing this exposure with GEM's "
    "own vulnerability database is blocked by the same licence; HAZUS's building-stock tables "
    "are openly licensed but are not committed here and will not be transcribed from memory"
)

PUBLIC_SUMMARY_BASE = (
    "https://raw.githubusercontent.com/gem/global_exposure_model/main/"
    "{region}/{country}/summaries/{table}"
)
SUMMARY_TABLES = (
    "Exposure_Summary_Adm0.csv",
    "Exposure_Summary_Adm1.csv",
    "Exposure_Summary_Taxonomy.csv",
)

REQUIRED_COLUMNS = ("id", "lon", "lat", "taxonomy")
VALUE_COLUMNS = ("structural", "total_repl_cost_usd", "bldg_repl_cost_usd")
DEFAULT_VS30 = 760.0


class GemExposureError(ValueError):
    """The GEM export cannot be read as an exposure portfolio."""


def fetch_summary(
    *, region: str, country: str, table: str, out_dir: Path, timeout_s: float = 120.0
) -> Path:
    """Download one **public summary table** into ``out_dir``, after printing the licence.

    Summary tables are aggregates by administrative division or by taxonomy and carry **no
    coordinates**, so they cannot be turned into a portfolio; :func:`read_summary` reports them.
    The spatially disaggregated model is not public — GEM distributes it on licence request — and
    this function will not pretend otherwise.
    """
    if table not in SUMMARY_TABLES:
        msg = f"{table!r} is not one of GEM's public summary tables {SUMMARY_TABLES}"
        raise GemExposureError(msg)
    print(LICENCE_NOTICE)  # noqa: T201 - a licence notice must be seen, not logged away
    url = PUBLIC_SUMMARY_BASE.format(region=region, country=country, table=table)
    out_dir.mkdir(parents=True, exist_ok=True)
    destination = out_dir / f"{country}_{table}"
    with urllib.request.urlopen(url, timeout=timeout_s) as response:
        payload: bytes = response.read()
    destination.write_bytes(payload)
    return destination


def read_summary(path: Path) -> pd.DataFrame:
    """One of GEM's public summary tables, as a frame. No coordinates, so no portfolio."""
    frame = pd.read_csv(path)
    if "lon" in {c.lower() for c in frame.columns}:
        msg = (
            f"{path.name} carries coordinates, so it is a disaggregated export: load it with "
            "GemExposureSource.load, not read_summary"
        )
        raise GemExposureError(msg)
    return frame


class GemExposureSource:
    """The ``ExposureSource`` port for a GEM exposure export the consumer already holds.

    Nothing is fetched and nothing is cached: ``load`` reads the path it is given or fails,
    naming what it needed. The portfolio's provenance records the file's digest, GEM's licence
    and the fact that rupture did not redistribute it.
    """

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        *,
        currency: str = "USD",
        price_year: int = 2025,
        default_vs30: float = DEFAULT_VS30,
        value_column: str | None = None,
    ) -> None:
        self.currency = currency
        self.price_year = price_year
        """GEM's v2026.0.0 release states building counts, cost and population aligned to 2025."""
        self.default_vs30 = default_vs30
        self.value_column = value_column

    def load(
        self, path: Path | None = None, *, portfolio_id: str = "gem-exposure"
    ) -> ExposurePortfolio:
        """Build a portfolio from a GEM/OpenQuake exposure CSV. Fetch or fail; never synthesise."""
        if path is None:
            msg = (
                "a path to a GEM exposure export is required. rupture does not ship one: "
                f"{NOT_OPEN_LICENSED}"
            )
            raise GemExposureError(msg)
        if not path.is_file():
            msg = f"no GEM exposure export at {path}"
            raise GemExposureError(msg)
        raw = path.read_bytes()
        frame = pd.read_csv(path)
        frame.columns = [str(c).strip().lower() for c in frame.columns]
        missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
        if missing:
            msg = (
                f"{path.name} is missing the OpenQuake exposure columns {missing}; "
                f"columns present: {sorted(frame.columns)}"
            )
            raise GemExposureError(msg)
        value_column = self._value_column(frame)
        assets = tuple(self._asset(row, value_column) for _, row in frame.iterrows())
        if not assets:
            msg = f"{path.name} has no rows"
            raise GemExposureError(msg)
        return ExposurePortfolio(
            id=portfolio_id,
            name=f"GEM Global Exposure Model export {path.name}",
            currency=self.currency,
            valuation_date=datetime(self.price_year, 1, 1, tzinfo=UTC),
            assets=assets,
            provenance=Provenance(
                source=SOURCE_ID,
                source_url=str(path),
                retrieved_at=datetime.now(tz=UTC),
                sha256=sha256_hex(raw),
                licence=LICENCE,
                adapter_version=ADAPTER_VERSION,
                notes=(
                    f"valuation: the export's own {value_column!r} column, "
                    f"{self.currency} {self.price_year}. {LICENCE_NOTICE}. {NO_BUILDING_FRAGILITY}"
                ),
            ),
        )

    def _value_column(self, frame: pd.DataFrame) -> str:
        if self.value_column is not None:
            if self.value_column not in frame.columns:
                msg = f"the export has no column {self.value_column!r}"
                raise GemExposureError(msg)
            return self.value_column
        for candidate in VALUE_COLUMNS:
            if candidate in frame.columns:
                return candidate
        msg = (
            f"the export has none of the replacement-value columns {VALUE_COLUMNS}; "
            "name one with GemExposureSource(value_column=...) rather than having rupture guess"
        )
        raise GemExposureError(msg)

    def _asset(self, row: pd.Series[Any], value_column: str) -> Asset:
        extras: dict[str, Any] = {
            str(k): _plain(v)
            for k, v in row.items()
            if str(k) not in {"id", "lon", "lat", "taxonomy", value_column}
        }
        extras["vs30_basis"] = "assumed reference rock; the GEM export carries no site condition"
        occupants = _number(row.get("night")) or _number(row.get("occupants_total"))
        return Asset(
            id=str(row["id"]),
            longitude=float(row["lon"]),
            latitude=float(row["lat"]),
            taxonomy=str(row["taxonomy"]),
            value=max(_number(row.get(value_column)) or 0.0, 0.0),
            occupants=occupants,
            attributes={"vs30": self.default_vs30, **extras},
        )


def _plain(value: Any) -> str | float | int | bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _number(value: Any) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
