"""`rupture region ...` — Test regions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from rupture.adapters.sources.regions import (
    default_regions,
    default_regions_root,
    list_region_ids,
    load_region,
    write_region,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

app = typer.Typer(help="Test regions.", no_args_is_help=True)


@app.command("list")
def list_(root: Annotated[Path, typer.Option(help="Repository root.")] = REPO_ROOT) -> None:
    """List the test regions under data/regions/."""
    regions_root = default_regions_root(root)
    ids = list_region_ids(regions_root)
    if not ids:
        typer.echo(f"no regions under {regions_root} (run `rupture region init`)", err=True)
        raise typer.Exit(1)
    for rid in ids:
        r = load_region(regions_root, rid)
        mc = f"mc={r.mc.mc:.2f} ({r.mc.method.value})" if r.mc else "mc=None"
        typer.echo(
            f"{rid:16s} {r.tectonic_setting.value:22s} M>={r.target_min_magnitude:<5g} "
            f"depth<={r.depth_max_km:g} km  {len(r.polygon)} vertices  {mc}"
        )


@app.command("show")
def show(
    region_id: Annotated[str, typer.Argument(help="Region id.")],
    root: Annotated[Path, typer.Option(help="Repository root.")] = REPO_ROOT,
) -> None:
    """Print one Region record (polygon, thresholds, fitted Mc) as JSON."""
    r = load_region(default_regions_root(root), region_id)
    typer.echo(json.dumps(r.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command("init")
def init(
    root: Annotated[Path, typer.Option(help="Repository root.")] = REPO_ROOT,
    force: Annotated[
        bool, typer.Option("--force", help="Overwrite existing region files.")
    ] = False,
) -> None:
    """Write the three default regions (California RELM boundary, Nepal MHT, Türkiye EAF)."""
    regions_root = default_regions_root(root)
    for r in default_regions():
        existing = regions_root / r.id / "region.json"
        if existing.exists() and not force:
            typer.echo(
                f"{existing} exists; skipping (use --force to overwrite; fitted mc would be lost)"
            )
            continue
        json_path, geo_path = write_region(regions_root, r)
        typer.echo(f"wrote {json_path} and {geo_path.name} ({len(r.polygon)} vertices)")
