"""Cascade gate (``make validate-cascade``). Offline, on committed fixtures.

What it checks, and what each check is worth:

1. **Coefficient provenance.** Every coefficient in :mod:`rupture.cascade.coefficients` is
   re-parsed out of the committed USGS reference-implementation files and compared. A number
   that has drifted from its published source fails the gate.
2. **Fixture integrity.** Every file listed in a cascade ``provenance.json`` exists and matches
   its recorded sha256.
3. **Gorkha reproduction.** The two published USGS ground-failure rasters are reproduced from
   the published ShakeMap and compared. The gate asserts the *link* comparison is exact (that is
   the part rupture can genuinely check) and asserts the recovered static term is admissible
   under the published coefficients where a bound exists. The *unconditioned* comparison is
   reported, never asserted: it is poor, and the gate says the number rather than hiding it.
4. **Discriminator.** ``us7000tbwb`` (ComCat ``type=landslide``, M5.2, Nepal) is tagged
   ``landslide``, is excluded by :meth:`~rupture.domain.catalog.Catalog.earthquakes`, and is
   counted by the discriminator accounting as excluded from tectonic fitting.
5. **Contract.** A :class:`~rupture.domain.cascade.CascadeExposure` built from the serac fallback
   validates against ``contracts/cascade-exposure.v0.json``, and a
   :class:`~rupture.domain.cascade.GroundFailureField` against
   ``contracts/ground-failure-field.v0.json``.
6. **Probabilities.** Every emitted probability is finite and in ``[0, 1]``.
7. **Label.** Every emitted record still carries the susceptibility caveat.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import numpy as np

from rupture.adapters.cascade import gorkha
from rupture.adapters.cascade.reproduction import Comparison
from rupture.adapters.cascade.serac import (
    DEFAULT_PGA_THRESHOLD_G,
    SeracSlopeUnitSource,
    _representative_point,
)
from rupture.adapters.catalogs.comcat import parse_comcat_geojson
from rupture.cascade import coefficients as coef
from rupture.cascade import discriminator
from rupture.domain import contracts
from rupture.domain.catalog import Bounds, Catalog
from rupture.domain.common import Provenance
from rupture.domain.event import EventType
from rupture.validation.result import GateResult, GateStatus

GATE_NAME = "validate-cascade"

FIXTURE_ROOT = Path("tests") / "fixtures" / "cascade"
COMCAT_LANDSLIDE_FIXTURE = (
    Path("data") / "fixtures" / "comcat" / "nepal-2026-landslide-us7000tbwb.geojson"
)
LANDSLIDE_EVENT_ID = "us7000tbwb"
EXPOSURE_AOI = "lhende-khola-trishuli"

LINK_TOLERANCE = 1e-9
"""The link round trip is arithmetic on the product's own numbers; it must be exact."""

ADMISSIBILITY_FLOOR = 0.95
"""Fraction of well-conditioned cells whose recovered static term must be admissible.

Not 1.0: the ShakeMap Vs30 band is not the Wald and Allen raster the USGS product used, so a
small tail of cells is expected to fall outside the band for that reason alone. The observed
value is always printed, so a drift shows up even while the gate passes.
"""

SUSCEPTIBILITY_MARKER = "susceptibility"


def catalog_from_comcat_geojson(path: Path) -> Catalog:
    """A minimal catalogue from a committed ComCat GeoJSON fixture, for the discriminator check."""
    payload = path.read_bytes()
    provenance = Provenance(
        source="usgs-comcat",
        source_url=str(path),
        retrieved_at=datetime.now(tz=UTC),
        sha256=hashlib.sha256(payload).hexdigest(),
        licence="public-domain (USGS)",
        adapter_version="0.1.0",
        notes="committed fixture, read by the cascade gate",
    )
    events = tuple(parse_comcat_geojson(payload, provenance=provenance))
    times = [e.origin_time for e in events]
    lons = [e.longitude for e in events]
    lats = [e.latitude for e in events]
    return Catalog(
        id=f"cascade-gate/{path.stem}",
        events=events,
        bounds=Bounds(
            min_longitude=min(lons),
            max_longitude=max(lons),
            min_latitude=min(lats),
            max_latitude=max(lats),
            start_time=min(times),
            end_time=max(times),
        )
        if events
        else None,
        sources=("usgs-comcat",),
        built_at=datetime.now(tz=UTC),
        builder_version="cascade-gate-0.1.0",
    )


