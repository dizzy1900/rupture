"""`rupture observe ...` — inspect latency-aware observation feeds, mostly offline.

Intended mount (orchestrator, do not edit ``src/rupture/cli.py`` from this worktree)::

    from rupture.commands import observe
    app.add_typer(observe.app, name="observe")

These commands read committed fixtures or, without ``--offline-fixtures``, would fetch. They
do not adjudicate GNSS precursors and they do not claim GNSS predicts earthquakes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from rupture.adapters.observations.ngl import CITATION, NglGnssSource
from rupture.adapters.observations.usgs_feed import FEEDS, UsgsRealtimeFeed
from rupture.domain import VintagePolicy
from rupture.domain.observation import GnssProduct

REPO_ROOT = Path(__file__).resolve().parents[3]

app = typer.Typer(
    help="Observation feeds: NGL GNSS and USGS real-time GeoJSON, as-of aware.",
    no_args_is_help=True,
)


def _parse_utc(text: str) -> datetime:
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    value = datetime.fromisoformat(raw)
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "timestamp must be timezone-aware UTC"
        raise typer.BadParameter(msg)
    return value.astimezone(UTC)


@app.command("ngl-info")
def ngl_info(
    station: Annotated[str, typer.Option("--station", help="Four-character NGL station id.")],
    root: Annotated[Path, typer.Option("--root", help="Repository root.")] = REPO_ROOT,
) -> None:
    """Summarise a committed NGL tenv3 fixture (offline; no network)."""
    source = NglGnssSource(
        station, product=GnssProduct.FINAL, offline_fixtures=root / "data" / "fixtures"
    )
    positions = source.series()
    if not positions:
        typer.echo(f"station {station.upper()}: 0 positions")
        return
    first, last = positions[0], positions[-1]
    typer.echo(f"station {first.station_id}")
    typer.echo(f"  source: {source.source_id}  product: {first.product.value}")
    typer.echo(f"  n_positions: {len(positions)}")
    typer.echo(
        f"  valid_time: [{first.valid_time.isoformat()}, {last.valid_time.isoformat()}]"
    )
    typer.echo(
        f"  available_time: [{first.available_time.isoformat()}, "
        f"{last.available_time.isoformat()}]"
    )
    typer.echo(f"  licence: {first.provenance.licence}")
    typer.echo(f"  citation: {CITATION}")
    typer.echo(
        "  note: data port only — not Bletery & Nocquet adjudication, not a prediction"
    )


@app.command("ngl-asof")
def ngl_asof(
    station: Annotated[str, typer.Option("--station", help="Four-character NGL station id.")],
    as_of: Annotated[str, typer.Option("--as-of", help="UTC instant, ISO 8601.")],
    offline_fixtures: Annotated[
        bool, typer.Option("--offline-fixtures", help="Read committed fixtures; no network.")
    ] = False,
    root: Annotated[Path, typer.Option("--root", help="Repository root.")] = REPO_ROOT,
) -> None:
    """Positions readable strictly before ``as_of`` (half-open; FINAL lag applied)."""
    if not offline_fixtures:
        typer.echo("ngl-asof: pass --offline-fixtures to read committed fixtures", err=True)
        raise typer.Exit(1)
    instant = _parse_utc(as_of)
    source = NglGnssSource(
        station, product=GnssProduct.FINAL, offline_fixtures=root / "data" / "fixtures"
    )
    kept = source.available_as_of(instant, policy=VintagePolicy.EXCLUDE_UNKNOWN)
    loaded = source.series()
    typer.echo(
        f"{station.upper()} as of {instant.isoformat()}: {len(kept)} of {len(loaded)} "
        f"position(s) with available_time < as_of"
    )
    if kept:
        typer.echo(
            f"  last kept valid_time {kept[-1].valid_time.isoformat()} "
            f"available_time {kept[-1].available_time.isoformat()}"
        )


@app.command("feed-info")
def feed_info(
    offline_fixtures: Annotated[
        bool, typer.Option("--offline-fixtures", help="Read committed fixtures; no network.")
    ] = False,
    root: Annotated[Path, typer.Option("--root", help="Repository root.")] = REPO_ROOT,
) -> None:
    """Summarise the committed USGS GeoJSON fixture and name the live feeds."""
    if not offline_fixtures:
        typer.echo("feed-info: pass --offline-fixtures to read committed fixtures", err=True)
        raise typer.Exit(1)
    feed = UsgsRealtimeFeed(offline_fixtures=root / "data" / "fixtures")
    catalog = feed.catalog()
    summary = catalog.vintage_summary()
    typer.echo(f"source: {feed.source_id}")
    typer.echo(f"  events: {len(catalog)}")
    typer.echo(f"  vintage: {summary.render()}")
    typer.echo("  documented live feeds (moving windows, not this fixture):")
    for name, url in FEEDS.items():
        typer.echo(f"    {name}: {url}")
    typer.echo(
        "  fixture is a cut of committed ComCat Ridgecrest GeoJSON, not a live all_day snapshot"
    )
