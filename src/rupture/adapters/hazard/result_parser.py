"""Parse OpenQuake hazard-curve CSV exports into :class:`HazardCurveSet`. Pure: no I/O.

Format (engine ``export_hcurves_csv``, verified against the QA expected files and the manual's
"Outputs → Classical PSHA" page)::

    #,,,,,"generated_by='OpenQuake engine 3.20.0', start_date='2024-06-03T09:36:04',
    checksum=2107362341, kind='mean', investigation_time=1.0, imt='PGA'"   (one line)
    lon,lat,depth,poe-0.1000000,poe-0.4000000,poe-0.6000000
    0.00000,0.00000,-0.10000,4.553861E-01,5.754043E-02,6.354517E-03

File names are ``hazard_curve-<kind>-<IMT>_<calc_id>.csv`` from ``oq export`` (the QA copies drop
``-<kind>`` and ``_<calc_id>``); the parser reads ``kind`` and ``imt`` from the header comment, not
from the file name.
"""

from __future__ import annotations

import configparser
import csv
import io
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from rupture.domain import HazardCurve, HazardCurveSet, Provenance

_META_ITEM = re.compile(r"(\w+)=(?:'([^']*)'|([^,]+))")
_ENGINE_VERSION = re.compile(r"OpenQuake engine\s+(\S+)")
_POE_COLUMN = "poe-"

HAZARD_CURVE_GLOB = "hazard_curve-*.csv"


class ResultParseError(ValueError):
    """The CSV is not an OpenQuake hazard-curve export we understand."""


@dataclass(frozen=True, slots=True)
class HazardCurveFile:
    """One parsed ``hazard_curve-*.csv``: header metadata plus a curve per site."""

    kind: str
    imt: str
    investigation_time: float
    engine_version: str | None
    start_date: str | None
    checksum: str | None
    curves: tuple[HazardCurve, ...]


def parse_header_metadata(line: str) -> dict[str, str]:
    """``key=value`` pairs from the leading ``#`` comment line."""
    if not line.startswith("#"):
        msg = "hazard-curve CSV must start with a '#' metadata line"
        raise ResultParseError(msg)
    body = line.strip().lstrip("#").strip().lstrip(",")
    if body.startswith('"') and body.endswith('"'):
        body = body[1:-1]
    meta: dict[str, str] = {}
    for key, quoted, bare in _META_ITEM.findall(body):
        meta[key] = quoted if quoted else bare.strip()
    return meta


def parse_hazard_curve_csv(text: str) -> HazardCurveFile:
    """Parse one hazard-curve CSV export."""
    lines = text.splitlines()
    if len(lines) < 2:
        msg = "hazard-curve CSV needs a metadata line, a header line and at least one site row"
        raise ResultParseError(msg)
    meta = parse_header_metadata(lines[0])
    for required in ("imt", "investigation_time", "kind"):
        if required not in meta:
            msg = f"metadata line lacks {required!r}: {lines[0][:120]}"
            raise ResultParseError(msg)
    try:
        investigation_time = float(meta["investigation_time"])
    except ValueError as exc:
        msg = f"investigation_time is not a number: {meta['investigation_time']!r}"
        raise ResultParseError(msg) from exc

    reader = csv.reader(io.StringIO("\n".join(lines[1:])))
    header = next(reader, None)
    if header is None:
        msg = "missing column header"
        raise ResultParseError(msg)
    columns = _Columns.from_header(header)
    curves = tuple(_read_rows(reader, columns, meta["imt"]))
    if not curves:
        msg = "hazard-curve CSV has no site rows"
        raise ResultParseError(msg)

    version = None
    generated_by = meta.get("generated_by")
    if generated_by:
        m = _ENGINE_VERSION.search(generated_by)
        version = m.group(1) if m else generated_by
    return HazardCurveFile(
        kind=meta["kind"],
        imt=meta["imt"],
        investigation_time=investigation_time,
        engine_version=version,
        start_date=meta.get("start_date"),
        checksum=meta.get("checksum"),
        curves=curves,
    )


@dataclass(frozen=True, slots=True)
class _Columns:
    names: tuple[str, ...]
    lon: int
    lat: int
    poe_indices: tuple[int, ...]
    imls: tuple[float, ...]

    @classmethod
    def from_header(cls, header: list[str]) -> _Columns:
        names = tuple(c.strip() for c in header)
        try:
            lon, lat = names.index("lon"), names.index("lat")
        except ValueError as exc:
            msg = f"header lacks lon/lat: {list(names)}"
            raise ResultParseError(msg) from exc
        poe_cols = [(i, c) for i, c in enumerate(names) if c.startswith(_POE_COLUMN)]
        if not poe_cols:
            msg = f"header has no poe-<IML> columns: {list(names)}"
            raise ResultParseError(msg)
        try:
            imls = tuple(float(c[len(_POE_COLUMN) :]) for _, c in poe_cols)
        except ValueError as exc:
            msg = f"non-numeric IML in header: {list(names)}"
            raise ResultParseError(msg) from exc
        return cls(names, lon, lat, tuple(i for i, _ in poe_cols), imls)


