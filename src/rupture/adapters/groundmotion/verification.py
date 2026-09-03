"""Check a native GSIM against OpenQuake's own committed expected values.

This is the mechanism ADR-0020 makes a precondition for shipping a GSIM: rupture's implementation
must reproduce the reference tables, and the check is executed rather than asserted in prose. The
tables live under ``tests/fixtures/risk/gsim/<name>/`` with a ``provenance.json``; the reader here
is production code because both the unit tests and ``validate-risk`` run it.

Table format (OpenQuake ``hazardlib/tests/gsim/data``): a header of ``rup_*``, ``dist_*`` and
``site_*`` input columns, then ``result_type``, ``damping``, then one column per intensity
measure (``pga``, ``pgv`` or a bare period). Values are the ground motion in the IMT's own unit
for ``MEAN`` rows and the natural-log standard deviation for the ``*_STDDEV`` rows.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from rupture.adapters.groundmotion.base import Gsim, GsimContext
from rupture.adapters.groundmotion.imt import Imt, parse_column

MEAN = "MEAN"
TOTAL = "TOTAL_STDDEV"
INTER = "INTER_EVENT_STDDEV"
INTRA = "INTRA_EVENT_STDDEV"

_INPUT_PREFIXES = ("rup_", "dist_", "site_")


class VerificationError(ValueError):
    """The verification table cannot be read, or names an IMT the GSIM does not support."""


@dataclass(frozen=True, slots=True)
class TableRow:
    inputs: dict[str, float]
    result_type: str
    values: dict[Imt, float]


@dataclass(frozen=True, slots=True)
class VerificationTable:
    """One parsed expected-value CSV."""

    path: Path
    imts: tuple[Imt, ...]
    rows: tuple[TableRow, ...]

    @classmethod
    def read(cls, path: Path) -> VerificationTable:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = [cell.strip() for cell in next(reader)]
            imt_columns = {i: parse_column(cell) for i, cell in enumerate(header)}
            imts = tuple(
                imt
                for i, imt in imt_columns.items()
                if imt is not None and not header[i].startswith(_INPUT_PREFIXES)
            )
            if not imts:
                msg = f"{path} has no intensity-measure columns"
                raise VerificationError(msg)
            if "result_type" not in header:
                msg = f"{path} has no result_type column"
                raise VerificationError(msg)
            type_index = header.index("result_type")
            input_columns = _prefixed(header)
            rows: list[TableRow] = []
            for cells in reader:
                if not cells:
                    continue
                inputs = {name: float(cells[i]) for i, name in input_columns}
                values = {
                    imt: float(cells[i])
                    for i, imt in imt_columns.items()
                    if imt is not None and not header[i].startswith(_INPUT_PREFIXES)
                }
                rows.append(TableRow(inputs, cells[type_index].strip(), values))
        return cls(path=path, imts=imts, rows=tuple(rows))


def _prefixed(header: list[str]) -> list[tuple[int, str]]:
    """``(column index, parameter name)`` for every ``rup_`` / ``dist_`` / ``site_`` column."""
    out: list[tuple[int, str]] = []
    for i, cell in enumerate(header):
        for prefix in _INPUT_PREFIXES:
            if cell.startswith(prefix):
                out.append((i, cell[len(prefix) :]))
                break
    return out


@dataclass
class Discrepancy:
    """Worst relative disagreement, in per cent, for one result type."""

    result_type: str
    max_percent: float = 0.0
    comparisons: int = 0
    worst: str = ""

    def observe(self, expected: float, got: float, where: str) -> None:
        self.comparisons += 1
        if expected == 0.0:
            percent = 0.0 if got == 0.0 else math.inf
        else:
            percent = abs(got - expected) / abs(expected) * 100.0
        if percent > self.max_percent:
            self.max_percent = percent
            self.worst = where


@dataclass
class VerificationReport:
    """What the check found, per result type. ``ok`` compares against the stated tolerances."""

    gsim: str
    discrepancies: dict[str, Discrepancy] = field(default_factory=dict)

    def worst(self, result_type: str) -> float:
        d = self.discrepancies.get(result_type)
        return d.max_percent if d else 0.0

    @property
    def comparisons(self) -> int:
        return sum(d.comparisons for d in self.discrepancies.values())

    def lines(self) -> list[str]:
        out = []
        for name in sorted(self.discrepancies):
            d = self.discrepancies[name]
            out.append(
                f"{self.gsim} {name}: max {d.max_percent:.4g} % over {d.comparisons} values"
                + (f" (worst at {d.worst})" if d.worst else "")
            )
        return out


def verify(
    gsim: Gsim,
    tables: dict[str, Path],
    *,
    imts: tuple[Imt, ...] | None = None,
) -> VerificationReport:
    """Run ``gsim`` over every row of every table and record the worst relative disagreement.

    ``tables`` maps a result type (``MEAN``, ``TOTAL_STDDEV``, ...) to the CSV that holds it.
    ``imts`` restricts the comparison to a subset of the table's intensity measures; by default
    every column the GSIM supports is compared and an unsupported column is a failure, not a
    silent skip.
    """
    report = VerificationReport(gsim=gsim.name)
    for result_type, path in sorted(tables.items()):
        table = VerificationTable.read(path)
        wanted = imts or table.imts
        missing = [str(i) for i in wanted if not gsim.supports(i)]
        if missing:
            msg = f"{gsim.name} does not support {', '.join(missing)} required by {path.name}"
            raise VerificationError(msg)
        discrepancy = report.discrepancies.setdefault(result_type, Discrepancy(result_type))
        for key, rows in _group_by_rupture(table.rows, result_type).items():
            ctx = _build_context(key, rows)
            for imt in wanted:
                got = _predicted(gsim, ctx, imt, result_type)
                for index, row in enumerate(rows):
                    discrepancy.observe(
                        row.values[imt],
                        float(got[index]),
                        f"{path.name} {imt} {dict(key)}",
                    )
    return report


def _group_by_rupture(
    rows: tuple[TableRow, ...], result_type: str
) -> dict[tuple[tuple[str, float], ...], list[TableRow]]:
    """Rows sharing rupture-level parameters are evaluated in one vectorised call."""
    groups: dict[tuple[tuple[str, float], ...], list[TableRow]] = defaultdict(list)
    for row in rows:
        if row.result_type != result_type:
            continue
        key = tuple(sorted((k, v) for k, v in row.inputs.items() if k in _RUPTURE_PARAMS))
        groups[key].append(row)
    return groups


_RUPTURE_PARAMS = frozenset({"mag", "rake", "hypo_depth", "ztor", "dip", "width"})
_DISTANCES = ("rjb", "rrup", "rx", "rhypo")


def _build_context(key: tuple[tuple[str, float], ...], rows: list[TableRow]) -> GsimContext:
    rup = dict(key)
    columns: dict[str, list[float]] = {name: [] for name in ("vs30", "backarc", *_DISTANCES)}
    for row in rows:
        for name, collected in columns.items():
            collected.append(row.inputs.get(name, math.nan))
    vs30 = np.asarray(columns["vs30"], dtype=np.float64)
    if np.isnan(vs30).any():
        msg = "verification table has no site_vs30 column"
        raise VerificationError(msg)
    given = {
        name: np.asarray(columns[name], dtype=np.float64)
        for name in _DISTANCES
        if not np.isnan(columns[name]).any()
    }
    if not given:
        msg = "verification table has no distance column"
        raise VerificationError(msg)
    fallback = next(iter(given.values()))
    distances = {name: given.get(name, fallback) for name in _DISTANCES}
    backarc = np.asarray(columns["backarc"], dtype=np.float64)
    return GsimContext(
        mag=rup["mag"],
        rake=rup.get("rake", 0.0),
        hypo_depth=rup.get("hypo_depth", 0.0),
        ztor=rup.get("ztor", 0.0),
        vs30=vs30,
        backarc=np.zeros_like(vs30, dtype=np.bool_) if np.isnan(backarc).any() else backarc > 0.0,
        **distances,
    )


def _predicted(gsim: Gsim, ctx: GsimContext, imt: Imt, result_type: str) -> np.ndarray:
    result = gsim.compute(ctx, imt)
    if result_type == MEAN:
        return np.exp(result.mean_ln)
    if result_type == TOTAL:
        return result.sigma
    if result_type == INTER:
        return result.tau
    if result_type == INTRA:
        return result.phi
    msg = f"unknown result type {result_type!r}"
    raise VerificationError(msg)