def _check_fixture_integrity(repo_root: Path, findings: list[str]) -> bool:
    ok = True
    for provenance_path in sorted((repo_root / FIXTURE_ROOT).rglob("provenance.json")):
        record = json.loads(provenance_path.read_text(encoding="utf-8"))
        base = provenance_path.parent
        for name, entry in record.get("files", {}).items():
            path = base / name
            if not path.exists():
                findings.append(f"fixture missing: {path.relative_to(repo_root)}")
                ok = False
                continue
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if entry.get("sha256") and digest != entry["sha256"]:
                findings.append(
                    f"fixture sha256 mismatch: {path.relative_to(repo_root)} "
                    f"(recorded {entry['sha256'][:12]}, found {digest[:12]})"
                )
                ok = False
    return ok


_FLOAT = r"-?\d+(?:\.\d*)?(?:e-?\d+)?"


def _parse_dict_literal(text: str, name: str) -> dict[str, float]:
    """Pull ``NAME = { "k": <number>, ... }`` out of the committed USGS source, as floats."""
    match = re.search(rf"\b{name}\s*=\s*\{{(.*?)\}}", text, flags=re.S)
    if match is None:
        msg = f"{name} not found in the committed USGS reference implementation"
        raise ValueError(msg)
    return {
        key: float(value) for key, value in re.findall(rf'"(\w+)"\s*:\s*({_FLOAT})', match.group(1))
    }


def _check_coefficient_provenance(repo_root: Path, findings: list[str]) -> bool:
    """Re-derive every coefficient from the committed USGS source and compare."""
    base = repo_root / FIXTURE_ROOT / "usgs_groundfailure"
    ok = True
    expectations: list[tuple[str, str, dict[str, float]]] = [
        (
            "jessee_2018.py.txt",
            "COEFFS",
            {
                "b0": coef.NOWICKI_JESSEE_2018.intercept,
                "b1": coef.NOWICKI_JESSEE_2018.coefficients["log_pgv"],
                "b2": coef.NOWICKI_JESSEE_2018.coefficients["slope_deg"],
                "b3": coef.NOWICKI_JESSEE_2018.coefficients["lithology_coefficient"],
                "b4": coef.NOWICKI_JESSEE_2018.coefficients["cti"],
                "b5": coef.NOWICKI_JESSEE_2018.coefficients["landcover_coefficient"],
                "b6": coef.NOWICKI_JESSEE_2018.coefficients["log_pgv_x_slope_deg"],
            },
        ),
        ("jessee_2018.py.txt", "COV_COEFFS", coef.NOWICKI_JESSEE_2018.coverage_coefficients),
        (
            "zhu_2017.py.txt",
            "COEFFS",
            {
                "b0": coef.ZHU_2017_GENERAL.intercept,
                "b1": coef.ZHU_2017_GENERAL.coefficients["log_pgv_magnitude_scaled"],
                "b2": coef.ZHU_2017_GENERAL.coefficients["log_vs30"],
                "b3": coef.ZHU_2017_GENERAL.coefficients["precipitation_mm"],
                "b4": coef.ZHU_2017_GENERAL.coefficients["distance_to_water_km"],
                "b5": coef.ZHU_2017_GENERAL.coefficients["water_table_depth_m"],
            },
        ),
        ("zhu_2017.py.txt", "COV_COEFFS", coef.ZHU_2017_GENERAL.coverage_coefficients),
    ]
    for filename, block, expected in expectations:
        path = base / filename
        if not path.exists():
            findings.append(f"coefficient provenance: {path.relative_to(repo_root)} missing")
            ok = False
            continue
        published = _parse_dict_literal(path.read_text(encoding="utf-8"), block)
        for key, value in expected.items():
            found = published.get(key)
            if found is None or abs(found - value) > 1e-12:
                findings.append(
                    f"coefficient drift: {filename}:{block}[{key}] is {found!r}, "
                    f"rupture carries {value!r}"
                )
                ok = False
    # the mask cut-offs come from the .ini files
    ini_expectations = [
        ("zhu_2017_general.ini", "minpgv", 3.0),
        ("zhu_2017_general.ini", "minpga", 10.0),
        ("zhu_2017_general.ini", "vs30max", 620.0),
        ("jessee_2018.ini", "minpga", 2.0),
        ("jessee_2018.ini", "slopemin", 2.0),
        ("jessee_2018.ini", "slopemax", 90.0),
    ]
    for filename, key, expected_value in ini_expectations:
        text = (base / filename).read_text(encoding="utf-8")
        match = re.search(rf"^\s*{key}\s*=\s*({_FLOAT})", text, flags=re.M)
        if match is None or abs(float(match.group(1)) - expected_value) > 1e-12:
            findings.append(
                f"mask drift: {filename}:{key} is {match.group(1) if match else None!r}, "
                f"rupture assumes {expected_value}"
            )
            ok = False
    return ok


