"""GSIM coefficient tables, read from the files in ``data/``.

The file format is OpenQuake's: a whitespace-separated table whose first column is ``IMT``
(``pga``, ``pgv`` or a bare period) and whose remaining columns are named coefficients. rupture
carries the tables as data rather than as code so their provenance can be checked
(``data/provenance.json``); they are never re-typed by hand.

Lookup for a spectral period that is not a row of the table interpolates **linearly in the
logarithm of period** between the bracketing rows, and refuses to extrapolate. That is what
OpenQuake's ``CoeffsTable`` does (``openquake/hazardlib/gsim/coeffs_table.py``, the default
``opt=0``/``logratio=True`` branch), and reproducing it exactly is a precondition for reproducing
the published expected values at periods the coefficient table does not list.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Final

from rupture.adapters.groundmotion.imt import Imt, parse_column

DATA_PACKAGE: Final = "rupture.adapters.groundmotion.data"


class CoeffTableError(KeyError):
    """The table has no row for this IMT and none can be interpolated."""


@dataclass(frozen=True, slots=True)
class CoeffTable:
    """Named coefficients per IMT, with log-period interpolation for spectral acceleration."""

    names: tuple[str, ...]
    named_rows: dict[str, dict[str, float]]
    """Rows keyed by a non-spectral IMT name (``PGA``, ``PGV``)."""
    sa_periods: tuple[float, ...]
    """Ascending periods of the spectral-acceleration rows."""
    sa_rows: tuple[dict[str, float], ...]

    @classmethod
    def from_text(cls, text: str) -> CoeffTable:
        lines = [ln for ln in text.strip().splitlines() if ln.strip()]
        header = lines[0].split()
        if header[0].upper() != "IMT":
            msg = f"first column of a coefficient table must be IMT, got {header[0]!r}"
            raise ValueError(msg)
        names = tuple(header[1:])
        named: dict[str, dict[str, float]] = {}
        sa: dict[float, dict[str, float]] = {}
        for line in lines[1:]:
            cells = line.split()
            if len(cells) != len(header):
                msg = f"row {cells[0]!r} has {len(cells)} cells, header has {len(header)}"
                raise ValueError(msg)
            imt = parse_column(cells[0])
            if imt is None:
                msg = f"unreadable IMT in coefficient table: {cells[0]!r}"
                raise ValueError(msg)
            row = {name: float(value) for name, value in zip(names, cells[1:], strict=True)}
            if imt.period is None:
                named[imt.name] = row
            else:
                sa[imt.period] = row
        periods = tuple(sorted(sa))
        return cls(names, named, periods, tuple(sa[p] for p in periods))

    @classmethod
    def from_data_file(cls, file_name: str) -> CoeffTable:
        """Read one of the committed tables under ``adapters/groundmotion/data/``."""
        text = resources.files(DATA_PACKAGE).joinpath(file_name).read_text(encoding="utf-8")
        return cls.from_text(text)

    def __getitem__(self, imt: Imt) -> dict[str, float]:
        if imt.period is None:
            try:
                return self.named_rows[imt.name]
            except KeyError as exc:
                msg = f"no {imt.name} row in this coefficient table"
                raise CoeffTableError(msg) from exc
        return self._spectral(imt.period)

    def _spectral(self, period: float) -> dict[str, float]:
        periods = self.sa_periods
        if not periods:
            msg = "this coefficient table has no spectral-acceleration rows"
            raise CoeffTableError(msg)
        below: int | None = None
        above: int | None = None
        for index, value in enumerate(periods):
            if value == period:
                return self.sa_rows[index]
            if value < period:
                below = index
            elif above is None:
                above = index
        if below is None or above is None:
            msg = (
                f"SA({period:g}) is outside the coefficient table's range "
                f"[{periods[0]:g}, {periods[-1]:g}]; extrapolation is refused"
            )
            raise CoeffTableError(msg)
        ratio = (math.log(period) - math.log(periods[below])) / (
            math.log(periods[above]) - math.log(periods[below])
        )
        low, high = self.sa_rows[below], self.sa_rows[above]
        return {name: (high[name] - low[name]) * ratio + low[name] for name in self.names}

    def supports(self, imt: Imt) -> bool:
        try:
            self[imt]
        except CoeffTableError:
            return False
        return True


@cache
def load(file_name: str) -> CoeffTable:
    """Cached read of a committed coefficient table."""
    return CoeffTable.from_data_file(file_name)
