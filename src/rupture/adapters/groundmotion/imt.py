"""Intensity measure types, in OpenQuake's spelling.

``PGA`` and ``PGV`` are named measures; ``SA(0.3)`` is 5 %-damped spectral acceleration at a
period. Only 5 % damping is supported, which is what every GSIM rupture ships is defined for.
Units follow OpenQuake: g for PGA and SA, cm/s for PGV.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SA = re.compile(r"^SA\(\s*([0-9]*\.?[0-9]+)\s*\)$", re.IGNORECASE)

DAMPING = 5.0
"""The only damping rupture supports, in per cent of critical."""


class ImtError(ValueError):
    """The intensity measure type is not one rupture understands."""


@dataclass(frozen=True, slots=True, order=True)
class Imt:
    """One intensity measure type. ``period`` is ``None`` for PGA and PGV."""

    name: str
    period: float | None = None

    def __str__(self) -> str:
        return self.name if self.period is None else f"SA({self.period:g})"

    @property
    def unit(self) -> str:
        return "cm/s" if self.name == "PGV" else "g"


PGA = Imt("PGA")
PGV = Imt("PGV")


def parse(text: str) -> Imt:
    """``'PGA'``, ``'pgv'``, ``'SA(0.3)'`` -> :class:`Imt`. Anything else raises."""
    token = text.strip()
    upper = token.upper()
    if upper in {"PGA", "PGV"}:
        return Imt(upper)
    match = _SA.match(token)
    if match is None:
        msg = f"unsupported intensity measure type {text!r}; use PGA, PGV or SA(<period>)"
        raise ImtError(msg)
    period = float(match.group(1))
    if period <= 0.0:
        msg = f"SA period must be positive, got {period}"
        raise ImtError(msg)
    return Imt("SA", period)


def parse_column(text: str) -> Imt | None:
    """Parse a verification-table column header, which is ``pga``, ``pgv`` or a bare period.

    Returns ``None`` for a column that is not an intensity measure (``rup_mag``, ``damping``...).
    """
    token = text.strip()
    upper = token.upper()
    if upper in {"PGA", "PGV"}:
        return Imt(upper)
    try:
        period = float(token)
    except ValueError:
        return None
    if period <= 0.0:
        return None
    return Imt("SA", period)
