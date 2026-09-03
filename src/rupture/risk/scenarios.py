"""The ruptures rupture prices a portfolio against.

Three sources, kept visibly different from one another:

1. **A Gorkha 2015 repeat** — the plane is derived from the USGS NEIC finite-fault inversion for
   ``us20002926`` (committed under ``tests/fixtures/risk/scenarios/gorkha2015/``), not chosen.
   ``hypothetical`` is ``False``: this is a published rupture model.
2. **An MHT M8+ hypothetical** — a Main Himalayan Thrust rupture reaching the surface at the Main
   Frontal Thrust, with its extent taken from published constraints on the great central-Himalayan
   earthquakes and its magnitude computed from the resulting area and a stated average slip.
   ``hypothetical`` is ``True`` and every report says so.
3. **A stochastic event set** — the interface an ETAS catalogue plugs into. The interface is here;
   the event sets are not, and :func:`from_stochastic_event` is explicit that an event without a
   finite-fault solution becomes a **point rupture**, which is a weaker geometry, not a hidden one.

Nothing in this module invents a fault plane from a magnitude. A rupture either has a published
geometry, or a documented hypothetical one, or it is a point.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rupture.adapters.groundmotion.distances import from_local_frame, local_frame
from rupture.domain.hazard import ScenarioRupture

FIXTURE_REL = Path("tests") / "fixtures" / "risk" / "scenarios"
GORKHA_DIR = "gorkha2015"
GORKHA_FSP = "complete_inversion.fsp"

GORKHA_SOURCE_REF = (
    "USGS NEIC finite-fault inversion for the 2015-04-25 Mw 7.8 Gorkha, Nepal earthquake "
    "(event us20002926), SRCMOD FSP format; https://earthquake.usgs.gov/earthquakes/eventpage/"
    "us20002926/finite-fault"
)
MOMENT_FRACTION = 0.90
"""The rupture surface is the smallest rectangle in fault coordinates holding this much slip.

The inversion grid is deliberately larger than the area that actually slipped (193 x 168 km for
Gorkha), so using the whole grid would put the rupture implausibly close to sites. rupture trims
whole rows and columns from the edges of the grid, always the one carrying the least slip, while
at least ``MOMENT_FRACTION`` of the total slip remains. On a uniform sub-fault grid at constant
rigidity, slip and seismic moment are proportional, so this is the smallest rectangle holding 90 %
of the released moment. The threshold is a stated modelling choice; ``docs/RISK.md`` reports what
other values do to the corridor's distances, and it is a parameter, not a constant in a formula.
"""

RIGIDITY_PA = 3.3e10
"""Shear modulus used in the moment calculation, Pa. A standard crustal value."""


class ScenarioError(ValueError):
    """The scenario cannot be built."""


# --------------------------------------------------------------------- FSP parsing
@dataclass(frozen=True, slots=True)
class FspModel:
    """The parts of a SRCMOD ``.fsp`` finite-source model rupture uses."""

    hypocentre_lon: float
    hypocentre_lat: float
    hypocentre_depth_km: float
    magnitude: float
    strike: float
    dip: float
    rake: float
    dx_km: float
    dz_km: float
    lons: np.ndarray
    lats: np.ndarray
    depths_km: np.ndarray
    slips_m: np.ndarray


_HEADER = {
    "lat": re.compile(r"LAT\s*=\s*(-?\d+\.?\d*)"),
    "lon": re.compile(r"LON\s*=\s*(-?\d+\.?\d*)"),
    "dep": re.compile(r"DEP\s*=\s*(-?\d+\.?\d*)"),
    "mw": re.compile(r"Mw\s*=\s*(-?\d+\.?\d*)"),
    "strike": re.compile(r"STRK\s*=\s*(-?\d+\.?\d*)"),
    "dip": re.compile(r"DIP\s*=\s*(-?\d+\.?\d*)"),
    "rake": re.compile(r"RAKE\s*=\s*(-?\d+\.?\d*)"),
    "dx": re.compile(r"Dx\s*=\s*(-?\d+\.?\d*)"),
    "dz": re.compile(r"Dz\s*=\s*(-?\d+\.?\d*)"),
}
MIN_FSP_COLUMNS = 6


def parse_fsp(text: str) -> FspModel:
    """Read a SRCMOD ``.fsp`` file: the header parameters and the sub-fault table."""
    values: dict[str, float] = {}
    for name, pattern in _HEADER.items():
        match = pattern.search(text)
        if match is None:
            msg = f"the FSP file has no {name.upper()} in its header"
            raise ScenarioError(msg)
        values[name] = float(match.group(1))
    rows = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%"):
            continue
        cells = stripped.split()
        if len(cells) < MIN_FSP_COLUMNS:
            continue
        try:
            rows.append([float(c) for c in cells[:6]])
        except ValueError:
            continue
    if not rows:
        msg = "the FSP file has no sub-fault rows"
        raise ScenarioError(msg)
    table = np.asarray(rows, dtype=np.float64)
    return FspModel(
        hypocentre_lon=values["lon"],
        hypocentre_lat=values["lat"],
        hypocentre_depth_km=values["dep"],
        magnitude=values["mw"],
        strike=values["strike"],
        dip=values["dip"],
        rake=values["rake"],
        dx_km=values["dx"],
        dz_km=values["dz"],
        lats=table[:, 0],
        lons=table[:, 1],
        depths_km=table[:, 4],
        slips_m=table[:, 5],
    )


def _fault_coordinates(model: FspModel) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sub-fault positions in fault coordinates: along-strike km, perpendicular km, depth, index."""
    strike = math.radians(model.strike)
    along = np.array([math.sin(strike), math.cos(strike)])
    down_dip = np.array([math.cos(strike), -math.sin(strike)])
    x, y = local_frame(model.hypocentre_lon, model.hypocentre_lat, model.lons, model.lats)
    s = x * along[0] + y * along[1]
    p = x * down_dip[0] + y * down_dip[1]
    return s, p, model.depths_km, np.array([along, down_dip])


