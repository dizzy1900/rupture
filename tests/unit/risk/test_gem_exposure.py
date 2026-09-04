"""The GEM exposure adapter, and the licence position it exists to make explicit.

No GEM data is committed to this repository (CC BY-NC-SA 4.0), so these tests exercise the
adapter against files the test writes itself. That is the honest shape of an offline test for an
adapter whose real input rupture is not permitted to redistribute: it tests rupture's parsing,
never GEM's numbers.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rupture.adapters.exposure import GemExposureError, GemExposureSource
from rupture.adapters.exposure.gem_global import fetch_summary, read_summary
from rupture.adapters.vulnerability import HydropowerVulnerability
from rupture.ports.exposure import ExposureSource

HEADER = "id,lon,lat,taxonomy,number,structural,night\n"
ROWS = (
    "NPL_BAG_1,85.31,27.71,MUR+CLBRS/LWAL/HBET:1/RES,120,4500000,340\n"
    "NPL_BAG_2,85.33,27.73,CR/LFINF+DNO/H:4/RES,18,9200000,96\n"
)


def _export(tmp_path: Path, text: str = HEADER + ROWS) -> Path:
    path = tmp_path / "Exposure_NPL.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_adapter_satisfies_the_exposure_port() -> None:
    assert isinstance(GemExposureSource(), ExposureSource)


def test_no_gem_data_is_committed_to_this_repository() -> None:
    """The licence position, asserted rather than only written down."""
    root = Path(__file__).resolve().parents[3]
    for directory in (root / "tests" / "fixtures", root / "data" / "fixtures"):
        if not directory.is_dir():
            continue
        offenders = [
            p for p in directory.rglob("*") if p.is_file() and "gem_exposure" in p.name.lower()
        ]
        assert offenders == []


def test_load_without_a_path_says_why_there_is_no_bundled_copy() -> None:
    with pytest.raises(GemExposureError, match="not an open licence"):
        GemExposureSource().load()


def test_a_missing_file_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(GemExposureError, match="no GEM exposure export"):
        GemExposureSource().load(tmp_path / "absent.csv")


def test_an_export_missing_the_required_columns_names_them(tmp_path: Path) -> None:
    path = _export(tmp_path, "id,taxonomy\nA,MUR\n")
    with pytest.raises(GemExposureError, match="missing the OpenQuake exposure columns"):
        GemExposureSource().load(path)


def test_an_export_with_no_value_column_refuses_to_guess(tmp_path: Path) -> None:
    path = _export(tmp_path, "id,lon,lat,taxonomy,number\nA,85.0,28.0,MUR,3\n")
    with pytest.raises(GemExposureError, match="rather than having rupture guess"):
        GemExposureSource().load(path)


def test_a_portfolio_carries_gem_taxonomies_verbatim_and_the_licence(tmp_path: Path) -> None:
    portfolio = GemExposureSource().load(_export(tmp_path), portfolio_id="npl-bagmati")
    assert portfolio.id == "npl-bagmati"
    assert [a.taxonomy for a in portfolio.assets] == [
        "MUR+CLBRS/LWAL/HBET:1/RES",
        "CR/LFINF+DNO/H:4/RES",
    ]
    assert [a.value for a in portfolio.assets] == [4500000.0, 9200000.0]
    assert [a.occupants for a in portfolio.assets] == [340.0, 96.0]
    assert portfolio.assets[0].attributes["number"] == 120
    assert portfolio.provenance.licence == "CC-BY-NC-SA-4.0"
    assert portfolio.provenance.sha256
    assert "does not redistribute" in (portfolio.provenance.notes or "")


def test_every_gem_asset_is_reported_unmodelled_with_the_reason(tmp_path: Path) -> None:
    """rupture ships no building fragility, and a GEM portfolio must say so, not price as zero."""
    portfolio = GemExposureSource().load(_export(tmp_path))
    coverage = HydropowerVulnerability().coverage(portfolio)
    assert coverage.modelled == ()
    assert len(coverage.unmodelled) == len(portfolio.assets)
    assert all("no damage model for taxonomy" in reason for _, reason in coverage.unmodelled)


def test_a_summary_table_with_coordinates_is_redirected(tmp_path: Path) -> None:
    with pytest.raises(GemExposureError, match="disaggregated export"):
        read_summary(_export(tmp_path))


def test_fetch_summary_refuses_a_table_that_is_not_public() -> None:
    with pytest.raises(GemExposureError, match="public summary tables"):
        fetch_summary(
            region="South_Asia",
            country="Nepal",
            table="Exposure_Disaggregated.csv",
            out_dir=Path("/tmp"),
        )
