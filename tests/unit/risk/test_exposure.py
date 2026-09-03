"""Exposure: where the portfolio came from, what it is worth, and what it does not know."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import geopandas
import jsonschema
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

from rupture.adapters.exposure import GeoParquetExposureSource, SeracExposureSource
from rupture.adapters.exposure.geoparquet_import import ExposureImportError
from rupture.adapters.exposure.serac_export import ENV_VAR, FALLBACK_REL, SeracExportError
from rupture.adapters.exposure.valuation import CENTRAL_USD_PER_KW, DEFAULT_BASIS
from rupture.domain import contracts
from rupture.domain.money import ModelProvenance
from rupture.ports.exposure import ExposureSource
from rupture.risk.exposure_schema import ExposureImport, ExposureImportRow, json_schema
from tests.unit.risk.conftest import REPO_ROOT, RISK_FIXTURES

AOI = "lhende-khola-trishuli"
FALLBACK = REPO_ROOT / FALLBACK_REL / AOI / "exposed_assets.geojson"
EXPECTED_ASSETS = 14
EXPECTED_VALUED = 9
CORRIDOR_MW = 541.4


@pytest.fixture
def committed_portfolio() -> object:
    return SeracExposureSource(repo_root=REPO_ROOT).load(FALLBACK, portfolio_id="trishuli-corridor")


def test_both_sources_satisfy_the_port() -> None:
    assert isinstance(SeracExposureSource(repo_root=REPO_ROOT), ExposureSource)
    assert isinstance(GeoParquetExposureSource(), ExposureSource)


def test_the_committed_copy_matches_the_provenance_it_ships_with() -> None:
    """The fallback is a real slice of serac's export, and says which commit it came from."""
    provenance = json.loads(
        (RISK_FIXTURES / "exposure" / AOI / "provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["source"] == "serac"
    assert provenance["source_repository"] == "github.com/dizzy1900/serac"
    assert len(provenance["source_commit"]) == 40
    assert hashlib.sha256(FALLBACK.read_bytes()).hexdigest() == provenance["sha256"]
    assert "FALLBACK ONLY" in provenance["notes"]


def test_the_portfolio_says_it_came_from_the_fallback(committed_portfolio: object) -> None:
    notes = committed_portfolio.provenance.notes  # type: ignore[attr-defined]
    assert "COMMITTED FALLBACK COPY" in notes
    assert "serac" in notes
    assert committed_portfolio.provenance.sha256  # type: ignore[attr-defined]


def test_every_asset_is_carried_and_the_unvalued_ones_are_counted(
    committed_portfolio: object,
) -> None:
    portfolio = committed_portfolio
    assert len(portfolio.assets) == EXPECTED_ASSETS  # type: ignore[attr-defined]
    valued = [a for a in portfolio.assets if a.value > 0.0]  # type: ignore[attr-defined]
    assert len(valued) == EXPECTED_VALUED
    for asset in portfolio.assets:  # type: ignore[attr-defined]
        assert asset.attributes["value_basis"]
        if asset.value == 0.0:
            assert "no verified replacement-cost basis" in str(asset.attributes["value_basis"])


def test_the_valuation_uses_the_published_cost_figure(committed_portfolio: object) -> None:
    """Total value is capacity times IRENA's published unit cost, to the penny."""
    total = sum(a.value for a in committed_portfolio.assets)  # type: ignore[attr-defined]
    assert total == pytest.approx(CORRIDOR_MW * 1000.0 * CENTRAL_USD_PER_KW, rel=1e-9)


def test_the_interval_around_the_published_figure_is_marked_assumed() -> None:
    money = DEFAULT_BASIS.money(100.0, basis="test")
    assert money.provenance is ModelProvenance.ASSUMED
    assert money.source_refs
    assert "IRENA" in money.source_refs[0]
    assert money.low < money.best < money.high  # type: ignore[operator]


def test_the_portfolio_validates_against_its_published_contract(
    committed_portfolio: object,
) -> None:
    jsonschema.validate(
        committed_portfolio.model_dump(mode="json"),  # type: ignore[attr-defined]
        contracts.schema_for("exposure-portfolio.v0.json"),
    )


def test_a_missing_export_and_no_fallback_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(ENV_VAR, str(tmp_path / "nowhere"))
    source = SeracExposureSource(repo_root=tmp_path)
    with pytest.raises(SeracExportError, match="no committed fallback"):
        source.load()


def test_a_non_point_geometry_is_refused(tmp_path: Path) -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [[85.0, 28.0], [85.1, 28.1]]},
                "properties": {"id": "a-line", "asset_type": "hydropower_plant"},
            }
        ],
    }
    path = tmp_path / "exposed_assets.geojson"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SeracExportError, match="only Point is supported"):
        SeracExposureSource(repo_root=REPO_ROOT).load(path)