def _trim(
    s: np.ndarray,
    depths: np.ndarray,
    slips: np.ndarray,
    *,
    dx_km: float,
    dz_km: float,
    dip: float,
    moment_fraction: float,
) -> np.ndarray:
    """Boolean mask of the smallest grid rectangle holding ``moment_fraction`` of the slip."""
    columns = np.rint((s - s.min()) / dx_km).astype(int)
    rows = np.rint((depths - depths.min()) / (dz_km * math.sin(dip))).astype(int)
    total = float(slips.sum())
    if total <= 0.0:
        msg = "the finite-fault model has no positive slip"
        raise ScenarioError(msg)
    c0, c1 = int(columns.min()), int(columns.max())
    r0, r1 = int(rows.min()), int(rows.max())
    while c1 > c0 and r1 > r0:
        inside = (columns >= c0) & (columns <= c1) & (rows >= r0) & (rows <= r1)
        edges = {
            "c0": float(slips[inside & (columns == c0)].sum()),
            "c1": float(slips[inside & (columns == c1)].sum()),
            "r0": float(slips[inside & (rows == r0)].sum()),
            "r1": float(slips[inside & (rows == r1)].sum()),
        }
        smallest = min(edges, key=lambda k: edges[k])
        if (float(slips[inside].sum()) - edges[smallest]) / total < moment_fraction:
            break
        if smallest == "c0":
            c0 += 1
        elif smallest == "c1":
            c1 -= 1
        elif smallest == "r0":
            r0 += 1
        else:
            r1 -= 1
    mask: np.ndarray = (columns >= c0) & (columns <= c1) & (rows >= r0) & (rows <= r1)
    return mask


@dataclass(frozen=True, slots=True)
class EffectiveRupture:
    """The trimmed rupture surface and the numbers a report should quote about it."""

    corners: tuple[tuple[float, float, float], ...]
    length_km: float
    width_km: float
    ztor_km: float
    retained_slip_fraction: float


def effective_rupture(
    model: FspModel, *, moment_fraction: float = MOMENT_FRACTION
) -> EffectiveRupture:
    """The planar surface of the effective rupture, in OpenQuake's corner order.

    Corners run top-left, top-right, bottom-right, bottom-left, where left-to-right follows the
    strike and the hanging wall lies to its right.
    """
    dip = math.radians(model.dip)
    s, p, depths, basis = _fault_coordinates(model)
    keep = _trim(
        s,
        depths,
        model.slips_m,
        dx_km=model.dx_km,
        dz_km=model.dz_km,
        dip=dip,
        moment_fraction=moment_fraction,
    )
    half_vertical = 0.5 * model.dz_km * math.sin(dip)
    z_top = max(float(depths[keep].min()) - half_vertical, 0.0)
    z_bottom = float(depths[keep].max()) + half_vertical
    s_min = float(s[keep].min()) - 0.5 * model.dx_km
    s_max = float(s[keep].max()) + 0.5 * model.dx_km

    # For a plane, p - z / tan(dip) is constant; the median absorbs rounding in the sub-fault table.
    intercept = float(np.median(p[keep] - depths[keep] / math.tan(dip)))
    p_top = intercept + z_top / math.tan(dip)
    p_bottom = intercept + z_bottom / math.tan(dip)

    along, down_dip = basis
    local = [
        (s_min, p_top, z_top),
        (s_max, p_top, z_top),
        (s_max, p_bottom, z_bottom),
        (s_min, p_bottom, z_bottom),
    ]
    xs = np.array([a * along[0] + b * down_dip[0] for a, b, _ in local])
    ys = np.array([a * along[1] + b * down_dip[1] for a, b, _ in local])
    lons, lats = from_local_frame(model.hypocentre_lon, model.hypocentre_lat, xs, ys)
    corners = tuple(
        (float(lon), float(lat), float(z))
        for lon, lat, (_, _, z) in zip(lons, lats, local, strict=True)
    )
    return EffectiveRupture(
        corners=corners,
        length_km=s_max - s_min,
        width_km=(z_bottom - z_top) / math.sin(dip),
        ztor_km=z_top,
        retained_slip_fraction=float(model.slips_m[keep].sum() / model.slips_m.sum()),
    )


