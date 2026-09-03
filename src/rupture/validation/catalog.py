"""Catalogue gate (``make validate-catalog``): builds the three regions offline from fixtures.

Checks, per region build:

1. every fixture directory has a ``provenance.json`` and every listed file matches its sha256
   (unlisted files are a finding);
2. every event carries provenance with a non-null ``sha256`` equal to the digest of a committed
   fixture payload;
3. Mc estimates are present for both required methods (maximum curvature, b-value stability);
4. no duplicates survive the merge: no two events share a contributing id, and no two events
   with disjoint lane sets lie within the association windows of each other (pairs sharing a
   lane are distinct events one bulletin reports separately, so the lane rule kept them apart);
5. ``us7000tbwb`` is present in the Nepal build and tagged ``landslide``;
6. every ``Event`` and the ``Catalog`` validate against ``contracts/event.v0.json`` and
   ``contracts/catalog.v0.json``;
7. the GeoParquet writer round-trips the catalogue exactly.

Offline by construction: sources are instantiated in fixture mode and never touch the network.
"""

from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import jsonschema

from rupture.adapters.catalogs.fixtures import PROVENANCE_FILE, FixtureError, load_fixture_dir
from rupture.adapters.sources.regions import default_regions_root, load_region
from rupture.adapters.storage.geoparquet import read_catalog, write_catalog
from rupture.domain import Catalog, EventType, McMethod, contracts
from rupture.pipelines.build_catalog import (
    MergeConfig,
    association_keys,
    build_catalog,
    contributing_lanes,
    haversine_km,
)
from rupture.validation.result import GateResult, GateStatus

FIXTURE_SOURCES: tuple[str, ...] = ("comcat", "isc", "gcmt")
LANDSLIDE_ID = "us7000tbwb"

# region -> [start, end) covered by the committed fixtures
WINDOWS: dict[str, tuple[datetime, datetime]] = {
    "nepal-himalaya": (datetime(2015, 4, 25, tzinfo=UTC), datetime(2026, 9, 1, tzinfo=UTC)),
    "turkiye-eaf": (datetime(2023, 2, 6, tzinfo=UTC), datetime(2023, 3, 8, tzinfo=UTC)),
    "california": (datetime(2019, 7, 4, tzinfo=UTC), datetime(2019, 8, 3, tzinfo=UTC)),
}


def _check_fixture_dirs(fixtures_root: Path) -> tuple[set[str], list[str]]:
    """Return the sha256 digests of every committed payload plus any findings."""
    digests: set[str] = set()
    findings: list[str] = []
    for name in FIXTURE_SOURCES:
        directory = fixtures_root / name
        try:
            files = load_fixture_dir(directory, adapter_version="gate")
        except FixtureError as exc:
            findings.append(f"fixtures/{name}: {exc}")
            continue
        listed = {f.path.name for f in files}
        for f in files:
            digests.add(f.provenance.sha256 or "")
        for p in sorted(directory.iterdir()):
            if p.is_file() and p.name != PROVENANCE_FILE and p.name not in listed:
                findings.append(f"fixtures/{name}/{p.name}: not listed in {PROVENANCE_FILE}")
    return digests, findings


def _check_duplicates(catalog: Catalog, cfg: MergeConfig) -> list[str]:
    findings: list[str] = []
    seen: dict[str, str] = {}
    for e in catalog.events:
        for cid in e.contributing_ids:
            if cid in seen:
                findings.append(f"{catalog.region_id}: {cid} contributes to {seen[cid]} and {e.id}")
            seen[cid] = e.id
    events = sorted(catalog.events, key=lambda e: e.origin_time)
    for i, a in enumerate(events):
        ka = association_keys(a)
        for b in events[i + 1 :]:
            if (b.origin_time - a.origin_time).total_seconds() > cfg.time_window_s + 60:
                break
            if contributing_lanes(a) & contributing_lanes(b):
                # they share a lane, so the merge was (correctly) blocked: two distinct events
                # that one bulletin reports separately, e.g. dense aftershocks
                continue
            for ta, la, lo_a in ka:
                for tb, lb, lo_b in association_keys(b):
                    if abs((ta - tb).total_seconds()) > cfg.time_window_s:
                        continue
                    if haversine_km(la, lo_a, lb, lo_b) <= cfg.distance_km:
                        findings.append(
                            f"{catalog.region_id}: {a.id} ({a.source_catalog}) and {b.id} "
                            f"({b.source_catalog}) lie within the merge windows"
                        )
    return findings


