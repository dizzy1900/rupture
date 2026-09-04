"""``rupture cascade ...`` — triggered ground failure and co-seismic slope exposure.

Everything this command prints is a **susceptibility or exposure** product. It says where ground
failure is more or less likely given the shaking and the terrain. It does not say that a
particular slope fails.

Sub-commands::

    rupture cascade cases
    rupture cascade run --scenario <id> --model landslide|liquefaction
    rupture cascade run --grid-xml <shakemap grid.xml> [--stride N] [--magnitude M]
    rupture cascade run --pgv-field <gmf.json> [--pga-field <gmf.json>] [--magnitude M]
    rupture cascade exposure --aoi <id> --scenario <id> [--out-parquet <file.parquet>]
    rupture cascade fetch-shakemap --event <comcat id> --out-dir <dir>      # network
    rupture cascade reproduce [--model ...]     # the Gorkha comparison, offline
    rupture cascade discriminate --catalog <dir|geojson> [--export-dir <serac>]

Both input routes the layer is specified with are reachable here: a published ShakeMap grid for a
real event (committed slice, a fetched ``grid.xml``, or one fetched by hand) and a scenario field
computed by a GSIM. :mod:`rupture.adapters.cascade.cases` holds the routes; nothing in this module
manufactures shaking.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import numpy as np
import typer

from rupture.adapters.cascade import cases, chamoli, comcat_shakemap, gorkha
from rupture.adapters.cascade.geoparquet import write_cascade_exposure
from rupture.adapters.cascade.serac import (
    DEFAULT_PGA_THRESHOLD_G,
    DEFAULT_STEEP_SLOPE_DEG,
    SeracExportMissingError,
    SeracSlopeUnitSource,
    _representative_point,
)
from rupture.cascade import discriminator
from rupture.cascade.models import build as build_model
from rupture.domain.cascade import CascadeExposure, GroundFailureField

REPO_ROOT = Path(__file__).resolve().parents[3]

EXIT_FAILED = 1

app = typer.Typer(
    help=(
        "Triggered cascades: ground-failure susceptibility and co-seismic slope exposure. "
        "These are susceptibility products, not forecasts of individual slope failure."
    ),
    no_args_is_help=True,
)

RootOpt = Annotated[Path, typer.Option("--root", help="Repository root.")]
OutOpt = Annotated[Path | None, typer.Option("--out", help="Write the record here as JSON.")]
PgvFieldOpt = Annotated[
    Path | None,
    typer.Option("--pgv-field", help="GroundMotionField JSON carrying PGV (any engine)."),
]
PgaFieldOpt = Annotated[
    Path | None, typer.Option("--pga-field", help="GroundMotionField JSON carrying PGA.")
]
GridXmlOpt = Annotated[
    Path | None, typer.Option("--grid-xml", help="A published ShakeMap grid.xml on disk.")
]


def _emit(payload: dict[str, object], out: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if out is None:
        typer.echo(text)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    typer.echo(f"wrote {out}")


@app.command("cases")
def list_cases() -> None:
    """List the scenarios that run offline from committed inputs, and their input route."""
    for case in cases.CASES:
        typer.echo(f"{case.scenario_id}  [{case.route}]")
        typer.echo(f"    {case.description}")
    typer.echo(
        "Any other event or scenario: supply the shaking with --grid-xml (see "
        "`rupture cascade fetch-shakemap`) or --pgv-field/--pga-field."
    )


@app.command("run")
def run(  # noqa: PLR0917 — typer builds the option list from the signature
    scenario: Annotated[
        str | None, typer.Option("--scenario", help="Scenario id; see `rupture cascade cases`.")
    ] = None,
    model: Annotated[
        str, typer.Option("--model", help="landslide | liquefaction | a model id.")
    ] = "landslide",
    pgv_field: PgvFieldOpt = None,
    pga_field: PgaFieldOpt = None,
    grid_xml: GridXmlOpt = None,
    stride: Annotated[int, typer.Option("--stride", help="Use every Nth cell of a grid.xml.")] = 1,
    magnitude: Annotated[
        float | None,
        typer.Option("--magnitude", help="Event magnitude (the liquefaction model needs one)."),
    ] = None,
    root: RootOpt = REPO_ROOT,
    out: OutOpt = None,
) -> None:
    """Evaluate a ground-failure model over a scenario's or an event's shaking.

    The shaking comes from one of four routes (``rupture cascade cases`` lists the committed
    ones). A request rupture cannot satisfy exits 1 saying exactly what would satisfy it, rather
    than inventing a field.
    """
    try:
        # built once to resolve the alias, then again on the grid the route actually returns
        model_id = build_model(model).model_id
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    try:
        shaking = cases.resolve(
            root,
            scenario=scenario,
            model_id=model_id,
            pgv_field=pgv_field,
            pga_field=pga_field,
            grid_xml=grid_xml,
            stride=stride,
            magnitude=magnitude,
        )
    except (cases.ShakingUnavailableError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    resolved_magnitude = magnitude if magnitude is not None else shaking.magnitude
    instance = build_model(model, cell_size_deg=shaking.cell_size_deg)
    scenario_id = scenario or shaking.pgv.scenario_id
    try:
        field: GroundFailureField = instance.evaluate(
            shaking.pgv,
            scenario_id=scenario_id,
            pga_field=shaking.pga,
            magnitude=resolved_magnitude,
        )
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    typer.echo(f"shaking: {shaking.route} — {shaking.description}")
    typer.echo(f"model: {field.model_id} ({field.model_version})")
    typer.echo(f"cells: {len(field.cells)}  mean areal coverage: {field.mean_probability():.6f}")
    typer.echo(f"label: {field.notes}")
    if out is not None:
        _emit(field.model_dump(mode="json"), out)


@app.command("exposure")
def exposure(
    *,
    aoi: Annotated[str, typer.Option("--aoi", help="serac AOI id, e.g. lhende-khola-trishuli.")],
    scenario: Annotated[str, typer.Option("--scenario", help="Scenario id.")] = gorkha.EVENT_ID,
    pga_threshold: Annotated[
        float, typer.Option("--pga-threshold", help="Screening threshold in g.")
    ] = DEFAULT_PGA_THRESHOLD_G,
    steep_slope_deg: Annotated[
        float,
        typer.Option(
            "--steep-slope-deg", help="Steepness screen, applied only where a unit carries a slope."
        ),
    ] = DEFAULT_STEEP_SLOPE_DEG,
    export_dir: Annotated[
        Path | None, typer.Option("--export-dir", help="serac export dir (else SERAC_EXPORT_DIR).")
    ] = None,
    pga_field: PgaFieldOpt = None,
    grid_xml: GridXmlOpt = None,
    root: RootOpt = REPO_ROOT,
    out: OutOpt = None,
    out_parquet: Annotated[
        Path | None,
        typer.Option("--out-parquet", help="Write the CascadeExposure as GeoParquet here."),
    ] = None,
) -> None:
    """Flag slope units shaken above a screening threshold.

    A threshold is a screening device, not a failure criterion.
    """
    source = SeracSlopeUnitSource(export_dir=export_dir, repo_root=root)
    try:
        inventory = source.inventory(aoi)
    except SeracExportMissingError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    points = [_representative_point(unit["geometry"]) for unit in inventory.units]
    try:
        field, route = cases.exposure_pga(
            root,
            scenario=scenario,
            lons=np.array([p[0] for p in points], dtype=np.float64),
            lats=np.array([p[1] for p in points], dtype=np.float64),
            pga_field=pga_field,
            grid_xml=grid_xml,
        )
    except (cases.ShakingUnavailableError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    except ValueError as exc:
        typer.echo(
            f"cannot overlay scenario {scenario} on AOI {aoi}: {exc}. rupture does not "
            f"extrapolate a ShakeMap beyond its own grid.",
            err=True,
        )
        raise typer.Exit(EXIT_FAILED) from exc
    record: CascadeExposure = source.exposure(
        field,
        aoi_id=aoi,
        pga_threshold_g=pga_threshold,
        steep_slope_deg=steep_slope_deg,
        scenario_id=scenario,
    )
    typer.echo(f"aoi: {record.aoi_id}  units: {len(record.units)}  flagged: {record.n_exceeding}")
    typer.echo(f"shaking: {route} — ground-motion field {record.shaking_source}")
    typer.echo(f"slope-unit source: {record.slope_unit_source}")
    typer.echo(f"label: {record.label}")
    typer.echo(f"notes: {record.notes}")
    if out is not None:
        _emit(record.model_dump(mode="json"), out)
    if out_parquet is not None:
        written = write_cascade_exposure(record, out_parquet)
        typer.echo(f"wrote {written} (GeoParquet, EPSG:4326, one row per slope unit)")


@app.command("fetch-shakemap")
def fetch_shakemap(
    *,
    event: Annotated[str, typer.Option("--event", help="ComCat event id, e.g. us20002926.")],
    out_dir: Annotated[
        Path, typer.Option("--out-dir", help="Directory to write grid.xml + provenance.json.")
    ],
    url: Annotated[
        str | None,
        typer.Option("--url", help="Skip the product lookup and download this grid.xml URL."),
    ] = None,
) -> None:
    """Download the published ShakeMap ``grid.xml`` for a real ComCat event. **Network.**

    Writes ``grid.xml`` and a ``provenance.json`` recording the URL, retrieval time, sha256 and
    licence. Feed the result to ``rupture cascade run --grid-xml``.
    """
    try:
        written = comcat_shakemap.fetch_shakemap(event, out_dir, grid_url=url)
    except (comcat_shakemap.ShakeMapFetchError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    for name, path in written.items():
        typer.echo(f"wrote {name}: {path}")
    typer.echo(f"next: rupture cascade run --grid-xml {written['grid']} --model landslide")


@app.command("reproduce")
def reproduce(
    model: Annotated[
        str | None, typer.Option("--model", help="Only this model; default both.")
    ] = None,
    root: RootOpt = REPO_ROOT,
    out: OutOpt = None,
) -> None:
    """Compare rupture against the published USGS ground-failure product for Gorkha, offline."""
    all_cases = gorkha.CASES
    if model is not None:
        resolved = build_model(model).model_id
        all_cases = tuple(c for c in all_cases if c.model_id == resolved)
    reports = {case.model_id: gorkha.run_case(root, case) for case in all_cases}
    for model_id, report in reports.items():
        typer.echo(f"--- {model_id} ({report.n_compared_cells} cells compared)")
        for item in report.agreements:
            typer.echo(
                f"    {item.comparison.value:14s} r={item.pearson_r:+.4f} "
                f"MAD={item.mean_absolute_difference:.5f} "
                f"max|d|={item.max_absolute_difference:.5f} "
                f"within {item.tolerance:g}: {item.fraction_within_tolerance:.4f}"
            )
        if report.admissibility is not None:
            adm = report.admissibility
            typer.echo(
                f"    admissible static term <= {adm.upper_bound:.4f}: "
                f"{adm.fraction_within:.4f} of cells"
            )
        typer.echo(f"    covariates not sourced: {', '.join(report.covariates_not_sourced)}")
    if out is not None:
        _emit({k: v.as_dict() for k, v in reports.items()}, out)


@app.command("scenario")
def scenario_summary(
    root: RootOpt = REPO_ROOT,
    out: OutOpt = None,
) -> None:
    """Print the Chamoli/Ronti scenario rupture and its assumptions, without running a model."""
    rupture_model = chamoli.scenario_rupture(root)
    window = chamoli.aoi_window(root)
    typer.echo(f"scenario: {rupture_model.id}  Mw {rupture_model.magnitude:.2f}  HYPOTHETICAL")
    typer.echo(
        f"window: {window.min_longitude:.4f}-{window.max_longitude:.4f} E, "
        f"{window.min_latitude:.4f}-{window.max_latitude:.4f} N at "
        f"{window.cell_size_deg:.6f} deg, derived from {', '.join(window.derived_from)}"
    )
    for assumption in chamoli.ASSUMPTIONS:
        typer.echo(f"  assumed: {assumption}")
    if out is not None:
        _emit(rupture_model.model_dump(mode="json"), out)


@app.command("discriminate")
def discriminate(
    catalog: Annotated[
        Path, typer.Option("--catalog", help="ComCat GeoJSON file with the events to assess.")
    ],
    export_dir: Annotated[
        Path | None, typer.Option("--export-dir", help="serac export dir (else SERAC_EXPORT_DIR).")
    ] = None,
    threshold: Annotated[
        float, typer.Option("--threshold", help="p_mass_movement acceptance threshold.")
    ] = discriminator.DEFAULT_ACCEPTANCE_THRESHOLD,
    out: OutOpt = None,
) -> None:
    """Apply serac's SourceTypeAssessment records and report what left the tectonic fit."""
    from rupture.validation.cascade import catalog_from_comcat_geojson  # noqa: PLC0415

    built = catalog_from_comcat_geojson(catalog)
    if export_dir is None:
        import os  # noqa: PLC0415

        env = os.environ.get("SERAC_EXPORT_DIR")
        export_dir = Path(env) if env else None
    if export_dir is None:
        _, accounting = discriminator.apply_assessments(built, (), threshold=threshold)
        typer.echo(
            "discriminator: SERAC_EXPORT_DIR is not set, so no SourceTypeAssessment was read; "
            "the accounting below reflects the source catalogue's own typing only."
        )
    else:
        _, accounting = discriminator.apply_from_export(built, export_dir, threshold=threshold)
    for line in accounting.render():
        typer.echo(line)
    if out is not None:
        _emit(accounting.as_dict(), out)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
