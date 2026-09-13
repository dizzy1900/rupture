"""Nevada Geodetic Laboratory daily GNSS positions as an ``ObservationSource``.

This is the data port that a later Bletery & Nocquet-style adjudication would read. It does
**not** reconstruct that paper's test, it does not invert strain, and a GNSS position is not
a prediction of an earthquake.

NGL publishes daily tenv3 series without an API key. The IGS14 daily files are the *final*
product: IGS final orbits lag the observation day by about two weeks, so a replay at issue
time must not treat today's file as if it had been readable on the valid day. Rapid products
are documented at about 24 h. Those lags are named constants below, not literals in the
arithmetic, and they are **documented by the provider / IGS, not measured in this
repository** (ARCHITECTURE.md § 3.2).

What this adapter cannot do: NGL serves the current series. It does not serve archived
vintages of that series. Applying a lag to ``valid_time`` withholds values that would not yet
have been published; it cannot recover a position that was later revised. Reconstructed
availability is labelled by using these constants rather than a publish stamp in the payload
(tenv3 has none).

Cite Blewitt, Hammond & Kreemer (2018), *Eos*, 99, https://doi.org/10.1029/2018EO104623 as
NGL requests on its homepage. No SPDX identifier is published; the licence field records that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from rupture.adapters.catalogs._http import FetchError, fetch_bytes
from rupture.adapters.catalogs.fixtures import load_fixture_dir
from rupture.domain import Provenance, VintagePolicy, VintageSummary
from rupture.domain.observation import (
    GnssPosition,
    GnssProduct,
    LatencyModel,
    ObservableKind,
    ProductVintage,
    readable_as_of,
)

SOURCE_ID = "ngl-gnss"
ADAPTER_VERSION = "0.1.0"
# Recorded from https://geodesy.unr.edu/ on 2026-09-13: citation required, no SPDX.
LICENCE = (
    "no SPDX; NGL homepage requires citation of Blewitt, Hammond & Kreemer (2018), Eos, 99, "
    "https://doi.org/10.1029/2018EO104623"
)
CITATION = (
    "Blewitt, G., W. C. Hammond, and C. Kreemer (2018), Harnessing the GPS data explosion "
    "for interdisciplinary science, Eos, 99, https://doi.org/10.1029/2018EO104623"
)

# Documented IGS final-orbit latency applied to NGL IGS14/IGS20 daily tenv3. Not measured here.
FINAL_ORBIT_LAG = timedelta(days=14)
# Documented NGL rapid-product latency (~24 h on the NGL station lists). Not measured here.
RAPID_ORBIT_LAG = timedelta(days=1)

MJD_EPOCH = datetime(1858, 11, 17, tzinfo=UTC)
_MONTHS = {
    name: index
    for index, name in enumerate(
        ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"),
        start=1,
    )
}

# Classic URL from NGL documentation and the literature. On 2026-09-13 this path 404'd; the
# current layout is CURRENT_IGS14_TENV3_TEMPLATE. HTTP port 80 timed out; HTTPS served.
DOCUMENTED_TENV3_TEMPLATE = "https://geodesy.unr.edu/gps_timeseries/tenv3/IGS14/{site}.tenv3"
CURRENT_IGS14_TENV3_TEMPLATE = (
    "https://geodesy.unr.edu/gps_timeseries/IGS14/tenv3/IGS14/{site}.tenv3"
)
HOLDINGS_URL = "https://geodesy.unr.edu/NGLStationPages/DataHoldings.txt"

NGL_LATENCY = LatencyModel(
    source_id=SOURCE_ID,
    products=(
        ProductVintage(
            product_id=GnssProduct.RAPID.value,
            nominal_lag=RAPID_ORBIT_LAG,
            evidence=(
                "documented:https://geodesy.unr.edu/ — NGL station lists describe rapid "
                "5-minute solutions as latency 24 hours; not measured in this repository"
            ),
        ),
        ProductVintage(
            product_id=GnssProduct.FINAL.value,
            nominal_lag=FINAL_ORBIT_LAG,
            evidence=(
                "documented: IGS final-orbit lag of ~14 days applied to NGL IGS14 daily "
                "tenv3 (ADR-0054, ARCHITECTURE.md § 3.2); not measured in this repository"
            ),
        ),
    ),
    default_product_id=GnssProduct.FINAL.value,
)


def lag_for_product(product: GnssProduct) -> timedelta:
    """Nominal valid_time -> available_time lag for an NGL product tier."""
    if product is GnssProduct.FINAL:
        return FINAL_ORBIT_LAG
    if product is GnssProduct.RAPID:
        return RAPID_ORBIT_LAG
    msg = f"unknown GNSS product {product!r}"
    raise ValueError(msg)


def stamp_available_time(
    valid_time: datetime,
    product: GnssProduct,
    *,
    publish_stamp: datetime | None,
) -> datetime:
    """Publish stamp from the payload if present; otherwise valid_time plus the product lag."""
    if publish_stamp is not None:
        return publish_stamp
    return valid_time + lag_for_product(product)


def tenv3_urls(station_id: str) -> tuple[str, ...]:
    """URLs to try for an IGS14 daily tenv3 file, documented path first."""
    site = station_id.strip().upper()
    return (
        DOCUMENTED_TENV3_TEMPLATE.format(site=site),
        CURRENT_IGS14_TENV3_TEMPLATE.format(site=site),
    )


def _parse_yymmdd(token: str) -> datetime:
    if len(token) != 7:
        msg = f"tenv3 date token {token!r} is not YYMMMDD"
        raise ValueError(msg)
    month = _MONTHS.get(token[2:5].upper())
    if month is None:
        msg = f"tenv3 date token {token!r} has an unknown month"
        raise ValueError(msg)
    year_yy = int(token[:2])
    year = 2000 + year_yy if year_yy < 80 else 1900 + year_yy
    day = int(token[5:7])
    return datetime(year, month, day, tzinfo=UTC)


def _mjd_to_utc(mjd: int) -> datetime:
    return MJD_EPOCH + timedelta(days=mjd)


def _require_header(line: str) -> list[str]:
    cols = line.split()
    needed = ("site", "YYMMMDD", "__MJD", "_e0(m)", "__east(m)", "sig_e(m)")
    missing = [name for name in needed if name not in cols]
    if missing:
        msg = f"tenv3 header missing columns {missing}: {line[:160]}"
        raise ValueError(msg)
    return cols


def parse_tenv3(
    payload: bytes | str,
    *,
    provenance: Provenance,
    product: GnssProduct = GnssProduct.FINAL,
) -> tuple[GnssPosition, ...]:
    """Pure parser: NGL tenv3 bytes -> positions. Never invents a row.

    ``available_time`` is ``valid_time +`` :data:`FINAL_ORBIT_LAG` or
    :data:`RAPID_ORBIT_LAG` according to ``product``. tenv3 carries no publish stamp.
    """
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    lines = text.splitlines()
    if not lines:
        msg = "tenv3 payload is empty"
        raise ValueError(msg)
    header = _require_header(lines[0])
    index = {name: i for i, name in enumerate(header)}
    positions: list[GnssPosition] = []
    for raw in lines[1:]:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cols = line.split()
        if len(cols) < len(header):
            msg = f"tenv3 row has {len(cols)} columns, expected {len(header)}: {line[:120]}"
            raise ValueError(msg)
        station_id = cols[index["site"]]
        valid_from_mjd = _mjd_to_utc(int(float(cols[index["__MJD"]])))
        valid_from_date = _parse_yymmdd(cols[index["YYMMMDD"]])
        if valid_from_mjd.date() != valid_from_date.date():
            msg = (
                f"tenv3 date/MJD disagree for {station_id}: "
                f"{cols[index['YYMMMDD']]} vs MJD {cols[index['__MJD']]}"
            )
            raise ValueError(msg)
        east_m = float(cols[index["_e0(m)"]]) + float(cols[index["__east(m)"]])
        north_m = float(cols[index["____n0(m)"]]) + float(cols[index["_north(m)"]])
        up_m = float(cols[index["u0(m)"]]) + float(cols[index["____up(m)"]])
        positions.append(
            GnssPosition(
                station_id=station_id,
                valid_time=valid_from_mjd,
                available_time=stamp_available_time(valid_from_mjd, product, publish_stamp=None),
                east_m=east_m,
                north_m=north_m,
                up_m=up_m,
                sigma_e=float(cols[index["sig_e(m)"]]),
                sigma_n=float(cols[index["sig_n(m)"]]),
                sigma_u=float(cols[index["sig_u(m)"]]),
                product=product,
                provenance=provenance,
            )
        )
    return tuple(positions)


def parse_data_holdings(payload: bytes | str) -> dict[str, str]:
    """Index NGL DataHoldings.txt by station id -> raw line (no invented fields)."""
    text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("Sta"):
            continue
        station_id = line.split()[0]
        out[station_id] = line
    return out


class NglGnssSource:
    """Loaded (or fetchable) NGL tenv3 series with ``available_as_of``.

    Implements the ``available_as_of(instant, policy)`` method of
    :class:`~rupture.ports.observation_source.ObservationSource` for GNSS positions.
    The port's return type is still catalogue-shaped; this adapter returns
    ``tuple[GnssPosition, ...]`` because a position is not an :class:`~rupture.domain.Event`.
    """

    source_id = SOURCE_ID
    adapter_version = ADAPTER_VERSION
    kind = ObservableKind.GNSS_POSITION

    def __init__(
        self,
        station_id: str,
        *,
        product: GnssProduct = GnssProduct.FINAL,
        offline_fixtures: Path | None = None,
        positions: tuple[GnssPosition, ...] | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.station_id = station_id.strip().upper()
        self.product = product
        self.offline_fixtures = offline_fixtures
        self.cache_dir = cache_dir
        self._positions = positions

    def latency_model(self) -> LatencyModel:
        return NGL_LATENCY

    def series(self) -> tuple[GnssPosition, ...]:
        """The loaded (or fetched) positions. Fetch or fail; never synthesise."""
        return self._load()

    def _load(self) -> tuple[GnssPosition, ...]:
        if self._positions is not None:
            return self._positions
        if self.offline_fixtures is not None:
            self._positions = self._from_fixtures()
            return self._positions
        self._positions = self._fetch_series()
        return self._positions

    def _from_fixtures(self) -> tuple[GnssPosition, ...]:
        assert self.offline_fixtures is not None
        directory = self.offline_fixtures / "gnss" / "ngl"
        files = load_fixture_dir(directory, adapter_version=ADAPTER_VERSION)
        matching = [
            f
            for f in files
            if f.path.name.upper().startswith(self.station_id)
            or self.station_id in f.path.name.upper()
        ]
        if not matching:
            names = ", ".join(f.path.name for f in files) or "(none)"
            msg = f"no NGL fixture for station {self.station_id}; have {names}"
            raise FileNotFoundError(msg)
        payload = matching[0]
        positions = parse_tenv3(payload.content, provenance=payload.provenance, product=self.product)
        unexpected = [p.station_id for p in positions if p.station_id != self.station_id]
        if unexpected:
            msg = f"NGL fixture station {unexpected[0]} != requested {self.station_id}"
            raise ValueError(msg)
        return positions

    def _fetch_series(self) -> tuple[GnssPosition, ...]:
        last_error: str | None = None
        for url in tenv3_urls(self.station_id):
            payload = fetch_bytes(url, cache_dir=self.cache_dir, ok_statuses=frozenset({200, 404}))
            if payload.status_code == 404:
                last_error = f"GET {url} -> HTTP 404"
                continue
            if payload.status_code != 200:
                msg = f"NGL tenv3 returned HTTP {payload.status_code} for {url}"
                raise FetchError(msg)
            if not payload.content.strip():
                msg = f"NGL tenv3 was empty at {url}"
                raise FetchError(msg)
            prov = Provenance(
                source=SOURCE_ID,
                source_url=payload.url,
                retrieved_at=payload.retrieved_at,
                sha256=payload.sha256,
                licence=LICENCE,
                adapter_version=ADAPTER_VERSION,
                notes=CITATION,
            )
            return parse_tenv3(payload.content, provenance=prov, product=self.product)
        msg = (
            f"NGL tenv3 for {self.station_id} not found; last error: {last_error}. "
            "Adapters fetch or fail; no positions were synthesised."
        )
        raise FetchError(msg)

    def available_as_of(
        self, instant: datetime, *, policy: VintagePolicy
    ) -> tuple[GnssPosition, ...]:
        """Positions this source can prove it held at ``instant`` (half-open).

        Every row carries ``available_time``, so ``policy`` cannot admit an unknown vintage.
        It is still required so the call site names the assumption.
        """
        if policy not in (VintagePolicy.EXCLUDE_UNKNOWN, VintagePolicy.INCLUDE_UNKNOWN):
            msg = f"unknown vintage policy {policy!r}"
            raise ValueError(msg)
        return tuple(p for p in self._load() if readable_as_of(p.available_time, instant))

    def vintage(self, reference_time: datetime | None = None) -> VintageSummary:
        """Coverage of the loaded series. ``n_events`` counts positions (existing type)."""
        positions = self._load()
        lags = sorted(
            (p.available_time - p.valid_time).total_seconds() / 86400.0 for p in positions
        )
        available = (
            None
            if reference_time is None
            else sum(1 for p in positions if readable_as_of(p.available_time, reference_time))
        )
        revised = (
            None
            if reference_time is None
            else sum(1 for p in positions if not readable_as_of(p.available_time, reference_time))
        )
        return VintageSummary(
            n_events=len(positions),
            n_with_available_time=len(positions),
            n_available_by=available,
            n_revised_after=revised,
            reference_time=reference_time,
            lag_days_median=_quantile(lags, 0.5),
            lag_days_p90=_quantile(lags, 0.9),
            lag_days_max=lags[-1] if lags else None,
        )


def _quantile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    idx = min(len(sorted_values) - 1, max(0, round(q * (len(sorted_values) - 1))))
    return sorted_values[idx]