# --------------------------------------------------------------------- scenarios
def gorkha_2015_repeat(
    repo_root: Path, *, moment_fraction: float = MOMENT_FRACTION
) -> ScenarioRupture:
    """A repeat of the 2015 Gorkha earthquake, on the published USGS rupture plane."""
    path = repo_root / FIXTURE_REL / GORKHA_DIR / GORKHA_FSP
    if not path.is_file():
        msg = f"the Gorkha finite-fault model is not committed at {path}"
        raise ScenarioError(msg)
    model = parse_fsp(path.read_text(encoding="utf-8", errors="replace"))
    surface = effective_rupture(model, moment_fraction=moment_fraction)
    return ScenarioRupture(
        id="gorkha-2015-repeat",
        magnitude=model.magnitude,
        hypocentre_longitude=model.hypocentre_lon,
        hypocentre_latitude=model.hypocentre_lat,
        hypocentre_depth_km=model.hypocentre_depth_km,
        strike=model.strike,
        dip=model.dip,
        rake=model.rake,
        tectonic_region="Active Shallow Crust",
        corners=surface.corners,
        source_refs=(GORKHA_SOURCE_REF,),
        hypothetical=False,
        notes=(
            f"effective rupture from the USGS inversion: the smallest grid rectangle holding "
            f"{surface.retained_slip_fraction:.0%} of the slip, {surface.length_km:.0f} km along "
            f"strike by {surface.width_km:.0f} km down dip, top of rupture "
            f"{surface.ztor_km:.1f} km. The full inversion grid is 193 x 168 km."
        ),
    )


MHT_LENGTH_KM = 250.0
MHT_DIP_DEG = 7.0
MHT_STRIKE_DEG = 293.0
MHT_RAKE_DEG = 101.0
MHT_BOTTOM_DEPTH_KM = 20.0
MHT_AVERAGE_SLIP_M = 5.0
MHT_TOP_LON = 85.20
MHT_TOP_LAT = 27.30
"""A point on the Main Frontal Thrust trace south of the Trishuli corridor, in central Nepal."""

MHT_SOURCE_REFS: tuple[str, ...] = (
    "Bollinger, L. et al. (2014). Estimating the return times of great Himalayan earthquakes in "
    "eastern Nepal: evidence from the Patu and Bardibas strands of the Main Frontal Thrust. "
    "Journal of Geophysical Research: Solid Earth 119(9), 7123-7163. doi:10.1002/2014JB010970",
    "Sapkota, S.N. et al. (2013). Primary surface ruptures of the great Himalayan earthquakes in "
    "1934 and 1255. Nature Geoscience 6, 71-76. doi:10.1038/ngeo1669",
    "Stevens, V.L. & Avouac, J.-P. (2016). Millenary Mw > 9.0 earthquakes required by geodetic "
    "strain in the Himalaya. Geophysical Research Letters 43(3), 1118-1123. "
    "doi:10.1002/2015GL067336",
    "Hanks, T.C. & Kanamori, H. (1979). A moment magnitude scale. Journal of Geophysical Research "
    "84(B5), 2348-2350. doi:10.1029/JB084iB05p02348",
)


def moment_magnitude(area_km2: float, average_slip_m: float, rigidity_pa: float) -> float:
    """Hanks & Kanamori (1979): Mw = (2/3)(log10 M0 - 9.1), with M0 = mu * A * D in N m."""
    moment = rigidity_pa * area_km2 * 1.0e6 * average_slip_m
    return (2.0 / 3.0) * (math.log10(moment) - 9.1)