def _read_rows(reader: Iterator[list[str]], cols: _Columns, imt: str) -> Iterator[HazardCurve]:
    for row in reader:
        if not row or not "".join(row).strip():
            continue
        if len(row) != len(cols.names):
            msg = f"row has {len(row)} fields, header has {len(cols.names)}: {row[:4]}"
            raise ResultParseError(msg)
        try:
            yield HazardCurve(
                site_longitude=float(row[cols.lon]),
                site_latitude=float(row[cols.lat]),
                imt=imt,
                imls=cols.imls,
                poes=tuple(float(row[i]) for i in cols.poe_indices),
            )
        except ValueError as exc:
            msg = f"bad numeric value in row {row[:4]}: {exc}"
            raise ResultParseError(msg) from exc


def parse_job_ini(text: str) -> dict[str, str]:
    """Flatten a ``job.ini`` into ``key -> value`` the way the engine does (sections ignored)."""
    cp = configparser.ConfigParser(interpolation=None, strict=False)
    cp.optionxform = str  # type: ignore[assignment,method-assign]  # keep key case
    try:
        cp.read_string(text)
    except configparser.Error as exc:
        msg = f"job.ini does not parse: {exc}"
        raise ResultParseError(msg) from exc
    flat: dict[str, str] = {}
    for section in cp.sections():
        for key, value in cp.items(section):
            flat[key] = " ".join(value.split())
    return flat


def select_realisation(files: Mapping[str, HazardCurveFile], realisation: str | None) -> str:
    """Pick the curve kind to publish: the requested one, else ``mean``, else the only one."""
    kinds = sorted({f.kind for f in files.values()})
    if realisation is not None:
        if realisation not in kinds:
            msg = f"realisation {realisation!r} not among exported kinds {kinds}"
            raise ResultParseError(msg)
        return realisation
    if "mean" in kinds:
        return "mean"
    if len(kinds) == 1:
        return kinds[0]
    msg = f"several curve kinds exported and no 'mean': {kinds}; pass realisation="
    raise ResultParseError(msg)


def build_curve_set(
    files: Mapping[str, str],
    *,
    set_id: str,
    source_model_id: str,
    gsim_logic_tree_id: str | None,
    job_hash: str,
    computed_at: datetime,
    provenance: Provenance,
    engine_version_fallback: str,
    realisation: str | None = None,
    notes: str | None = None,
) -> HazardCurveSet:
    """Assemble one :class:`HazardCurveSet` from ``{file name: csv text}``.

    Every file of the chosen kind must agree on ``investigation_time``. ``engine_version`` is the
    version the CSV header reports (what actually produced the numbers), falling back to
    ``engine_version_fallback`` when the header carries none.
    """
    if not files:
        msg = "no hazard-curve CSV files to parse"
        raise ResultParseError(msg)
    parsed = {name: parse_hazard_curve_csv(text) for name, text in files.items()}
    kind = select_realisation(parsed, realisation)
    chosen = {n: f for n, f in parsed.items() if f.kind == kind}
    times = {f.investigation_time for f in chosen.values()}
    if len(times) != 1:
        msg = f"files of kind {kind!r} disagree on investigation_time: {sorted(times)}"
        raise ResultParseError(msg)
    versions = {f.engine_version for f in chosen.values() if f.engine_version}
    engine_version = sorted(versions)[0] if versions else engine_version_fallback
    curves: list[HazardCurve] = []
    for name in sorted(chosen):
        curves.extend(chosen[name].curves)
    start_dates = sorted({f.start_date for f in chosen.values() if f.start_date})
    extra = (
        f"engine start_date (header, engine-local clock): {start_dates[0]}" if start_dates else ""
    )
    all_notes = "; ".join(n for n in (notes, extra) if n) or None
    return HazardCurveSet(
        id=set_id,
        source_model_id=source_model_id,
        gsim_logic_tree_id=gsim_logic_tree_id,
        realisation=kind,
        investigation_time_years=times.pop(),
        curves=tuple(curves),
        engine="openquake.engine",
        engine_version=engine_version,
        job_hash=job_hash,
        computed_at=computed_at,
        provenance=provenance,
        notes=all_notes,
    )


def check_curve_set(
    curve_set: HazardCurveSet, *, expected_investigation_time: float | None = None
) -> list[str]:
    """Sanity findings for a curve set; empty means all checks passed.

    Checks: at least one site; PoE within [0, 1] (also enforced by the model); PoE non-increasing
    with increasing IML; IMLs strictly increasing; investigation time matches the job when given.
    """
    problems: list[str] = []
    if not curve_set.curves:
        problems.append("no hazard curves")
        return problems
    sites = {(c.site_longitude, c.site_latitude) for c in curve_set.curves}
    if not sites:
        problems.append("no sites")
    for idx, c in enumerate(curve_set.curves):
        where = f"curve {idx} ({c.imt} @ {c.site_longitude:.4f},{c.site_latitude:.4f})"
        if any(b <= a for a, b in pairwise(c.imls)):
            problems.append(f"{where}: IMLs not strictly increasing")
        if any(p < 0.0 or p > 1.0 for p in c.poes):
            problems.append(f"{where}: PoE outside [0, 1]")
        if any(b > a + 1e-12 for a, b in pairwise(c.poes)):
            problems.append(f"{where}: PoE increases with IML")
    if (
        expected_investigation_time is not None
        and abs(curve_set.investigation_time_years - expected_investigation_time) > 1e-9
    ):
        problems.append(
            f"investigation_time {curve_set.investigation_time_years} != job "
            f"{expected_investigation_time}"
        )
    return problems
