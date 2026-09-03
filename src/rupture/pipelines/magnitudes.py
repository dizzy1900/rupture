"""Magnitude homogenisation to Mw (ADR-0017).

Precedence for the homogenised ``mw`` of a merged event, highest first:

1. GCMT Mw (from the scalar moment; ``identity:mwc``);
2. ISC-GEM Mw (``identity:mw``);
3. any moment magnitude reported by ISC or ComCat (``mww``, ``mwc``, ``mwb``, ``mwr``, ``mw``;
   ``identity:<type>``), the largest-network-first order being ISC then ComCat;
4. ``mb`` or ``Ms`` converted with Scordilis (2006), inside the published validity ranges;
5. nothing else: ``ML``, ``Md`` and unknown scales are **not** converted (no regional relation
   is cited for the three test regions), so ``mw = None`` and the pipeline logs
   ``MAGNITUDE_UNCONVERTIBLE``.

Scordilis, E. M. (2006), "Empirical global relations converting MS and mb to moment magnitude",
Journal of Seismology 10, 225-236, doi:10.1007/s10950-006-9012-4. Coefficients below are the
paper's ordinary-least-squares global relations::

    Mw = 0.85 mb + 1.03      for 3.5 <= mb <= 6.2   (slope +/- 0.04, intercept +/- 0.23)
    Mw = 0.67 Ms + 2.07      for 3.0 <= Ms <= 6.1   (slope +/- 0.005, intercept +/- 0.03)
    Mw = 0.99 Ms + 0.08      for 6.2 <= Ms <= 8.2   (slope +/- 0.02, intercept +/- 0.13)

Verification status (2026-09-03): the slopes 0.85, 0.67, 0.99 and the ranges were confirmed
against third-party citations of the paper; the intercepts 1.03, 2.07 and 0.08 match the brief
and the author's recollection of the paper but the paper itself was behind a paywall, so
ADR-0017 carries a ``verify`` note. Outside the validity ranges no conversion is applied.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rupture.domain import MagnitudeRecord, MagnitudeType

SCORDILIS_2006 = "scordilis2006"

# (from_type, lower, upper, slope, intercept)
SCORDILIS_TABLE: tuple[tuple[MagnitudeType, float, float, float, float], ...] = (
    (MagnitudeType.MB, 3.5, 6.2, 0.85, 1.03),
    (MagnitudeType.MS, 3.0, 6.1, 0.67, 2.07),
    (MagnitudeType.MS, 6.2, 8.2, 0.99, 0.08),
)

MOMENT_TYPES: tuple[MagnitudeType, ...] = (
    MagnitudeType.MWW,
    MagnitudeType.MWC,
    MagnitudeType.MWB,
    MagnitudeType.MWR,
    MagnitudeType.MW,
)

# Source precedence for a *reported* moment magnitude, highest first.
MW_SOURCE_PRECEDENCE: tuple[str, ...] = ("gcmt", "isc-gem", "isc", "usgs-comcat")


@dataclass(frozen=True, slots=True)
class SourcedMagnitude:
    """A magnitude record together with the catalogue that reported it."""

    source: str
    record: MagnitudeRecord


@dataclass(frozen=True, slots=True)
class MwResult:
    """Homogenised Mw with the method reference, or both ``None`` when unconvertible."""

    mw: float | None
    conversion: str | None
    detail: str


def scordilis_2006(mag_type: MagnitudeType, value: float) -> float | None:
    """Convert mb or Ms to Mw with Scordilis (2006); ``None`` outside the validity ranges."""
    for from_type, lo, hi, slope, intercept in SCORDILIS_TABLE:
        if mag_type == from_type and lo <= value <= hi:
            return round(slope * value + intercept, 2)
    return None


def _rank(source: str) -> int:
    try:
        return MW_SOURCE_PRECEDENCE.index(source)
    except ValueError:
        return len(MW_SOURCE_PRECEDENCE)


def preferred_mw(magnitudes: Iterable[SourcedMagnitude]) -> MwResult:
    """Pick the homogenised Mw for one merged event from every magnitude any source reported."""
    mags: Sequence[SourcedMagnitude] = tuple(magnitudes)
    # 1-3: reported moment magnitudes, by source precedence then by type order
    moment = [m for m in mags if m.record.type in MOMENT_TYPES]
    if moment:
        best = min(moment, key=lambda m: (_rank(m.source), MOMENT_TYPES.index(m.record.type)))
        return MwResult(
            mw=best.record.value,
            conversion=f"identity:{best.record.type.value}",
            detail=f"{best.record.type.value} {best.record.value:.2f} from {best.source}",
        )
    # 4: Scordilis conversions; prefer mb over Ms only by source precedence, then Ms first
    # (Ms saturates later than mb), both inside their validity ranges.
    convertible: list[tuple[int, int, SourcedMagnitude, float]] = []
    for m in mags:
        mw = scordilis_2006(m.record.type, m.record.value)
        if mw is not None:
            type_order = 0 if m.record.type == MagnitudeType.MS else 1
            convertible.append((_rank(m.source), type_order, m, mw))
    if convertible:
        convertible.sort(key=lambda t: (t[0], t[1]))
        _, _, m, mw = convertible[0]
        return MwResult(
            mw=mw,
            conversion=f"{SCORDILIS_2006}:{m.record.type.value}",
            detail=(
                f"{m.record.type.value} {m.record.value:.2f} from {m.source} -> Mw {mw:.2f} "
                f"(Scordilis 2006)"
            ),
        )
    kinds = sorted({f"{m.source}:{m.record.raw_type or m.record.type.value}" for m in mags})
    return MwResult(mw=None, conversion=None, detail=f"no accepted relation for {kinds}")
