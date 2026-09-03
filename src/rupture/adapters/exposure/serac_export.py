"""Read the sibling ``serac``'s published exposure export into an ``ExposurePortfolio``.

serac owns this exposure. rupture reads it and never becomes its source of truth: the adapter
looks for the live export first (``SERAC_EXPORT_DIR``, default ``../serac``) and only falls back
to the copy committed under ``tests/fixtures/risk/exposure/`` so that a fresh clone can run the
offline gate. Which of the two was used is recorded in ``Provenance.source_url`` and repeated in
``Provenance.notes``, so a portfolio can never quietly be built from a stale copy.

Coordination is by file, never by import (CLAUDE.md, ADR-0014): nothing here imports serac.

The export is GeoJSON point features whose properties carry ``id``, ``asset_type``, ``status``,
``positional_accuracy_m``, ``source_refs`` and, for power plants, a ``capacity_mw`` object shaped
like rupture's :class:`~rupture.domain.money.Range`. Capacity is converted to a replacement value
by :mod:`rupture.adapters.exposure.valuation`, which carries the published cost figure and labels
the assumed interval; asset classes with no cost basis are kept at value zero and counted.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rupture import __version__
from rupture.adapters.exposure.valuation import (
    DEFAULT_BASIS,
    NO_BASIS_NOTE,
    VALUED_ASSET_TYPES,
    HydropowerCostBasis,
)
from rupture.domain.common import Provenance, sha256_hex
from rupture.domain.loss import Asset, ExposurePortfolio

SOURCE_ID = "serac-export"
ADAPTER_VERSION = __version__
ENV_VAR = "SERAC_EXPORT_DIR"
DEFAULT_EXPORT_DIR = Path("..") / "serac"
AOI_REL = Path("data") / "aoi"
ASSETS_FILE = "exposed_assets.geojson"
FALLBACK_REL = Path("tests") / "fixtures" / "risk" / "exposure"
DEFAULT_AOI = "lhende-khola-trishuli"
DEFAULT_VS30 = 760.0
"""NEHRP B/C reference rock. An assumption: the export carries no site condition. See docs."""

LICENCE = "see the serac repository (github.com/dizzy1900/serac)"
POINT = "Point"


class SeracExportError(ValueError):
    """The export is missing or not shaped the way the contract says."""


@dataclass(frozen=True, slots=True)
class LoadReport:
    """What the loader did, so the caller can print it rather than guess."""

    path: Path
    used_fallback: bool
    n_features: int
    n_valued: int
    n_unvalued: int
    unvalued_ids: tuple[str, ...] = ()
    warnings: tuple[str, ...] = field(default=())

    def lines(self) -> list[str]:
        origin = "committed fallback fixture" if self.used_fallback else "live serac export"
        out = [
            f"exposure source: {origin} at {self.path}",
            f"assets: {self.n_features} ({self.n_valued} valued, {self.n_unvalued} at zero value)",
        ]
        if self.unvalued_ids:
            out.append(f"no replacement-cost basis: {', '.join(self.unvalued_ids)}")
        out.extend(self.warnings)
        return out


def export_dir() -> Path:
    """Where the live serac export is expected: ``$SERAC_EXPORT_DIR`` or ``../serac``."""
    raw = os.environ.get(ENV_VAR)
    return Path(raw).expanduser() if raw else DEFAULT_EXPORT_DIR


class SeracExposureSource:
    """The ``ExposureSource`` port, reading serac's published GeoJSON."""

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION

    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        aoi: str = DEFAULT_AOI,
        cost_basis: HydropowerCostBasis = DEFAULT_BASIS,
        default_vs30: float = DEFAULT_VS30,
    ) -> None:
        self.repo_root = repo_root
        self.aoi = aoi
        self.cost_basis = cost_basis
        self.default_vs30 = default_vs30
        self._last_report: LoadReport | None = None

    # ------------------------------------------------------------------ location
    def resolve(self, path: Path | None = None) -> tuple[Path, bool]:
        """``(path to the export, used_fallback)``. Explicit path wins; then live; then fixture.

        An explicit path that points into rupture's own committed fixtures still counts as the
        fallback: the caller asked for a specific file, but the portfolio must still say that the
        exposure did not come from serac.
        """
        if path is not None:
            if not path.is_file():
                msg = f"exposure export not found at {path}"
                raise SeracExportError(msg)
            resolved = path.resolve()
            return resolved, self._is_committed_fallback(resolved)
        live = export_dir() / AOI_REL / self.aoi / ASSETS_FILE
        if live.is_file():
            return live.resolve(), False
        if self.repo_root is None:
            msg = (
                f"no serac export at {live} and no repo_root given for the committed fallback; "
                f"set {ENV_VAR} to the serac checkout"
            )
            raise SeracExportError(msg)
        fallback = self.repo_root / FALLBACK_REL / self.aoi / ASSETS_FILE
        if not fallback.is_file():
            msg = f"no serac export at {live} and no committed fallback at {fallback}"
            raise SeracExportError(msg)
        return fallback.resolve(), True

    def _is_committed_fallback(self, path: Path) -> bool:
        if self.repo_root is None:
            return False
        return path.is_relative_to((self.repo_root / FALLBACK_REL).resolve())

    # ------------------------------------------------------------------ port
    def load(
        self, path: Path | None = None, *, portfolio_id: str = "trishuli-corridor"
    ) -> ExposurePortfolio:
        resolved, used_fallback = self.resolve(path)
        raw = resolved.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        features = _features(payload, resolved)
        assets: list[Asset] = []
        unvalued: list[str] = []
        for feature in features:
            asset, valued = self._asset(feature, resolved)
            assets.append(asset)
            if not valued:
                unvalued.append(asset.id)
        if not assets:
            msg = f"{resolved} has no features"
            raise SeracExportError(msg)

        warnings: list[str] = []
        if used_fallback:
            warnings.append(
                "WARNING: built from rupture's committed copy of serac's export, not from serac; "
                f"set {ENV_VAR} to the serac checkout to use the live file"
            )
        if unvalued:
            warnings.append(
                f"WARNING: {len(unvalued)} of {len(assets)} assets carry no replacement value "
                "and contribute nothing to the loss figure"
            )
        self._last_report = LoadReport(
            path=resolved,
            used_fallback=used_fallback,
            n_features=len(assets),
            n_valued=len(assets) - len(unvalued),
            n_unvalued=len(unvalued),
            unvalued_ids=tuple(unvalued),
            warnings=tuple(warnings),
        )
        return ExposurePortfolio(
            id=portfolio_id,
            name=f"serac AOI {self.aoi}",
            currency=self.cost_basis.currency,
            valuation_date=_valuation_date(self.cost_basis.price_year),
            assets=tuple(assets),
            provenance=Provenance(
                source=SOURCE_ID,
                source_url=str(resolved),
                retrieved_at=datetime.now(tz=UTC),
                sha256=sha256_hex(raw),
                licence=LICENCE,
                adapter_version=ADAPTER_VERSION,
                notes="; ".join(
                    [
                        (
                            "exposure owned by the sibling serac and read by file contract; "
                            "rupture is not its source of truth"
                        ),
                        (
                            "COMMITTED FALLBACK COPY, not the live serac export"
                            if used_fallback
                            else "live serac export"
                        ),
                        f"valuation: {self.cost_basis.describe()}",
                        f"site conditions assumed: Vs30 = {self.default_vs30:g} m/s at every site",
                        (
                            f"{len(unvalued)} asset(s) with no cost basis at value zero: "
                            f"{', '.join(unvalued)}"
                            if unvalued
                            else "every asset carries a replacement value"
                        ),
                    ]
                ),
            ),
        )

    @property
    def last_report(self) -> LoadReport:
        if self._last_report is None:
            msg = "load() has not been called yet"
            raise SeracExportError(msg)
        return self._last_report

    # ------------------------------------------------------------------ internals
    def _asset(self, feature: dict[str, Any], path: Path) -> tuple[Asset, bool]:
        properties = feature.get("properties") or {}
        identifier = properties.get("id")
        if not identifier:
            msg = f"a feature in {path} has no id"
            raise SeracExportError(msg)
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != POINT:
            msg = f"asset {identifier!r} is a {geometry.get('type')!r}; only Point is supported"
            raise SeracExportError(msg)
        lon, lat = (float(v) for v in geometry["coordinates"][:2])
        asset_type = str(properties.get("asset_type") or "unknown")
        capacity = _capacity_mw(properties)

        attributes: dict[str, str | float | int | bool | None] = {
            "asset_type": asset_type,
            "status": properties.get("status"),
            "positional_accuracy_m": properties.get("positional_accuracy_m"),
            "vs30": self.default_vs30,
            "vs30_basis": "assumed reference rock; serac's export carries no site condition",
            "source_refs": ", ".join(properties.get("source_refs") or ()),
        }
        if capacity is not None:
            attributes["capacity_mw"] = capacity

        if asset_type in VALUED_ASSET_TYPES and capacity is not None:
            value = self.cost_basis.best(capacity)
            attributes["value_basis"] = f"{capacity:g} MW x {self.cost_basis.describe()}"
            valued = True
        else:
            value = 0.0
            attributes["value_basis"] = NO_BASIS_NOTE
            valued = False
        return (
            Asset(
                id=str(identifier),
                longitude=lon,
                latitude=lat,
                taxonomy=asset_type,
                value=value,
                occupants=None,
                attributes=attributes,
            ),
            valued,
        )