def mht_hypothetical(
    *,
    length_km: float = MHT_LENGTH_KM,
    bottom_depth_km: float = MHT_BOTTOM_DEPTH_KM,
    average_slip_m: float = MHT_AVERAGE_SLIP_M,
) -> ScenarioRupture:
    """A hypothetical Main Himalayan Thrust rupture that reaches the surface at the MFT.

    The geometry is set from published constraints rather than from a magnitude-scaling relation:
    a shallowly north-dipping decollement (7 degrees, as resolved for Gorkha), rupturing from the
    Main Frontal Thrust trace (``ztor = 0``, as documented for the 1255 and 1934 events) down dip
    to ``bottom_depth_km``, over ``length_km`` along strike. The magnitude is then **computed**
    from that area and a stated average slip through Hanks & Kanamori (1979) - it is an output of
    the geometry, not an input, so the two cannot disagree.
    """
    dip = math.radians(MHT_DIP_DEG)
    width_km = bottom_depth_km / math.sin(dip)
    magnitude = moment_magnitude(length_km * width_km, average_slip_m, RIGIDITY_PA)

    strike = math.radians(MHT_STRIKE_DEG)
    along = np.array([math.sin(strike), math.cos(strike)])
    down_dip = np.array([math.cos(strike), -math.sin(strike)])
    horizontal = width_km * math.cos(dip)
    local = [
        (-0.5 * length_km, 0.0, 0.0),
        (0.5 * length_km, 0.0, 0.0),
        (0.5 * length_km, horizontal, bottom_depth_km),
        (-0.5 * length_km, horizontal, bottom_depth_km),
    ]
    xs = np.array([a * along[0] + b * down_dip[0] for a, b, _ in local])
    ys = np.array([a * along[1] + b * down_dip[1] for a, b, _ in local])
    lons, lats = from_local_frame(MHT_TOP_LON, MHT_TOP_LAT, xs, ys)
    corners = tuple(
        (float(lon), float(lat), float(z))
        for lon, lat, (_, _, z) in zip(lons, lats, local, strict=True)
    )
    # hypocentre at mid-length, mid-width, which is where the decollement is locked
    hx = np.array([0.5 * horizontal * down_dip[0]])
    hy = np.array([0.5 * horizontal * down_dip[1]])
    hlon, hlat = from_local_frame(MHT_TOP_LON, MHT_TOP_LAT, hx, hy)
    return ScenarioRupture(
        id="mht-m8-hypothetical",
        magnitude=round(magnitude, 2),
        hypocentre_longitude=float(hlon[0]),
        hypocentre_latitude=float(hlat[0]),
        hypocentre_depth_km=0.5 * bottom_depth_km,
        strike=MHT_STRIKE_DEG,
        dip=MHT_DIP_DEG,
        rake=MHT_RAKE_DEG,
        tectonic_region="Active Shallow Crust",
        corners=corners,
        source_refs=MHT_SOURCE_REFS,
        hypothetical=True,
        notes=(
            f"HYPOTHETICAL. {length_km:g} km along strike by {width_km:.0f} km down dip, surface "
            f"rupture at the MFT, {average_slip_m:g} m average slip; magnitude computed from that "
            "area, not assumed. Not a forecast of any particular event."
        ),
    )


def from_stochastic_event(
    *,
    event_id: str,
    magnitude: float,
    longitude: float,
    latitude: float,
    depth_km: float,
    strike: float = 293.0,
    dip: float = 7.0,
    rake: float = 101.0,
    corners: tuple[tuple[float, float, float], ...] = (),
    source_ref: str | None = None,
) -> ScenarioRupture:
    """One rupture of a stochastic event set (an ETAS catalogue, say).

    This is the hook C2 offers C1: an event set supplies magnitude, location and, where it has one,
    a finite-fault geometry. When ``corners`` is empty the result is a **point rupture** - Rjb is
    the epicentral distance and Rrup the hypocentral distance - because rupture will not
    manufacture a fault plane from a magnitude. The note on the returned rupture says which it is,
    and the loss report repeats it.
    """
    finite = len(corners) == 4
    return ScenarioRupture(
        id=event_id,
        magnitude=magnitude,
        hypocentre_longitude=longitude,
        hypocentre_latitude=latitude,
        hypocentre_depth_km=depth_km,
        strike=strike,
        dip=dip,
        rake=rake,
        tectonic_region="Active Shallow Crust",
        corners=corners,
        source_refs=(source_ref,) if source_ref else (),
        hypothetical=True,
        notes=(
            "stochastic event set member; finite geometry supplied by the event set"
            if finite
            else (
                "stochastic event set member with no finite-fault geometry: evaluated as a POINT "
                "rupture, so Rjb is the epicentral distance. Distances are therefore longer than "
                "a finite rupture of this magnitude would give, and the loss is a lower estimate."
            )
        ),
    )


def builtin(repo_root: Path) -> dict[str, ScenarioRupture]:
    """The scenarios ``rupture risk run --scenario`` knows by name."""
    return {
        "gorkha-2015-repeat": gorkha_2015_repeat(repo_root),
        "mht-m8-hypothetical": mht_hypothetical(),
    }
