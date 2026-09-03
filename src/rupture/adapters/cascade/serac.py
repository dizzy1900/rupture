"""Slope units from the sibling ``serac``, read as files and never as code.

``serac`` (``github.com/dizzy1900/serac``, Apache-2.0) publishes ``contracts/slope-unit.v0.json``.
rupture consumes that contract through ``SERAC_EXPORT_DIR`` and holds a **fixture fallback**
derived from serac's own AOI files for the case where serac has not exported slope units yet,
which is the case as of 2026-09-03.

Two rules govern this module.

*The fallback is labelled.* Every :class:`~rupture.domain.cascade.CascadeExposure` it produces
names its ``slope_unit_source`` as a fallback and says what it was derived from. A consumer can
always tell a real serac L0 inventory from rupture's stand-in.

*serac's data is serac's.* The committed fixture under ``tests/fixtures/cascade/serac/`` is a
verbatim copy of serac's own files with serac's attribution, licence and commit recorded. rupture
does not present it as its own, does not edit it, and does not re-derive it.

Contract mismatch, recorded rather than hidden: serac's ``slope-unit.v0`` has
``glacier_cover: boolean`` and ``elevation_band_m: [low, high]``, while rupture's
:class:`~rupture.domain.cascade.ExposedSlopeUnit` has ``glacier_cover: float in [0, 1]`` and
``elevation_band_m: str``. The mapping is ``True -> 1.0`` / ``False -> 0.0`` and
``[a, b] -> "a-b m"``; a boolean carries no fraction, so the 1.0 means "glacierised", not "fully
glacierised". See ADR-0027.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from rupture.domain.cascade import CascadeExposure, CascadeKind, ExposedSlopeUnit
from rupture.domain.common import utc_now
from rupture.domain.groundmotion import GroundMotionField
from rupture.domain.money import ConfidenceTier, ModelProvenance

SERAC_EXPORT_DIR_ENV = "SERAC_EXPORT_DIR"
SERAC_LICENCE = "Apache-2.0"
SERAC_REPOSITORY = "https://github.com/dizzy1900/serac"
SLOPE_UNIT_CONTRACT = "serac contracts/slope-unit.v0.json"

FIXTURE_DIR = Path("tests") / "fixtures" / "cascade" / "serac"

DEFAULT_PGA_THRESHOLD_G = 0.02
"""Screening floor, 2 %g.

Basis: the USGS ground-failure landslide model does not evaluate at all below 2 %g
(``defaultconfigfiles/models/jessee_2018.ini``: ``minpga = 2. # %g (Jibson and Harp, 2016)``,
committed under ``tests/fixtures/cascade/usgs_groundfailure/``). It is a floor below which a
published model declines to say anything, **not** a level at which a slope fails. Nothing in the
literature gives a shaking threshold for co-seismic ice/rock avalanche release, and rupture does
not invent one; the threshold is a configurable screening device and every output says so.
"""

DEFAULT_STEEP_SLOPE_DEG = 30.0
"""Steepness screen applied only when a unit actually carries ``mean_slope_deg``.

30 degrees is the conventional lower bound for the source areas of rapid rock and ice
avalanches; it is a screening convention, not a stability criterion, and rupture applies it only
where serac supplies a slope. Where slope is unknown the screen is **not** applied and the
exposure record says which units that affected.
"""


class SeracExportMissingError(RuntimeError):
    """SERAC_EXPORT_DIR was set but holds nothing rupture can read."""


@dataclass(frozen=True, slots=True)
class SlopeUnitInventory:
    """Slope units for one AOI, plus where they came from and how much to trust them."""

    aoi_id: str
    units: tuple[dict[str, Any], ...]
    source_id: str
    is_fallback: bool
    derived_from: tuple[str, ...]
    licence: str
    notes: str


def _representative_point(geometry: dict[str, Any]) -> tuple[float, float]:
    """Centroid of a polygon's exterior ring, or the point itself. No projection: AOIs are small."""
    kind = geometry.get("type")
    if kind == "Point":
        lon, lat = geometry["coordinates"][:2]
        return float(lon), float(lat)
    if kind == "Polygon":
        ring = geometry["coordinates"][0]
    elif kind == "MultiPolygon":
        ring = geometry["coordinates"][0][0]
    else:
        msg = f"cannot take a representative point of geometry type {kind!r}"
        raise ValueError(msg)
    coords = np.asarray([(float(c[0]), float(c[1])) for c in ring], dtype=np.float64)
    if len(coords) > 1 and np.allclose(coords[0], coords[-1]):
        coords = coords[:-1]
    return float(coords[:, 0].mean()), float(coords[:, 1].mean())