# ------------------------------------------------------------------ user import
def _rows() -> list[dict[str, object]]:
    return [
        {
            "id": "plant-a",
            "longitude": 85.1,
            "latitude": 28.0,
            "taxonomy": "hydropower_plant",
            "value": 1.0e8,
            "vs30": 620.0,
        },
        {
            "id": "plant-b",
            "longitude": 85.2,
            "latitude": 28.1,
            "taxonomy": "hydropower_plant",
            "value": 5.0e7,
        },
    ]


def test_a_csv_import_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "portfolio.csv"
    pd.DataFrame(_rows()).to_csv(path, index=False)
    portfolio = GeoParquetExposureSource(currency="USD", price_year=2026).load(
        path, portfolio_id="imported"
    )
    assert [a.id for a in portfolio.assets] == ["plant-a", "plant-b"]
    assert portfolio.assets[0].attributes["vs30"] == 620.0
    assert "assumed reference rock" in str(portfolio.assets[1].attributes["vs30_basis"])
    assert portfolio.provenance.sha256


def test_a_geoparquet_import_reads_point_geometry(tmp_path: Path) -> None:
    frame = geopandas.GeoDataFrame(
        [{k: v for k, v in row.items() if k not in {"longitude", "latitude"}} for row in _rows()],
        geometry=[Point(row["longitude"], row["latitude"]) for row in _rows()],
        crs="EPSG:4326",
    )
    path = tmp_path / "portfolio.parquet"
    frame.to_parquet(path)
    portfolio = GeoParquetExposureSource().load(path, portfolio_id="imported")
    assert portfolio.assets[0].longitude == pytest.approx(85.1)


def test_a_line_geometry_import_is_refused_rather_than_centroided(tmp_path: Path) -> None:
    frame = geopandas.GeoDataFrame(
        [{"id": "a", "taxonomy": "hydropower_plant", "value": 1.0}],
        geometry=[LineString([(85.0, 28.0), (85.1, 28.1)])],
        crs="EPSG:4326",
    )
    path = tmp_path / "lines.parquet"
    frame.to_parquet(path)
    with pytest.raises(ExposureImportError, match="only Point is supported"):
        GeoParquetExposureSource().load(path)


def test_a_missing_required_column_names_it(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    pd.DataFrame([{"id": "a", "longitude": 85.0, "latitude": 28.0}]).to_csv(path, index=False)
    with pytest.raises(ExposureImportError, match="missing required column"):
        GeoParquetExposureSource().load(path)


def test_duplicate_ids_are_refused() -> None:
    with pytest.raises(ValueError, match="duplicate asset ids"):
        ExposureImport(
            portfolio_id="p",
            currency="USD",
            price_year=2026,
            valuation_basis="test",
            assets=(
                {"id": "a", "longitude": 0.0, "latitude": 0.0, "taxonomy": "t", "value": 1.0},
                {"id": "a", "longitude": 0.0, "latitude": 0.0, "taxonomy": "t", "value": 1.0},
            ),  # type: ignore[arg-type]
        )


def test_the_import_schema_is_registered_and_exportable() -> None:
    """Registered in contracts/ and rendered identically from either entry point.

    This started life as the risk engineer's guard that the contract was *not* yet registered, so
    the note asking the architect to register it could not go stale. It is registered now, so the
    guard becomes its opposite: the published file and the module must not drift apart.
    """
    schema = json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["$id"].endswith("exposure-import.v0.json")
    assert "exposure-import.v0.json" in contracts.CONTRACTS
    assert contracts.drift(Path("contracts")) == [], "run `make schema-export`"


def test_a_component_row_needs_a_parent() -> None:
    with pytest.raises(ValueError, match="no parent_id"):
        ExposureImportRow(
            id="ph",
            longitude=85.0,
            latitude=28.0,
            taxonomy="hydropower_plant:powerhouse",
            value=1.0,
            component="powerhouse",
        )


def test_valuation_date_follows_the_cost_basis_price_year(committed_portfolio: object) -> None:
    assert committed_portfolio.valuation_date == datetime(  # type: ignore[attr-defined]
        DEFAULT_BASIS.price_year, 12, 31, tzinfo=UTC
    )
