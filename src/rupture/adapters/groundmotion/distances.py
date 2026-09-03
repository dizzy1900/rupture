"""Source-to-site distance metrics from a :class:`~rupture.domain.hazard.ScenarioRupture`.

The GSIMs rupture ships need ``rjb`` (BSSA14) and ``rrup`` (BC Hydro); ``rx``, ``ztor`` and
``rhypo`` are computed too, because other GSIMs and the engine cross-check want them and because
a metric that is silently zero is worse than one that is absent.

Geometry. A rupture with four ``corners`` is treated as a planar quadrilateral in the order
OpenQuake's ``planarSurface`` uses — top-left, top-right, bottom-right, bottom-left — where
"top" is the shallow edge and left/right follow the strike. Sites and corners are projected to a
local azimuthal-equidistant frame centred on the rupture's surface centroid (east ``x``, north
``y``, down ``z``, kilometres): distances from that centre are exact great-circle distances and
the local distortion over a corridor of a few hundred kilometres is small. Distances are then
exact in that frame — point-to-triangle in three dimensions for ``rrup``, point-to-polygon in two
for ``rjb`` — rather than being read off a discretised mesh.

A rupture with no corners is a **point rupture** at the hypocentre: ``rjb`` is the epicentral
distance, ``rrup`` the hypocentral distance, ``ztor`` the hypocentral depth and ``rx`` zero.
rupture does not invent a fault plane from magnitude; a scenario that needs a finite fault
supplies its corners, with a citation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from rupture.domain.groundmotion import Site
from rupture.domain.hazard import ScenarioRupture

FloatArray = npt.NDArray[np.float64]

EARTH_RADIUS_KM = 6371.0
"""Mean Earth radius, matching OpenQuake's ``hazardlib.geo.geodetic.EARTH_RADIUS``."""

PLANAR_CORNERS = 4


class GeometryError(ValueError):
    """The rupture geometry cannot be interpreted."""


@dataclass(frozen=True, slots=True)
class Distances:
    """One value per site, kilometres."""

    rjb: FloatArray
    rrup: FloatArray
    rx: FloatArray
    rhypo: FloatArray
    ztor: float


def local_frame(
    origin_lon: float, origin_lat: float, lons: FloatArray, lats: FloatArray
) -> tuple[FloatArray, FloatArray]:
    """Azimuthal-equidistant projection about ``(origin_lon, origin_lat)``, in kilometres."""
    lat0 = math.radians(origin_lat)
    lon0 = math.radians(origin_lon)
    lat = np.radians(lats)
    lon = np.radians(lons)
    dlon = lon - lon0
    # great-circle distance (haversine) and initial bearing from the origin
    a = np.sin((lat - lat0) / 2.0) ** 2 + math.cos(lat0) * np.cos(lat) * np.sin(dlon / 2.0) ** 2
    distance = 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    bearing = np.arctan2(
        np.sin(dlon) * np.cos(lat),
        math.cos(lat0) * np.sin(lat) - math.sin(lat0) * np.cos(lat) * np.cos(dlon),
    )
    return distance * np.sin(bearing), distance * np.cos(bearing)


def from_local_frame(
    origin_lon: float, origin_lat: float, x_km: FloatArray, y_km: FloatArray
) -> tuple[FloatArray, FloatArray]:
    """Inverse of :func:`local_frame`: local east/north kilometres back to (lon, lat) degrees."""
    lat0 = math.radians(origin_lat)
    lon0 = math.radians(origin_lon)
    distance = np.hypot(x_km, y_km) / EARTH_RADIUS_KM
    bearing = np.arctan2(x_km, y_km)
    lat = np.arcsin(
        math.sin(lat0) * np.cos(distance) + math.cos(lat0) * np.sin(distance) * np.cos(bearing)
    )
    lon = lon0 + np.arctan2(
        np.sin(bearing) * np.sin(distance) * math.cos(lat0),
        np.cos(distance) - math.sin(lat0) * np.sin(lat),
    )
    return np.degrees((lon + np.pi) % (2.0 * np.pi) - np.pi), np.degrees(lat)


def _point_segment_distance(p: FloatArray, a: FloatArray, b: FloatArray) -> FloatArray:
    """Distance from points ``p`` (n, d) to the segment ``ab``, in any dimension."""
    ab = b - a
    denominator = float(ab @ ab)
    if denominator == 0.0:
        return np.linalg.norm(p - a, axis=1)
    t = np.clip((p - a) @ ab / denominator, 0.0, 1.0)
    closest = a + t[:, None] * ab
    return np.linalg.norm(p - closest, axis=1)


def _point_triangle_distance(
    p: FloatArray, a: FloatArray, b: FloatArray, c: FloatArray
) -> FloatArray:
    """Distance from points ``p`` (n, 3) to the triangle ``abc``.

    The projection of a point onto the triangle's plane is used when it falls inside the
    triangle (checked with barycentric coordinates); otherwise the nearest edge governs.
    """
    normal = np.cross(b - a, c - a)
    norm = float(np.linalg.norm(normal))
    edges = np.minimum(
        np.minimum(_point_segment_distance(p, a, b), _point_segment_distance(p, b, c)),
        _point_segment_distance(p, c, a),
    )
    if norm == 0.0:  # degenerate triangle: the edges are the whole of it
        return edges
    unit = normal / norm
    signed = (p - a) @ unit
    projected = p - signed[:, None] * unit
    inside = _inside_triangle(projected, a, b, c)
    return np.where(inside, np.abs(signed), edges)


