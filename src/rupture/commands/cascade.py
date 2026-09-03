"""``rupture cascade ...`` — triggered ground failure and co-seismic slope exposure.

Everything this command prints is a **susceptibility or exposure** product. It says where ground
failure is more or less likely given the shaking and the terrain. It does not say that a
particular slope fails.

Sub-commands::

    rupture cascade run --scenario <id> --model landslide|liquefaction
    rupture cascade exposure --aoi <id> --scenario <id> --pga-threshold <g>
    rupture cascade reproduce [--model ...]     # the Gorkha comparison, offline
    rupture cascade discriminate --catalog <dir|geojson> [--export-dir <serac>]

Registration note: ``src/rupture/cli.py`` does not yet mount this sub-application (that file is
the architect's). Until it does, run these as ``python -m rupture.commands.cascade ...``; the
``app`` object below is the one ``cli.py`` needs to add with a single ``add_typer`` line.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import numpy as np
import typer

from rupture.adapters.cascade import gorkha
from rupture.adapters.cascade.serac import (
    DEFAULT_PGA_THRESHOLD_G,
    DEFAULT_STEEP_SLOPE_DEG,
    SeracExportMissingError,
    SeracSlopeUnitSource,
)
from rupture.cascade import discriminator
from rupture.cascade.models import build as build_model
from rupture.domain.cascade import CascadeExposure, GroundFailureField

REPO_ROOT = Path(__file__).resolve().parents[3]

EXIT_FAILED = 1
EXIT_NOT_IMPLEMENTED = 2

app = typer.Typer(
    help=(
        "Triggered cascades: ground-failure susceptibility and co-seismic slope exposure. "
        "These are susceptibility products, not forecasts of individual slope failure."
    ),
    no_args_is_help=True,
)

RootOpt = Annotated[Path, typer.Option("--root", help="Repository root.")]
OutOpt = Annotated[Path | None, typer.Option("--out", help="Write the record here as JSON.")]


def _emit(payload: dict[str, object], out: Path | None) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, default=str)
    if out is None:
        typer.echo(text)
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    typer.echo(f"wrote {out}")


@app.command("run")
def run(
    scenario: Annotated[str, typer.Option("--scenario", help="Scenario id.")],
    model: Annotated[
        str, typer.Option("--model", help="landslide | liquefaction | a model id.")
    ] = "landslide",
    root: RootOpt = REPO_ROOT,
    out: OutOpt = None,
) -> None:
    """Evaluate a ground-failure model over a scenario's shaking.

    Only the committed Gorkha case (``--scenario us20002926``) is wired offline today; any other
    scenario needs a ground-motion field this command cannot yet locate, and exits 2 saying so
    rather than inventing one.
    """
    try:
        instance = build_model(model)
    except KeyError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    if scenario != gorkha.EVENT_ID:
        typer.echo(
            f"rupture cascade run --scenario {scenario}: not implemented — rupture has no "
            f"ground-motion field for that scenario. The only scenario wired offline is "
            f"'{gorkha.EVENT_ID}' (2015 Gorkha, from the committed ShakeMap slice). Scenario "
            f"fields from the loss layer arrive with F2.",
            err=True,
        )
        raise typer.Exit(EXIT_NOT_IMPLEMENTED)
    case = gorkha.CASE_FOR_MODEL[instance.model_id]
    shakemap = gorkha.load_shakemap(root)
    published = gorkha.load_published(root, case)
    pgv_field = shakemap.ground_motion_field(
        imt="PGV",
        lons=published.longitudes,
        lats=published.latitudes,
        scenario_id=scenario,
    )
    pga_field = shakemap.ground_motion_field(
        imt="PGA",
        lons=published.longitudes,
        lats=published.latitudes,
        scenario_id=scenario,
    )
    field: GroundFailureField = instance.evaluate(
        pgv_field,
        scenario_id=scenario,
        pga_field=pga_field,
        magnitude=gorkha.MAGNITUDE,
    )
    typer.echo(f"model: {field.model_id} ({field.model_version})")
    typer.echo(f"cells: {len(field.cells)}  mean areal coverage: {field.mean_probability():.6f}")
    typer.echo(f"label: {field.notes}")
    if out is not None:
        _emit(field.model_dump(mode="json"), out)


@app.command("exposure")
def exposure(
    aoi: Annotated[str, typer.Option("--aoi", help="serac AOI id, e.g. lhende-khola-trishuli.")],
    scenario: Annotated[str, typer.Option("--scenario", help="Scenario id.")] = gorkha.EVENT_ID,
    pga_threshold: Annotated[
        float, typer.Option("--pga-threshold", help="Screening threshold in g.")
    ] = DEFAULT_PGA_THRESHOLD_G,
    steep_slope_deg: Annotated[
        float, typer.Option("--steep-slope-deg", help="Steepness screen, applied only where a "
                            "unit carries a slope.")
    ] = DEFAULT_STEEP_SLOPE_DEG,
    export_dir: Annotated[
        Path | None, typer.Option("--export-dir", help="serac export dir (else SERAC_EXPORT_DIR).")
    ] = None,
    root: RootOpt = REPO_ROOT,
    out: OutOpt = None,
) -> None:
    """Flag slope units shaken above a screening threshold. A threshold is not a failure criterion."""
    source = SeracSlopeUnitSource(export_dir=export_dir, repo_root=root)
    shakemap = gorkha.load_shakemap(root)
    try:
        inventory = source.inventory(aoi)
    except SeracExportMissingError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(EXIT_FAILED) from exc
    lons: list[float] = []
    lats: list[float] = []
    from rupture.adapters.cascade.serac import _representative_point  # noqa: PLC0415

    for unit in inventory.units:
        lon, lat = _representative_point(unit["geometry"])
        lons.append(lon)
        lats.append(lat)
    try:
        field = shakemap.ground_motion_field(
            imt="PGA",
            lons=np.array(lons, dtype=np.float64),
            lats=np.array(lats, dtype=np.float64),
            scenario_id=scenario,
        )
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
    typer.echo(f"slope-unit source: {record.slope_unit_source}")
    typer.echo(f"label: {record.label}")
    typer.echo(f"notes: {record.notes}")
    if out is not None:
        _emit(record.model_dump(mode="json"), out)


@app.command("reproduce")
def reproduce(
    model: Annotated[
        str | None, typer.Option("--model", help="Only this model; default both.")
    ] = None,
    root: RootOpt = REPO_ROOT,
    out: OutOpt = None,
) -> None:
    """Compare rupture against the published USGS ground-failure product for Gorkha, offline."""
    cases = gorkha.CASES
    if model is not None:
        resolved = build_model(model).model_id
        cases = tuple(c for c in cases if c.model_id == resolved)
    reports = {case.model_id: gorkha.run_case(root, case) for case in cases}
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
