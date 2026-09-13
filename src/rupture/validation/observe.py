"""``validate-observe``: committed observation fixtures parse, and as-of is half-open.

Offline: reads ``data/fixtures/gnss/ngl`` and ``data/fixtures/usgs_feed``. Does not fetch.
"""

from __future__ import annotations

import math
from pathlib import Path

from rupture.adapters.catalogs.fixtures import FixtureError, load_fixture_dir
from rupture.adapters.observations.ngl import NglGnssSource, parse_tenv3
from rupture.adapters.observations.usgs_feed import parse_usgs_feed_geojson
from rupture.domain import VintagePolicy
from rupture.domain.observation import GnssProduct, readable_as_of
from rupture.validation.result import GateResult, GateStatus


def run(repo_root: Path) -> GateResult:
    findings: list[str] = []
    failures: list[str] = []
    fixtures = repo_root / "data" / "fixtures"

    try:
        ngl_files = load_fixture_dir(fixtures / "gnss" / "ngl", adapter_version="gate")
    except FixtureError as exc:
        failures.append(f"gnss/ngl fixtures: {exc}")
        ngl_files = []
    if not ngl_files:
        failures.append("gnss/ngl: no listed fixture payloads")

    for fx in ngl_files:
        positions = parse_tenv3(fx.content, provenance=fx.provenance, product=GnssProduct.FINAL)
        findings.append(
            f"{fx.path.name}: {len(positions)} position(s), station "
            f"{positions[0].station_id if positions else '(none)'}"
        )
        if not positions:
            failures.append(f"{fx.path.name}: parsed zero positions")
            continue
        if any(p.station_id != "P595" for p in positions):
            failures.append(f"{fx.path.name}: expected station P595")
        if any(
            not (
                math.isfinite(p.east_m)
                and math.isfinite(p.north_m)
                and math.isfinite(p.up_m)
                and p.provenance.sha256 == fx.provenance.sha256
            )
            for p in positions
        ):
            failures.append(f"{fx.path.name}: non-finite coordinates or provenance mismatch")

        source = NglGnssSource("P595", positions=positions, product=GnssProduct.FINAL)
        last = positions[-1]
        kept = source.available_as_of(last.available_time, policy=VintagePolicy.EXCLUDE_UNKNOWN)
        if last in kept or any(p.available_time == last.available_time for p in kept):
            failures.append(
                "as-of half-open violated: a position with available_time == as_of was served"
            )
        if any(not readable_as_of(p.available_time, last.available_time) for p in kept):
            failures.append("as-of returned a position with available_time >= as_of")
        findings.append(
            f"as-of {last.available_time.isoformat()}: kept {len(kept)} of {len(positions)} "
            "(boundary excluded)"
        )

    try:
        usgs_files = load_fixture_dir(fixtures / "usgs_feed", adapter_version="gate")
    except FixtureError as exc:
        failures.append(f"usgs_feed fixtures: {exc}")
        usgs_files = []
    for fx in usgs_files:
        events = parse_usgs_feed_geojson(fx.content, provenance=fx.provenance)
        findings.append(f"{fx.path.name}: {len(events)} event(s)")
        if not events:
            failures.append(f"{fx.path.name}: parsed zero events")
        if any(e.provenance.sha256 != fx.provenance.sha256 for e in events):
            failures.append(f"{fx.path.name}: provenance sha256 mismatch")
        if not any(e.source_event_id == "ci38457511" for e in events):
            failures.append(f"{fx.path.name}: Ridgecrest M7.1 ci38457511 missing")

    if failures:
        return GateResult(
            name="validate-observe", status=GateStatus.FAILED, findings=findings + failures
        )
    return GateResult(name="validate-observe", status=GateStatus.PASSED, findings=findings)
