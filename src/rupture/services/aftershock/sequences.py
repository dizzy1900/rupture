"""Mainshocks, the committed sequence catalogues, and the two validation sequences.

A :class:`Mainshock` is either read out of a catalogue by its ComCat event id or supplied
explicitly (time, latitude, longitude, depth, magnitude). Nothing here fetches: catalogues come
from a built catalogue directory or, offline, from the committed ComCat slices under
``tests/fixtures/aftershock/`` whose provenance and digests are checked on load.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rupture.adapters.catalogs.comcat import ADAPTER_VERSION, parse_comcat_geojson
from rupture.domain import (
    Catalog,
    Event,
    FitResult,
    MagnitudePolicy,
    Provenance,
    Region,
    sha256_hex,
)
from rupture.pipelines.io import load_region as load_region_file
from rupture.pipelines.magnitudes import SourcedMagnitude, preferred_mw

FIXTURE_REL = Path("tests") / "fixtures" / "aftershock"
REGIONS_REL = Path("data") / "regions"
PROVENANCE_FILE = "provenance.json"
COMCAT_SOURCE = "usgs-comcat"


class FixtureError(RuntimeError):
    """A committed sequence fixture is missing or does not match its recorded digest."""


@dataclass(frozen=True, slots=True)
class Mainshock:
    """The event a sequence is defined around."""

    event_id: str
    origin_time: datetime
    latitude: float
    longitude: float
    magnitude: float
    depth_km: float | None = None

    def __post_init__(self) -> None:
        if self.origin_time.tzinfo is None:
            msg = "mainshock origin_time must be timezone-aware (UTC)"
            raise ValueError(msg)
        if not (-90.0 <= self.latitude <= 90.0 and -180.0 <= self.longitude <= 180.0):
            msg = "mainshock epicentre out of range"
            raise ValueError(msg)
        if not (0.0 <= self.magnitude <= 10.0):
            msg = "mainshock magnitude out of range"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class SequenceSpec:
    """One named validation sequence: its mainshock, its parent region and its catalogue slice."""

    id: str
    mainshock: Mainshock
    parent_region_id: str
    fixture_file: str
    description: str


# The two pseudo-prospective validation sequences. Mainshock parameters are the ComCat preferred
# solutions in the committed slices (checked by ``check_against_catalog`` below), not typed in
# from memory.
GORKHA = SequenceSpec(
    id="gorkha",
    mainshock=Mainshock(
        event_id="us20002926",
        origin_time=datetime(2015, 4, 25, 6, 11, 25, 950000, tzinfo=UTC),
        latitude=28.2305,
        longitude=84.7314,
        magnitude=7.8,
        depth_km=8.22,
    ),
    parent_region_id="nepal-himalaya",
    fixture_file="comcat-nepal-2005-2015-m3.8.geojson",
    description="2015 Gorkha, Nepal (M7.8); M7.3 aftershock us20002ejl on 2015-05-12",
)

KAHRAMANMARAS = SequenceSpec(
    id="kahramanmaras",
    mainshock=Mainshock(
        event_id="us6000jllz",
        origin_time=datetime(2023, 2, 6, 1, 17, 34, 342000, tzinfo=UTC),
        latitude=37.2256,
        longitude=37.0143,
        magnitude=7.8,
        depth_km=10.0,
    ),
    parent_region_id="turkiye-eaf",
    fixture_file="comcat-turkiye-2013-2023-m3.8.geojson",
    description="2023 Kahramanmaras, Turkiye (M7.8); M7.5 doublet us6000jlqa about 9 h later",
)

SEQUENCES: dict[str, SequenceSpec] = {s.id: s for s in (GORKHA, KAHRAMANMARAS)}


def sequence_spec(name: str) -> SequenceSpec:
    if name not in SEQUENCES:
        msg = f"unknown sequence {name!r}; known: {', '.join(sorted(SEQUENCES))}"
        raise KeyError(msg)
    return SEQUENCES[name]


# ---------------------------------------------------------------------- fixtures
def fixture_dir(repo_root: Path) -> Path:
    return Path(repo_root) / FIXTURE_REL


def load_sequence_catalog(spec: SequenceSpec, repo_root: Path) -> Catalog:
    """Read the committed ComCat slice for ``spec`` and homogenise its magnitudes to Mw.

    The digest recorded in ``provenance.json`` is verified before the payload is parsed, so a
    hand-edited fixture fails loudly rather than quietly changing a published number.
    """
    directory = fixture_dir(repo_root)
    prov_path = directory / PROVENANCE_FILE
    if not prov_path.exists():
        msg = f"no {PROVENANCE_FILE} in {directory}"
        raise FixtureError(msg)
    meta = json.loads(prov_path.read_text(encoding="utf-8"))
    info = meta.get("files", {}).get(spec.fixture_file)
    if info is None:
        msg = f"{spec.fixture_file} is not recorded in {prov_path}"
        raise FixtureError(msg)
    path = directory / spec.fixture_file
    if not path.exists():
        msg = f"fixture {path} is missing; regenerate with tests.fixtures.aftershock.make_fixtures"
        raise FixtureError(msg)
    payload = path.read_bytes()
    digest = sha256_hex(payload)
    if digest != info["sha256"]:
        msg = f"fixture {path} sha256 {digest} != recorded {info['sha256']} (edited by hand?)"
        raise FixtureError(msg)
    provenance = Provenance(
        source=meta["source"],
        source_url=info["source_url"],
        retrieved_at=info["retrieved_at"],
        sha256=digest,
        licence=meta["licence"],
        adapter_version=ADAPTER_VERSION,
        notes=info.get("notes"),
    )
    events = homogenise(parse_comcat_geojson(payload, provenance=provenance))
    return Catalog(
        id=f"aftershock-fixture-{spec.id}",
        region_id=spec.parent_region_id,
        events=tuple(events),
        sources=(COMCAT_SOURCE,),
        built_at=provenance.retrieved_at,
        builder_version="rupture.services.aftershock.sequences",
        notes=(
            f"{info['n_events']} ComCat features, query floor M{info['query']['minmagnitude']}; "
            "Mw by rupture.pipelines.magnitudes.preferred_mw under the STRICT policy"
        ),
    )


def homogenise(
    events: list[Event], *, policy: MagnitudePolicy = MagnitudePolicy.STRICT
) -> list[Event]:
    """Fill ``mw``/``mw_conversion`` from the single reported magnitude of each ComCat entry.

    ComCat's summary feed gives one preferred magnitude per event, so this is the one-source case
    of the merge-time homogenisation in :mod:`rupture.pipelines.magnitudes`: moment magnitudes pass
    through, ``mb`` and ``Ms`` convert with Scordilis (2006) inside its validity ranges, and every
    other scale leaves ``mw = None``. The events stay in the catalogue either way; the magnitude
    filters exclude them.
    """
    out: list[Event] = []
    for event in events:
        result = preferred_mw(
            [SourcedMagnitude(source=COMCAT_SOURCE, record=event.magnitude)],
            policy=policy,
            preferred=event.magnitude,
        )
        out.append(event.model_copy(update={"mw": result.mw, "mw_conversion": result.conversion}))
    return out


def fixture_coverage_end(spec: SequenceSpec, repo_root: Path) -> datetime:
    """The ``endtime`` of the ComCat query behind the slice: after this the catalogue is silent.

    A forecast window that ends later is not closed by the data and must not be scored; the
    validation skips it with a printed reason instead of counting a truncated tail as zero.
    """
    meta = json.loads((fixture_dir(repo_root) / PROVENANCE_FILE).read_text(encoding="utf-8"))
    info = meta["files"][spec.fixture_file]
    text = str(info["query"]["endtime"])
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def load_parent_region(spec: SequenceSpec, repo_root: Path) -> Region:
    """The published region whose Mc, thresholds and depth range the sequence inherits."""
    return load_region_file(Path(repo_root) / REGIONS_REL / spec.parent_region_id)


FITS_SUBDIR = "fits"


def fits_dir(spec: SequenceSpec, repo_root: Path) -> Path:
    return fixture_dir(repo_root) / FITS_SUBDIR / spec.id


def load_committed_fits(spec: SequenceSpec, repo_root: Path) -> dict[str, FitResult]:
    """Persisted ETAS fits for ``spec``, keyed by ISO fit cutoff.

    These are real fits of the committed slice, regenerated by
    ``tests.fixtures.aftershock.make_fits``; they exist so the offline gate can score forecasts
    without spending four minutes re-running the EM. An empty mapping means "no committed fits",
    and the caller refits.
    """
    directory = fits_dir(spec, repo_root)
    if not directory.is_dir():
        return {}
    out: dict[str, FitResult] = {}
    for path in sorted(directory.glob("*/fit_result.json")):
        fit = FitResult.model_validate_json(path.read_text(encoding="utf-8"))
        out[fit.fit_cutoff.isoformat()] = fit
    return out


def mainshock_from_catalog(catalog: Catalog, event_id: str) -> Mainshock:
    """Look a mainshock up in a catalogue by ComCat id (with or without the ``usgs-comcat:``)."""
    wanted = {event_id, f"{COMCAT_SOURCE}:{event_id}"}
    hit = next((e for e in catalog.events if e.id in wanted or e.source_event_id == event_id), None)
    if hit is None:
        msg = f"event {event_id!r} is not in catalogue {catalog.id!r}"
        raise KeyError(msg)
    if hit.mw is None:
        msg = (
            f"event {event_id!r} has no homogenised Mw ({hit.magnitude.type.value} "
            f"{hit.magnitude.value}); a mainshock magnitude cannot be assumed"
        )
        raise ValueError(msg)
    return Mainshock(
        event_id=hit.source_event_id,
        origin_time=hit.origin_time,
        latitude=hit.latitude,
        longitude=hit.longitude,
        magnitude=hit.mw,
        depth_km=hit.depth_km,
    )


def check_against_catalog(spec: SequenceSpec, catalog: Catalog) -> list[str]:
    """Differences between the declared mainshock and the one in the catalogue (empty = agrees)."""
    found = mainshock_from_catalog(catalog, spec.mainshock.event_id)
    declared = spec.mainshock
    problems: list[str] = []
    if abs((found.origin_time - declared.origin_time).total_seconds()) > 1.0:
        problems.append(
            f"{spec.id}: origin_time {found.origin_time.isoformat()} != declared "
            f"{declared.origin_time.isoformat()}"
        )
    if abs(found.magnitude - declared.magnitude) > 0.05:
        problems.append(f"{spec.id}: magnitude {found.magnitude} != declared {declared.magnitude}")
    if (
        abs(found.latitude - declared.latitude) > 0.05
        or abs(found.longitude - declared.longitude) > 0.05
    ):
        problems.append(
            f"{spec.id}: epicentre ({found.latitude}, {found.longitude}) != declared "
            f"({declared.latitude}, {declared.longitude})"
        )
    return problems


ISSUE_OFFSETS: tuple[tuple[str, timedelta], ...] = (
    ("1h", timedelta(hours=1)),
    ("1d", timedelta(days=1)),
    ("7d", timedelta(days=7)),
)
"""The three elapsed times at which the validation issues a forecast."""
