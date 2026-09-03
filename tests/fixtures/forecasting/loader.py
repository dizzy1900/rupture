"""Test-only loader: the committed ComCat GeoJSON slice -> domain ``Catalog`` + a test ``Region``.

The fixture holds *reported* preferred magnitudes (ComCat ``magType`` ml/mlr/mw/md), not
homogenised Mw. With ``reported_as_mw=True`` (the default, used by the ETAS smoke fit and the
gates) every event gets ``mw = magnitude.value`` labelled ``mw_conversion="reported-as-mw:<type>"``
so the label says exactly what was done. With ``reported_as_mw=False`` only mw-family types get
``mw`` (``identity:<type>``); everything else has ``mw=None``. Production catalogues never use
this loader; they come from ``rupture catalog build``.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rupture.domain import (
    Catalog,
    Event,
    EventType,
    MagnitudeRecord,
    MagnitudeType,
    Provenance,
    Region,
    TectonicSetting,
)

FIXTURE_DIR = Path(__file__).resolve().parent
GEOJSON = FIXTURE_DIR / "comcat-california-2018-2019-m3.geojson"
PROVENANCE = FIXTURE_DIR / "provenance.json"
MW_FAMILY = {"mw", "mww", "mwc", "mwb", "mwr"}


def _event_type(raw: str) -> EventType:
    return EventType(raw) if raw in {"earthquake", "landslide", "explosion"} else EventType.OTHER


def load_fixture_catalog(*, reported_as_mw: bool = True) -> Catalog:
    prov = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    provenance = Provenance(
        source=prov["source"],
        source_url=prov["source_url"],
        retrieved_at=prov["retrieved_at"],
        sha256=prov["sha256"],
        licence=prov["licence"],
        adapter_version="tests.fixtures.forecasting.loader",
    )
    raw = json.loads(GEOJSON.read_text(encoding="utf-8"))
    events: list[Event] = []
    for feat in raw["features"]:
        p = feat["properties"]
        lon, lat, depth = feat["geometry"]["coordinates"]
        raw_type = (p.get("magType") or "other").lower()
        mtype = (
            MagnitudeType(raw_type)
            if raw_type in MagnitudeType.__members__.values()
            else (MagnitudeType.OTHER)
        )
        value = float(p["mag"])
        if reported_as_mw:
            mw, conv = value, f"reported-as-mw:{raw_type}"
        elif raw_type in MW_FAMILY:
            mw, conv = value, f"identity:{raw_type}"
        else:
            mw, conv = None, None
        events.append(
            Event(
                id=f"comcat:{feat['id']}",
                origin_time=datetime.fromtimestamp(p["time"] / 1000.0, tz=UTC),
                latitude=lat,
                longitude=lon,
                depth_km=depth,
                magnitude=MagnitudeRecord(
                    value=value, type=mtype, agency=p.get("net"), raw_type=raw_type
                ),
                mw=mw,
                mw_conversion=conv,
                event_type=_event_type(p["type"]),
                source_catalog="usgs-comcat",
                source_event_id=feat["id"],
                provenance=provenance,
            )
        )
    return Catalog(
        id="fixture-comcat-california-2018-2019-m3",
        region_id="california-fixture",
        events=tuple(events),
        sources=("usgs-comcat",),
        built_at=provenance.retrieved_at,
        builder_version="tests.fixtures.forecasting.loader",
        notes=prov["notes"],
    )


def fixture_region() -> Region:
    """Rectangle around the fixture query box; RELM-style thresholds; Mc not fitted (``None``)."""
    return Region(
        id="california-fixture",
        name="California fixture box (tests only)",
        polygon=((-122.0, 32.0), (-114.0, 32.0), (-114.0, 37.5), (-122.0, 37.5)),
        depth_max_km=30.0,
        tectonic_setting=TectonicSetting.TRANSFORM,
        cell_size_deg=0.1,
        target_min_magnitude=3.95,
        description="Test-only rectangle; not one of the protocol regions.",
    )