def _elevation_band(value: Any) -> str | None:
    if isinstance(value, list | tuple) and len(value) == 2:
        return f"{value[0]:g}-{value[1]:g} m"
    if isinstance(value, str):
        return value
    return None


def _glacier_cover(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, int | float):
        return float(value)
    return None


class SeracSlopeUnitSource:
    """Reads serac's ``slope-unit.v0`` export, or falls back to serac's AOI files.

    Resolution order:

    1. ``SERAC_EXPORT_DIR`` (or ``export_dir=``) containing ``slope-units/<aoi>.geojson`` or
       ``slope_units/<aoi>.json`` — a real serac L0 inventory.
    2. The same directory's ``data/aoi/<aoi>/`` files — serac's AOI build, from which rupture
       derives one coarse unit per source zone, with every terrain attribute left null.
    3. The committed fixture copy of (2) under ``tests/fixtures/cascade/serac/``, so the offline
       suite runs with no serac checkout at all.
    """

    def __init__(self, *, export_dir: Path | None = None, repo_root: Path | None = None) -> None:
        env = os.environ.get(SERAC_EXPORT_DIR_ENV)
        self.export_dir = export_dir or (Path(env) if env else None)
        self.repo_root = repo_root or Path.cwd()
        self.source_id = "serac-slope-unit-v0"

    # -- discovery ----------------------------------------------------------------------
    def _export_candidates(self, aoi_id: str) -> list[Path]:
        if self.export_dir is None:
            return []
        base = self.export_dir
        return [
            base / "slope-units" / f"{aoi_id}.geojson",
            base / "slope-units" / f"{aoi_id}.json",
            base / "slope_units" / f"{aoi_id}.geojson",
            base / "slope_units" / f"{aoi_id}.json",
            base / aoi_id / "slope_units.geojson",
        ]

    def _aoi_dir(self, aoi_id: str) -> Path | None:
        if self.export_dir is not None:
            for candidate in (
                self.export_dir / "data" / "aoi" / aoi_id,
                self.export_dir / "aoi" / aoi_id,
                self.export_dir / aoi_id,
            ):
                if (candidate / "source_zone.geojson").exists():
                    return candidate
        fixture = self.repo_root / FIXTURE_DIR / aoi_id
        return fixture if (fixture / "source_zone.geojson").exists() else None

    # -- the port ------------------------------------------------------------------------
    def units_for(self, aoi_id: str) -> tuple[dict[str, object], ...]:
        return tuple(dict(u) for u in self.inventory(aoi_id).units)

    def inventory(self, aoi_id: str) -> SlopeUnitInventory:
        for path in self._export_candidates(aoi_id):
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                features = payload.get("features", payload if isinstance(payload, list) else [])
                units = tuple(
                    dict(f.get("properties", {}), geometry=f.get("geometry"))
                    if isinstance(f, dict) and "properties" in f
                    else dict(f)
                    for f in features
                )
                return SlopeUnitInventory(
                    aoi_id=aoi_id,
                    units=units,
                    source_id=f"serac:{path}",
                    is_fallback=False,
                    derived_from=(str(path),),
                    licence=SERAC_LICENCE,
                    notes=f"serac slope-unit.v0 export, {len(units)} units",
                )
        aoi_dir = self._aoi_dir(aoi_id)
        if aoi_dir is None:
            msg = (
                f"no slope units for AOI {aoi_id!r}: no serac slope-unit.v0 export under "
                f"{self.export_dir or SERAC_EXPORT_DIR_ENV + ' (unset)'}, and no committed "
                f"fallback under {FIXTURE_DIR / aoi_id}"
            )
            raise SeracExportMissingError(msg)
        return self._fallback(aoi_id, aoi_dir)

    def _fallback(self, aoi_id: str, aoi_dir: Path) -> SlopeUnitInventory:
        """One coarse unit per serac source zone, with every terrain attribute null.

        serac's AOI build carries no DEM-derived terrain, so slope, aspect, elevation band,
        glacier cover and permafrost index are all unknown here and are recorded as ``None``,
        never as a plausible-looking guess.
        """
        payload = json.loads((aoi_dir / "source_zone.geojson").read_text(encoding="utf-8"))
        units: list[dict[str, Any]] = []
        for index, feature in enumerate(payload.get("features", [])):
            properties = feature.get("properties", {})
            units.append(
                {
                    "id": f"{aoi_id}-source-zone-{index}",
                    "aoi_id": aoi_id,
                    "geometry": feature.get("geometry"),
                    "geometry_quality": properties.get("geometry_quality"),
                    "aspect_deg": None,
                    "mean_slope_deg": None,
                    "elevation_band_m": None,
                    "glacier_cover": None,
                    "permafrost_index": None,
                    "lithology_tag": None,
                    "area_m2": None,
                    "source_refs": tuple(properties.get("source_refs", ())),
                    "notes": (
                        "rupture fallback unit: serac's source-zone polygon, unmodified. serac "
                        "has not exported a slope-unit.v0 inventory for this AOI, so no "
                        "terrain attribute is available and none is guessed. "
                        + str(properties.get("notes", ""))
                    ).strip(),
                }
            )
        return SlopeUnitInventory(
            aoi_id=aoi_id,
            units=tuple(units),
            source_id=f"serac-aoi-fallback:{aoi_id}",
            is_fallback=True,
            derived_from=(str(aoi_dir / "source_zone.geojson"),),
            licence=SERAC_LICENCE,
            notes=(
                "FALLBACK, not a serac slope-unit.v0 inventory: one unit per serac source-zone "
                "polygon, terrain attributes null"
            ),
        )

    def settlements(self, aoi_id: str) -> tuple[tuple[str, float, float], ...]:
        """Settlements serac maps in this AOI's corridor: ``(id, lon, lat)``."""
        aoi_dir = self._aoi_dir(aoi_id)
        if aoi_dir is None:
            return ()
        path = aoi_dir / "exposed_assets.geojson"
        if not path.exists():
            return ()
        payload = json.loads(path.read_text(encoding="utf-8"))
        found = []
        for feature in payload.get("features", []):
            properties = feature.get("properties", {})
            if properties.get("asset_type") != "settlement":
                continue
            lon, lat = _representative_point(feature["geometry"])
            found.append((str(properties.get("id")), lon, lat))
        return tuple(found)

    def exposure(
        self,
        field: GroundMotionField,
        *,
        aoi_id: str,
        pga_threshold_g: float = DEFAULT_PGA_THRESHOLD_G,
        steep_slope_deg: float = DEFAULT_STEEP_SLOPE_DEG,
        scenario_id: str | None = None,
    ) -> CascadeExposure:
        """Overlay a scenario's shaking on the AOI's slope units and flag the exposed ones.

        A unit is flagged when the PGA it receives is at or above ``pga_threshold_g`` **and**
        every terrain screen that can be applied passes: ``mean_slope_deg >= steep_slope_deg``
        where slope is known, and ``glacier_cover > 0`` where glacier cover is known. A screen
        whose attribute is unknown is not applied, and the count of units that affected is in
        the record's ``notes``. Nothing here says a flagged unit fails.
        """
        if field.imt.upper() != "PGA":
            msg = f"exposure needs a PGA field, got imt={field.imt!r}"
            raise ValueError(msg)
        inventory = self.inventory(aoi_id)
        settlements = self.settlements(aoi_id)
        settlement_ids = tuple(s[0] for s in settlements)

        site_lons = np.array([s.longitude for s in field.sites], dtype=np.float64)
        site_lats = np.array([s.latitude for s in field.sites], dtype=np.float64)
        pga = field.median()

        units: list[ExposedSlopeUnit] = []
        slope_unknown = 0
        glacier_unknown = 0
        for record in inventory.units:
            geometry = record.get("geometry")
            if geometry is None:
                msg = f"slope unit {record.get('id')!r} has no geometry"
                raise ValueError(msg)
            lon, lat = _representative_point(geometry)
            nearest = int(
                np.argmin((site_lons - lon) ** 2 + (site_lats - lat) ** 2)
            )
            unit_pga = float(pga[nearest])
            slope = record.get("mean_slope_deg")
            glacier = _glacier_cover(record.get("glacier_cover"))
            passes = unit_pga >= pga_threshold_g
            if slope is None:
                slope_unknown += 1
            elif float(slope) < steep_slope_deg:
                passes = False
            if glacier is None:
                glacier_unknown += 1
            elif glacier <= 0.0:
                passes = False
            units.append(
                ExposedSlopeUnit(
                    id=str(record["id"]),
                    aoi_id=aoi_id,
                    mean_slope_deg=float(slope) if slope is not None else None,
                    glacier_cover=glacier,
                    permafrost_index=(
                        float(record["permafrost_index"])
                        if record.get("permafrost_index") is not None
                        else None
                    ),
                    elevation_band_m=_elevation_band(record.get("elevation_band_m")),
                    area_m2=(
                        float(record["area_m2"]) if record.get("area_m2") is not None else None
                    ),
                    pga_g=unit_pga,
                    exceeds_threshold=passes,
                    settlements_below=settlement_ids,
                    source_refs=tuple(str(r) for r in record.get("source_refs", ())),
                )
            )
        notes = [
            f"screening threshold {pga_threshold_g:g} g; a threshold is a screening device, not "
            f"a failure criterion",
            f"slope-unit source: {inventory.notes}",
            f"serac ({SERAC_REPOSITORY}, {SERAC_LICENCE}); derived from "
            + ", ".join(inventory.derived_from),
            "settlements_below lists the settlements serac maps in this AOI's river corridor; "
            "serac's asset records carry no elevation, so 'below' here is corridor membership, "
            "not a verified elevation relation",
            f"PGA sampled at each unit's representative point from ground-motion field "
            f"{field.id}",
        ]
        if slope_unknown:
            notes.append(
                f"steepness screen NOT applied to {slope_unknown} of {len(units)} units: "
                f"mean_slope_deg unknown"
            )
        if glacier_unknown:
            notes.append(
                f"glacier screen NOT applied to {glacier_unknown} of {len(units)} units: "
                f"glacier_cover unknown"
            )
        return CascadeExposure(
            id=f"cascade-exposure-{aoi_id}-{scenario_id or field.scenario_id}",
            scenario_id=scenario_id or field.scenario_id,
            aoi_id=aoi_id,
            kind=CascadeKind.ICE_ROCK_AVALANCHE,
            pga_threshold_g=pga_threshold_g,
            units=tuple(units),
            slope_unit_source=inventory.source_id,
            provenance=ModelProvenance.ASSUMED if inventory.is_fallback else ModelProvenance.PUBLISHED,
            confidence=ConfidenceTier.UNQUALIFIED if inventory.is_fallback else ConfidenceTier.LOW,
            computed_at=utc_now(),
            notes=" | ".join(notes),
        )
