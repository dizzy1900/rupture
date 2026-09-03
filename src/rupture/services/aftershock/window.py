"""The sequence window: which events belong to a mainshock's aftershock sequence.

A forecast has to say, before it says anything else, *which* events it is about. rupture defines
the sequence of a mainshock of magnitude ``M`` as the events with

    ``origin_time >= mainshock_time``  and  ``epicentral distance <= R(M)``

with the aftershock-zone radius

    ``R(M) = max(R_min, f * L(M))``,
    ``L(M) = 10 ** (-2.44 + 0.59 * M)`` km,

where ``L`` is the subsurface rupture length of Wells & Coppersmith (1994), Table 2A, "all"
slip type (BSSA 84(4), 974-1002), ``f = 1.5`` and ``R_min = 20 km``.

Why this shape. The aftershock zone of a large earthquake scales with the rupture, not with the
epicentre, and the epicentre can sit at one end of the rupture: taking one rupture length from
the epicentre (``f = 1``) would put the 2015-05-12 M7.3 Gorkha aftershock, about 140 km east of
the M7.8 epicentre, within a few kilometres of the boundary. Taking ``f = 1.5`` (about 220 km for
M7.8) covers a unilateral rupture plus its off-fault triggering. The convention of "one to two
rupture lengths" is the usual one in the aftershock-statistics literature; Gardner & Knopoff
(1974) declustering windows are smaller (about 89 km at M7.8) because they are tuned to remove
dependent events from a catalogue, not to bound where triggering can occur. ``R_min = 20 km``
keeps the zone of a small mainshock larger than typical epicentral location error.

The radius is a modelling choice, stated here so it can be argued with. It is fixed before any
forecast is issued and does not depend on where the aftershocks actually fell.
"""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import numpy.typing as npt

from rupture.domain import Catalog, Region

# Wells & Coppersmith (1994) Table 2A, subsurface rupture length, all slip types:
# log10(RLD / km) = -2.44 + 0.59 * M
WC94_A = -2.44
WC94_B = 0.59
ZONE_MULTIPLIER = 1.5
MIN_RADIUS_KM = 20.0
MAX_RADIUS_KM = 600.0

EARTH_RADIUS_KM = 6371.0088  # IUGG mean radius
ZONE_VERTICES = 72  # 5-degree steps: the polygon is within 0.1 % of the circle it approximates


def subsurface_rupture_length_km(magnitude: float) -> float:
    """Wells & Coppersmith (1994) subsurface rupture length for magnitude ``M``."""
    return float(10.0 ** (WC94_A + WC94_B * magnitude))


def aftershock_zone_radius_km(magnitude: float) -> float:
    """Radius of the sequence window: ``max(20 km, 1.5 * L(M))``, capped at 600 km."""
    scaled = ZONE_MULTIPLIER * subsurface_rupture_length_km(magnitude)
    return float(min(MAX_RADIUS_KM, max(MIN_RADIUS_KM, scaled)))


def epicentral_distance_km(
    lat0: float, lon0: float, lats: npt.ArrayLike, lons: npt.ArrayLike
) -> npt.NDArray[np.float64]:
    """Great-circle distance on a sphere from ``(lat0, lon0)`` to each ``(lat, lon)``, in km."""
    phi0 = math.radians(lat0)
    phi = np.radians(np.asarray(lats, dtype=np.float64))
    dphi = phi - phi0
    dlam = np.radians(np.asarray(lons, dtype=np.float64) - lon0)
    a = np.sin(dphi / 2.0) ** 2 + math.cos(phi0) * np.cos(phi) * np.sin(dlam / 2.0) ** 2
    out: npt.NDArray[np.float64] = 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return out


def zone_polygon(
    latitude: float, longitude: float, radius_km: float, *, vertices: int = ZONE_VERTICES
) -> tuple[tuple[float, float], ...]:
    """A closed-ring approximation to the circle of ``radius_km`` about the epicentre.

    Vertices are placed with the spherical destination-point formula, so the polygon is a true
    small circle on the sphere rather than a lat/lon ellipse. Returned open (the domain
    :class:`~rupture.domain.Region` closes the ring itself), in (longitude, latitude) order.
    """
    if radius_km <= 0.0:
        msg = "radius_km must be positive"
        raise ValueError(msg)
    if vertices < 8:
        msg = "vertices must be at least 8"
        raise ValueError(msg)
    delta = radius_km / EARTH_RADIUS_KM
    phi0, lam0 = math.radians(latitude), math.radians(longitude)
    ring: list[tuple[float, float]] = []
    for k in range(vertices):
        theta = 2.0 * math.pi * k / vertices
        phi = math.asin(
            math.sin(phi0) * math.cos(delta) + math.cos(phi0) * math.sin(delta) * math.cos(theta)
        )
        lam = lam0 + math.atan2(
            math.sin(theta) * math.sin(delta) * math.cos(phi0),
            math.cos(delta) - math.sin(phi0) * math.sin(phi),
        )
        lat = max(-90.0, min(90.0, math.degrees(phi)))
        lon = (math.degrees(lam) + 180.0) % 360.0 - 180.0
        ring.append((round(lon, 6), round(lat, 6)))
    return tuple(ring)


def sequence_region(
    parent: Region,
    *,
    region_id: str,
    name: str,
    latitude: float,
    longitude: float,
    radius_km: float,
) -> Region:
    """The aftershock zone as a :class:`~rupture.domain.Region`, inheriting the parent's settings.

    Everything that decides what a forecast means -- the completeness estimate, the target
    threshold, the magnitude binning, the depth range -- is taken from the published parent region
    (``data/regions/<id>/region.json``) rather than invented for the sequence. Only the polygon
    and the identity differ.
    """
    return parent.model_copy(
        update={
            "id": region_id,
            "name": name,
            "polygon": zone_polygon(latitude, longitude, radius_km),
            "description": (
                f"Aftershock zone of {name}: circle of radius {radius_km:.0f} km about "
                f"({latitude:.4f} N, {longitude:.4f} E), from Wells & Coppersmith (1994) "
                f"subsurface rupture length times {ZONE_MULTIPLIER}. Thresholds, Mc, depth range "
                f"and binning inherited from region {parent.id!r}."
            ),
        }
    )


def sequence_catalog(
    catalog: Catalog,
    *,
    mainshock_time: datetime,
    latitude: float,
    longitude: float,
    radius_km: float,
    suffix: str = "sequence",
) -> Catalog:
    """Events at or after the mainshock and within the aftershock-zone radius.

    This is the *sequence*, used for reporting ``n_sequence_events`` and for the sequence-specific
    diagnostics. It is not the ETAS training slice: a fit also needs the pre-mainshock seismicity
    of the same zone, which is what supplies the auxiliary window and the background rate.
    """
    if not catalog.events:
        return catalog.model_copy(update={"events": (), "id": f"{catalog.id}/{suffix}"})
    lats = np.fromiter((e.latitude for e in catalog.events), dtype=np.float64, count=len(catalog))
    lons = np.fromiter((e.longitude for e in catalog.events), dtype=np.float64, count=len(catalog))
    distance = epicentral_distance_km(latitude, longitude, lats, lons)
    kept = tuple(
        e
        for e, d in zip(catalog.events, distance.tolist(), strict=True)
        if e.origin_time >= mainshock_time and d <= radius_km
    )
    return catalog.model_copy(update={"events": kept, "id": f"{catalog.id}/{suffix}"})
