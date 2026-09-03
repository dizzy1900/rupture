"""`rupture catalog ...` — Build and inspect homogenised catalogues."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from rupture.adapters.catalogs import SOURCE_IDS
from rupture.adapters.sources.regions import (
    default_regions_root,
    load_region,
    write_region,
)
from rupture.adapters.storage.geoparquet import read_catalog, write_catalog
from rupture.domain import Catalog, CompletenessEstimate, McMethod, Region
from rupture.pipelines.build_catalog import MergeConfig, build_catalog, mw_coverage_at

REPO_ROOT = Path(__file__).resolve().parents[3]
EXIT_FAIL = 1
MIN_PUBLISHABLE_B = 0.7
MIN_PUBLISHABLE_COVERAGE = 0.8


def region_mc_decision(
    catalog: Catalog, region: Region, *, force: bool = False
) -> tuple[Region, str]:
    """Apply the publication rules for ``Region.mc`` (QA blocker B1).

    Every estimate goes into ``mc_estimates`` with a note naming the Mw coverage at the target
    threshold and the maximum-curvature b. ``mc`` is set to the maximum-curvature estimate only
    when that b is >= 0.7 **and** at least 80 % of earthquakes reported at or above the target
    threshold carry a homogenised Mw; otherwise ``mc`` is left ``None`` (unless ``force``) and the
    reason is returned for printing. A too-low b or too-low coverage means the Mw distribution is
    not the region's seismicity and the estimate would mislead the fit.
    """
    maxc = catalog.preferred_mc(McMethod.MAXIMUM_CURVATURE)
    with_mw, total = mw_coverage_at(catalog, region.target_min_magnitude)
    coverage = with_mw / total if total else 0.0
    b = maxc.b_value if maxc is not None else None
    tag = (
        f"Mw coverage at M>={region.target_min_magnitude:g}: {with_mw}/{total} "
        f"({coverage:.0%}); maximum-curvature b={b:.2f}"
        if b is not None
        else f"Mw coverage at M>={region.target_min_magnitude:g}: {with_mw}/{total} "
        f"({coverage:.0%}); maximum-curvature b unavailable"
    )
    estimates = tuple(
        c.model_copy(update={"notes": f"{c.notes + '; ' if c.notes else ''}{tag}"})
        for c in catalog.completeness
    )
    problems: list[str] = []
    if maxc is None:
        problems.append("no maximum-curvature estimate")
    if b is None or b < MIN_PUBLISHABLE_B:
        problems.append(
            f"maximum-curvature b {b if b is None else round(b, 2)} < {MIN_PUBLISHABLE_B}"
        )
    if coverage < MIN_PUBLISHABLE_COVERAGE:
        problems.append(f"Mw coverage {coverage:.0%} < {MIN_PUBLISHABLE_COVERAGE:.0%}")
    publish = maxc is not None and (not problems or force)
    mc_est: CompletenessEstimate | None = None
    if publish:
        mc_est = next(c for c in estimates if c.method is McMethod.MAXIMUM_CURVATURE)
        if problems:
            mc_est = mc_est.model_copy(
                update={
                    "notes": (
                        f"{mc_est.notes}; published with --force-mc despite: " + "; ".join(problems)
                    )
                }
            )
    updated = region.model_copy(update={"mc": mc_est, "mc_estimates": estimates})
    if mc_est is not None:
        reason = f"mc={mc_est.mc:.2f} published ({tag})" + (" [forced]" if problems else "")
    else:
        reason = (
            "mc left null: " + "; ".join(problems) + f" ({tag}); estimates written to mc_estimates"
        )
    return updated, reason


app = typer.Typer(help="Build and inspect homogenised catalogues.", no_args_is_help=True)


def _parse_utc(text: str) -> datetime:
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def default_min_magnitude(target: float) -> float:
    """Source-magnitude floor for a build: 1.5 below the region target (Mc needs the FMD below)."""
    return round(target - 1.5, 2)


@app.command("build")
def build(  # noqa: PLR0917  typer options are positional to typer
    region: Annotated[str, typer.Option("--region", help="Region id under data/regions/.")],
    start: Annotated[str, typer.Option("--from", help="UTC start (inclusive), ISO 8601.")],
    end: Annotated[str, typer.Option("--to", help="UTC end (exclusive), ISO 8601.")],
    sources: Annotated[
        str,
        typer.Option("--sources", help=f"Comma-separated subset of: {', '.join(SOURCE_IDS)}."),
    ] = "comcat,isc,gcmt",
    offline_fixtures: Annotated[
        bool, typer.Option("--offline-fixtures", help="Read committed fixtures; no network.")
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Output directory (default data/catalogs/<region>)."),
    ] = None,
    min_magnitude: Annotated[
        float | None,
        typer.Option("--min-magnitude", help="Source magnitude floor (default: target - 1.5)."),
    ] = None,
    time_window_s: Annotated[float, typer.Option(help="Duplicate window, seconds.")] = 16.0,
    distance_km: Annotated[float, typer.Option(help="Duplicate window, km.")] = 100.0,
    update_region_mc: Annotated[
        bool,
        typer.Option(
            "--update-region-mc/--no-update-region-mc",
            help="Write the fitted maximum-curvature Mc into data/regions/<region>/region.json.",
        ),
    ] = False,
    no_etas_cross_check: Annotated[
        bool, typer.Option("--no-etas-cross-check", help="Skip the etas KS Mc cross-check.")
    ] = False,
    force_mc: Annotated[
        bool,
        typer.Option(
            "--force-mc",
            help="With --update-region-mc: publish mc even if b < 0.7 or Mw coverage < 80 %.",
        ),
    ] = False,
    root: Annotated[Path, typer.Option(help="Repository root.")] = REPO_ROOT,
) -> None:
    """Merge sources, homogenise magnitudes, estimate Mc, write GeoParquet + homogenisation log."""
    regions_root = default_regions_root(root)
    reg = load_region(regions_root, region)
    t0, t1 = _parse_utc(start), _parse_utc(end)
    floor = (
        default_min_magnitude(reg.target_min_magnitude) if min_magnitude is None else min_magnitude
    )
    names = [s for s in sources.split(",") if s.strip()]
    fixtures = root / "data" / "fixtures" if offline_fixtures else None
    raw_dir = None if offline_fixtures else root / "data" / "raw"
    out_dir = out or (root / "data" / "catalogs" / region)
    typer.echo(
        f"catalog build: region={region} [{t0.isoformat()}, {t1.isoformat()}) sources={names} "
        f"min_magnitude={floor} {'offline' if offline_fixtures else 'online'}"
    )
    started = time.monotonic()
    catalog = build_catalog(
        reg,
        t0,
        t1,
        names,
        offline_fixtures=fixtures,
        raw_dir=raw_dir,
        min_magnitude=floor,
        merge=MergeConfig(time_window_s=time_window_s, distance_km=distance_km),
        etas_cross_check=not no_etas_cross_check,
    )
    paths = write_catalog(catalog, out_dir)
    elapsed = time.monotonic() - started
    typer.echo(f"wrote {paths['events']} ({len(catalog)} events) in {elapsed:.1f}s")
    typer.echo(f"sources used: {', '.join(catalog.sources) or '(none)'}")
    for kind, n in catalog.count_by_type().items():
        if n:
            typer.echo(f"  {kind.value}: {n}")
    for c in catalog.completeness:
        b = (
            f" b={c.b_value:.2f}+/-{c.b_value_uncertainty:.2f}"
            if c.b_value and c.b_value_uncertainty
            else ""
        )
        typer.echo(f"  Mc[{c.method.value}] = {c.mc:.2f} (n={c.n_events}){b}")
    if catalog.notes:
        typer.echo(f"notes: {catalog.notes}")
    with_mw, total = mw_coverage_at(catalog, reg.target_min_magnitude)
    typer.echo(
        f"Mw coverage at M>={reg.target_min_magnitude:g} (reported, any scale): "
        f"{with_mw}/{total}" + (f" ({with_mw / total:.0%})" if total else "")
    )
    if update_region_mc:
        if not catalog.completeness:
            typer.echo("no completeness estimates; region.json left unchanged", err=True)
            raise typer.Exit(EXIT_FAIL)
        updated, reason = region_mc_decision(catalog, reg, force=force_mc)
        json_path, _ = write_region(regions_root, updated)
        typer.echo(f"updated {json_path}: {reason}")


@app.command("inspect")
def inspect(
    path: Annotated[Path, typer.Argument(help="Catalogue directory written by `catalog build`.")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print catalog.meta.json fields.")
    ] = False,
) -> None:
    """Summarise a built catalogue: counts, bounds, completeness, sources."""
    catalog = read_catalog(path)
    if as_json:
        meta = catalog.model_dump(mode="json", exclude={"events", "homogenisation_log"})
        meta["n_events"] = len(catalog)
        typer.echo(json.dumps(meta, indent=2))
        return
    typer.echo(f"catalog {catalog.id}")
    typer.echo(f"  region: {catalog.region_id}  sources: {', '.join(catalog.sources)}")
    typer.echo(
        f"  events: {len(catalog)}  built: {catalog.built_at.isoformat()} "
        f"v{catalog.builder_version}"
    )
    for kind, n in catalog.count_by_type().items():
        if n:
            typer.echo(f"    {kind.value}: {n}")
    with_mw = sum(1 for e in catalog.events if e.mw is not None)
    typer.echo(f"  with homogenised Mw: {with_mw}  without: {len(catalog) - with_mw}")
    if catalog.bounds:
        b = catalog.bounds
        typer.echo(
            f"  bounds: lon [{b.min_longitude:.3f}, {b.max_longitude:.3f}] lat "
            f"[{b.min_latitude:.3f}, {b.max_latitude:.3f}] time [{b.start_time.isoformat()}, "
            f"{b.end_time.isoformat()})"
        )
    for c in catalog.completeness:
        bv = f" b={c.b_value:.2f}" if c.b_value else ""
        typer.echo(f"  Mc[{c.method.value}] = {c.mc:.2f} (n={c.n_events}){bv}")
    typer.echo(f"  homogenisation log entries: {len(catalog.homogenisation_log)}")
    if catalog.notes:
        typer.echo(f"  notes: {catalog.notes}")


@app.command("refresh-fixtures")
def refresh_fixtures(
    root: Annotated[Path, typer.Option(help="Repository root.")] = REPO_ROOT,
) -> None:
    """Re-cut the committed catalogue fixtures from the live services (network)."""
    from rupture.adapters.catalogs.refresh import refresh_all  # noqa: PLC0415

    for line in refresh_all(root / "data" / "fixtures"):
        typer.echo(line)