def run(repo_root: Path) -> GateResult:  # noqa: PLR0912, PLR0915
    findings: list[str] = []
    failed = False

    if not (repo_root / FIXTURE_ROOT).is_dir():
        return GateResult(
            name=GATE_NAME,
            status=GateStatus.FAILED,
            findings=[f"cascade fixtures missing: {FIXTURE_ROOT}"],
        )

    failed |= not _check_fixture_integrity(repo_root, findings)
    failed |= not _check_coefficient_provenance(repo_root, findings)
    findings.append("coefficient provenance: checked against the committed USGS source (CC0-1.0)")

    # ---------------------------------------------------------------- Gorkha reproduction
    ground_failure_field = None
    for case in gorkha.CASES:
        report = gorkha.run_case(repo_root, case)
        link = report.agreement(Comparison.LINK)
        shaking = report.agreement(Comparison.SHAKING)
        unconditioned = report.agreement(Comparison.UNCONDITIONED)
        findings.append(
            f"{case.model_id}: {report.n_compared_cells} of {report.n_published_cells} "
            f"published cells compared (coverage > {case.coverage_threshold})"
        )
        findings.append(
            f"{case.model_id}: link round trip max|d| = {link.max_absolute_difference:.3e} "
            f"(must be <= {LINK_TOLERANCE:g})"
        )
        if link.max_absolute_difference > LINK_TOLERANCE:
            findings.append(
                f"{case.model_id}: the link/coverage round trip is not exact; the coverage "
                f"transform or its inverse disagrees with the published product"
            )
            failed = True
        findings.append(
            f"{case.model_id}: shaking comparison r = {shaking.pearson_r:.4f}, "
            f"MAD = {shaking.mean_absolute_difference:.5f}, "
            f"max|d| = {shaking.max_absolute_difference:.5f} "
            f"(static term taken from the published product, so the static covariates are NOT "
            f"tested)"
        )
        findings.append(
            f"{case.model_id}: UNCONDITIONED (what rupture can compute today, no static "
            f"covariate sourced) r = {unconditioned.pearson_r:.4f}, "
            f"MAD = {unconditioned.mean_absolute_difference:.5f} against a published mean of "
            f"{unconditioned.published_mean:.5f} — reported, not asserted"
        )
        if report.admissibility is not None:
            adm = report.admissibility
            findings.append(
                f"{case.model_id}: recovered static term admissible (<= {adm.upper_bound:.4f}) "
                f"for {adm.fraction_within:.4f} of cells; median {adm.median:.4f}, "
                f"max {adm.maximum:.4f}"
            )
            if adm.fraction_within < ADMISSIBILITY_FLOOR:
                findings.append(
                    f"{case.model_id}: only {adm.fraction_within:.4f} of recovered static terms "
                    f"are admissible under the published coefficients (floor "
                    f"{ADMISSIBILITY_FLOOR}); a coefficient or a unit is wrong"
                )
                failed = True
        else:
            findings.append(
                f"{case.model_id}: no admissibility bound available — the lithology and "
                f"land-cover coefficients are unbounded above and rupture does not carry them"
            )
        for note in report.notes:
            if note.startswith("DEGENERATE"):
                findings.append(f"{case.model_id}: {note}")

        # keep one field for the contract and probability checks
        if ground_failure_field is None:
            published = gorkha.load_published(repo_root, case)
            shakemap = gorkha.load_shakemap(repo_root)
            keep = slice(0, 2000)
            lons = published.longitudes[keep]
            lats = published.latitudes[keep]
            model = gorkha.build_model(case)
            ground_failure_field = model.evaluate(
                shakemap.ground_motion_field(
                    imt="PGV", lons=lons, lats=lats, scenario_id=gorkha.EVENT_ID
                ),
                scenario_id=gorkha.EVENT_ID,
                pga_field=shakemap.ground_motion_field(
                    imt="PGA", lons=lons, lats=lats, scenario_id=gorkha.EVENT_ID
                ),
                magnitude=gorkha.MAGNITUDE,
            )

    # ---------------------------------------------------------------- discriminator
    catalog = catalog_from_comcat_geojson(repo_root / COMCAT_LANDSLIDE_FIXTURE)
    target = next((e for e in catalog.events if e.source_event_id == LANDSLIDE_EVENT_ID), None)
    if target is None:
        findings.append(f"{LANDSLIDE_EVENT_ID} not present in {COMCAT_LANDSLIDE_FIXTURE}")
        failed = True
    elif target.event_type is not EventType.LANDSLIDE:
        findings.append(
            f"{LANDSLIDE_EVENT_ID} is tagged {target.event_type.value}, expected landslide"
        )
        failed = True
    else:
        findings.append(f"{LANDSLIDE_EVENT_ID}: tagged landslide by the source catalogue")
    tectonic_ids = {e.source_event_id for e in catalog.earthquakes().events}
    if LANDSLIDE_EVENT_ID in tectonic_ids:
        findings.append(
            f"{LANDSLIDE_EVENT_ID} survives Catalog.earthquakes(): it would enter a tectonic "
            f"ETAS fit"
        )
        failed = True
    else:
        findings.append(
            f"{LANDSLIDE_EVENT_ID}: excluded from tectonic fitting by Catalog.earthquakes()"
        )
    _, accounting = discriminator.apply_assessments(catalog, ())
    if target is not None and target.id not in accounting.already_tagged:
        findings.append(f"{LANDSLIDE_EVENT_ID} is not counted in the cascade layer accounting")
        failed = True
    findings.append(
        f"discriminator accounting: {accounting.n_excluded_from_tectonic_fit} of "
        f"{accounting.n_events} event(s) excluded from tectonic fitting "
        f"({accounting.n_already_tagged} already tagged, "
        f"{accounting.n_reclassified} reclassified by a serac assessment)"
    )

    # ---------------------------------------------------------------- exposure + contracts
    source = SeracSlopeUnitSource(repo_root=repo_root)
    inventory = source.inventory(EXPOSURE_AOI)
    shakemap = gorkha.load_shakemap(repo_root)
    points = [_representative_point(u["geometry"]) for u in inventory.units]
    exposure = source.exposure(
        shakemap.ground_motion_field(
            imt="PGA",
            lons=np.array([p[0] for p in points], dtype=np.float64),
            lats=np.array([p[1] for p in points], dtype=np.float64),
            scenario_id=gorkha.EVENT_ID,
        ),
        aoi_id=EXPOSURE_AOI,
        pga_threshold_g=DEFAULT_PGA_THRESHOLD_G,
        scenario_id=gorkha.EVENT_ID,
    )
    findings.append(
        f"exposure: {len(exposure.units)} slope unit(s) for {EXPOSURE_AOI} from "
        f"{exposure.slope_unit_source}; {exposure.n_exceeding} above "
        f"{exposure.pga_threshold_g:g} g"
    )
    jsonschema.validate(
        exposure.model_dump(mode="json"), contracts.schema_for("cascade-exposure.v0.json")
    )
    findings.append("exposure: validates against contracts/cascade-exposure.v0.json")

    if ground_failure_field is None:
        findings.append("no ground-failure field was produced; the reproduction did not run")
        failed = True
    else:
        jsonschema.validate(
            ground_failure_field.model_dump(mode="json"),
            contracts.schema_for("ground-failure-field.v0.json"),
        )
        findings.append(
            "ground-failure field: validates against contracts/ground-failure-field.v0.json"
        )
        values = np.array([c.probability for c in ground_failure_field.cells], dtype=np.float64)
        if not np.all(np.isfinite(values)) or values.min() < 0.0 or values.max() > 1.0:
            findings.append(
                f"probabilities out of range: min {values.min()}, max {values.max()}, "
                f"{int((~np.isfinite(values)).sum())} non-finite"
            )
            failed = True
        else:
            findings.append(
                f"probabilities: {values.size} cells, all finite and in [0, 1] "
                f"(min {values.min():.4f}, max {values.max():.4f})"
            )
        if SUSCEPTIBILITY_MARKER not in (ground_failure_field.notes or ""):
            findings.append("the ground-failure field lost its susceptibility caveat")
            failed = True

    if SUSCEPTIBILITY_MARKER not in exposure.label:
        findings.append("the cascade exposure lost its susceptibility label")
        failed = True

    return GateResult(
        name=GATE_NAME,
        status=GateStatus.FAILED if failed else GateStatus.PASSED,
        findings=findings,
    )