def _features(payload: Any, path: Path) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
        msg = f"{path} is not a GeoJSON FeatureCollection"
        raise SeracExportError(msg)
    features = payload.get("features")
    if not isinstance(features, list):
        msg = f"{path} has no features array"
        raise SeracExportError(msg)
    return [f for f in features if isinstance(f, dict)]


def _capacity_mw(properties: dict[str, Any]) -> float | None:
    """serac writes ``capacity_mw`` as a Range-shaped object; take ``best``, else the midpoint."""
    raw = properties.get("capacity_mw")
    if raw is None:
        return None
    if isinstance(raw, int | float):
        return float(raw)
    if not isinstance(raw, dict):
        msg = f"capacity_mw for {properties.get('id')!r} is a {type(raw).__name__}"
        raise SeracExportError(msg)
    if raw.get("unit") not in (None, "MW"):
        msg = f"capacity_mw for {properties.get('id')!r} is in {raw['unit']!r}, expected MW"
        raise SeracExportError(msg)
    best = raw.get("best")
    if best is not None:
        return float(best)
    low, high = raw.get("low"), raw.get("high")
    if low is None or high is None:
        msg = f"capacity_mw for {properties.get('id')!r} has neither best nor low/high"
        raise SeracExportError(msg)
    return (float(low) + float(high)) / 2.0


def _valuation_date(price_year: int) -> datetime:
    """The cost basis's price year, as the portfolio's valuation date."""
    return datetime(price_year, 12, 31, tzinfo=UTC)