def _check_schemas(catalog: Catalog) -> list[str]:
    findings: list[str] = []
    event_schema = contracts.schema_for("event.v0.json")
    catalog_schema = contracts.schema_for("catalog.v0.json")
    validator = jsonschema.Draft202012Validator(event_schema)
    for e in catalog.events:
        errors = list(validator.iter_errors(e.model_dump(mode="json")))
        if errors:
            findings.append(
                f"{catalog.region_id}: event {e.id} fails event.v0.json: {errors[0].message}"
            )
            break
    cat_errors = list(
        jsonschema.Draft202012Validator(catalog_schema).iter_errors(catalog.model_dump(mode="json"))
    )
    if cat_errors:
        findings.append(
            f"{catalog.region_id}: catalog fails catalog.v0.json: {cat_errors[0].message}"
        )
    return findings


def run(repo_root: Path) -> GateResult:
    fixtures_root = repo_root / "data" / "fixtures"
    regions_root = default_regions_root(repo_root)
    findings: list[str] = []
    failures: list[str] = []

    digests, fixture_findings = _check_fixture_dirs(fixtures_root)
    failures.extend(fixture_findings)
    findings.append(f"{len(digests)} fixture payloads verified against provenance.json")

    cfg = MergeConfig()
    for region_id, (start, end) in WINDOWS.items():
        try:
            region = load_region(regions_root, region_id)
        except (FileNotFoundError, ValueError) as exc:
            failures.append(str(exc))
            continue
        catalog = build_catalog(
            region,
            start,
            end,
            list(FIXTURE_SOURCES),
            offline_fixtures=fixtures_root,
            min_magnitude=None,
            merge=cfg,
            etas_cross_check=False,
        )
        counts = catalog.count_by_type()
        findings.append(
            f"{region_id}: {len(catalog)} events from {', '.join(catalog.sources)}; "
            f"{counts[EventType.EARTHQUAKE]} earthquakes, "
            f"{counts[EventType.LANDSLIDE]} landslide-type"
        )
        # 2. provenance
        bad = [
            e.id
            for e in catalog.events
            if not e.provenance.sha256 or e.provenance.sha256 not in digests
        ]
        if bad:
            failures.append(
                f"{region_id}: {len(bad)} events without a fixture sha256 (e.g. {bad[0]})"
            )
        # 3. completeness
        for method in (McMethod.MAXIMUM_CURVATURE, McMethod.B_VALUE_STABILITY):
            est = catalog.preferred_mc(method)
            if est is None:
                failures.append(f"{region_id}: no {method.value} Mc estimate")
            else:
                b = f", b={est.b_value:.2f}" if est.b_value else ""
                findings.append(
                    f"{region_id}: Mc[{method.value}]={est.mc:.2f} (n={est.n_events}{b})"
                )
        # 4. duplicates
        failures.extend(_check_duplicates(catalog, cfg))
        # 5. landslide retention
        if region_id == "nepal-himalaya":
            hits = [e for e in catalog.events if LANDSLIDE_ID in e.source_event_id]
            if not hits:
                failures.append(f"{region_id}: {LANDSLIDE_ID} missing from the built catalogue")
            elif hits[0].event_type != EventType.LANDSLIDE:
                failures.append(f"{region_id}: {LANDSLIDE_ID} tagged {hits[0].event_type.value}")
            else:
                findings.append(f"{region_id}: {LANDSLIDE_ID} present, tagged landslide, mw=None")
        # 6. schemas
        failures.extend(_check_schemas(catalog))
        # 7. round trip
        with tempfile.TemporaryDirectory(prefix="rupture-catalog-gate-") as tmp:
            write_catalog(catalog, Path(tmp))
            back = read_catalog(Path(tmp))
            if back != catalog:
                failures.append(f"{region_id}: GeoParquet round trip is not equal")
            meta = json.loads((Path(tmp) / "catalog.meta.json").read_text(encoding="utf-8"))
            if meta.get("event_hash") != catalog.event_hash():
                failures.append(f"{region_id}: catalog.meta.json event_hash mismatch")

    status = GateStatus.PASSED if not failures else GateStatus.FAILED
    return GateResult(name="validate-catalog", status=status, findings=[*failures, *findings])