def _inside_triangle(
    q: FloatArray, a: FloatArray, b: FloatArray, c: FloatArray
) -> npt.NDArray[np.bool_]:
    v0, v1 = b - a, c - a
    v2 = q - a
    d00, d01, d11 = float(v0 @ v0), float(v0 @ v1), float(v1 @ v1)
    d20, d21 = v2 @ v0, v2 @ v1
    denominator = d00 * d11 - d01 * d01
    if denominator == 0.0:  # pragma: no cover - guarded by the caller
        return np.zeros(len(q), dtype=np.bool_)
    v = (d11 * d20 - d01 * d21) / denominator
    w = (d00 * d21 - d01 * d20) / denominator
    return (v >= 0.0) & (w >= 0.0) & (v + w <= 1.0)


def _polygon_distance(p: FloatArray, polygon: FloatArray) -> FloatArray:
    """2-D distance from points ``p`` (n, 2) to a convex polygon, zero inside it."""
    n = len(polygon)
    edge = np.full(len(p), np.inf)
    for i in range(n):
        edge = np.minimum(edge, _point_segment_distance(p, polygon[i], polygon[(i + 1) % n]))
    return np.where(_inside_polygon(p, polygon), 0.0, edge)


def _inside_polygon(p: FloatArray, polygon: FloatArray) -> npt.NDArray[np.bool_]:
    """Ray-casting point-in-polygon; the polygon need not be convex or wound consistently."""
    inside = np.zeros(len(p), dtype=np.bool_)
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        crosses = (y1 > p[:, 1]) != (y2 > p[:, 1])
        with np.errstate(divide="ignore", invalid="ignore"):
            x_at = (x2 - x1) * (p[:, 1] - y1) / np.where(y2 == y1, np.nan, y2 - y1) + x1
        inside ^= crosses & (p[:, 0] < x_at)
    return inside


def rupture_corners_km(
    rupture: ScenarioRupture,
) -> tuple[FloatArray, tuple[float, float]]:
    """Rupture corners in the local frame (m, 3) plus the projection origin (lon, lat)."""
    if not rupture.corners:
        origin = (rupture.hypocentre_longitude, rupture.hypocentre_latitude)
        return np.zeros((0, 3), dtype=np.float64), origin
    if len(rupture.corners) != PLANAR_CORNERS:
        msg = (
            f"a finite rupture needs exactly {PLANAR_CORNERS} corners "
            f"(top-left, top-right, bottom-right, bottom-left), got {len(rupture.corners)}"
        )
        raise GeometryError(msg)
    lons = np.array([c[0] for c in rupture.corners], dtype=np.float64)
    lats = np.array([c[1] for c in rupture.corners], dtype=np.float64)
    depths = np.array([c[2] for c in rupture.corners], dtype=np.float64)
    if (depths < 0.0).any():
        msg = "rupture corner depths must be non-negative (kilometres below the surface)"
        raise GeometryError(msg)
    origin = (float(lons.mean()), float(lats.mean()))
    x, y = local_frame(origin[0], origin[1], lons, lats)
    return np.column_stack([x, y, depths]), origin


def distances(rupture: ScenarioRupture, sites: tuple[Site, ...]) -> Distances:
    """Every distance metric the shipped GSIMs need, for one rupture and a set of sites."""
    if not sites:
        msg = "at least one site is required"
        raise GeometryError(msg)
    corners, origin = rupture_corners_km(rupture)
    site_lons = np.array([s.longitude for s in sites], dtype=np.float64)
    site_lats = np.array([s.latitude for s in sites], dtype=np.float64)
    sx, sy = local_frame(origin[0], origin[1], site_lons, site_lats)
    surface = np.column_stack([sx, sy])
    space = np.column_stack([sx, sy, np.zeros_like(sx)])

    hx, hy = local_frame(
        origin[0],
        origin[1],
        np.array([rupture.hypocentre_longitude]),
        np.array([rupture.hypocentre_latitude]),
    )
    hypocentre = np.array([hx[0], hy[0], rupture.hypocentre_depth_km])
    rhypo = np.linalg.norm(space - hypocentre, axis=1)

    if len(corners) == 0:
        repi = np.linalg.norm(surface - hypocentre[:2], axis=1)
        return Distances(
            rjb=repi,
            rrup=rhypo,
            rx=np.zeros_like(repi),
            rhypo=rhypo,
            ztor=rupture.hypocentre_depth_km,
        )

    top_left, top_right, bottom_right, bottom_left = corners
    rrup = np.minimum(
        _point_triangle_distance(space, top_left, top_right, bottom_right),
        _point_triangle_distance(space, top_left, bottom_right, bottom_left),
    )
    rjb = _polygon_distance(surface, corners[:, :2])
    rx = _rx(surface, top_left[:2], top_right[:2])
    return Distances(rjb=rjb, rrup=rrup, rx=rx, rhypo=rhypo, ztor=float(corners[:, 2].min()))


def _rx(surface: FloatArray, top_left: FloatArray, top_right: FloatArray) -> FloatArray:
    """Signed horizontal distance from the top-edge trace, positive on the hanging wall.

    The strike direction runs top-left to top-right; the hanging wall is to its right, which is
    the Aki-Richards convention the corner ordering already assumes.
    """
    strike = top_right - top_left
    length = float(np.linalg.norm(strike))
    if length == 0.0:
        msg = "the rupture's top edge has zero length"
        raise GeometryError(msg)
    unit = strike / length
    right = np.array([unit[1], -unit[0]])
    result: FloatArray = (surface - top_left) @ right
    return result
