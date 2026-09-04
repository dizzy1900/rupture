"""The ShakeMap routes: parsing a real ``grid.xml``, and fetching one for a real ComCat event.

``read_grid_xml`` is the path a real event takes into this layer, and until now nothing exercised
it. The document it is tested on here is **assembled in the test from the committed Gorkha
ShakeMap slice** — the XML scaffolding is synthetic, every number in it is the real published
grid's own — and the assertion is that parsing it returns exactly what
:func:`read_slice_csv` returns from the CSV. Nothing is committed as a fixture and no value is
invented.

The fetch tests inject a fetcher, so the offline suite exercises URL selection, provenance and
every failure message without a socket.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.cascade import cases, comcat_shakemap, gorkha
from rupture.adapters.cascade.shakemap import ShakeMapGrid, read_grid_xml
from rupture.domain.common import sha256_hex

GRID_FIELDS = ("LON", "LAT", "PGA", "PGV", "SVEL")


def grid_xml_text(grid: ShakeMapGrid, *, event_id: str, magnitude: float, version: str) -> str:
    """Re-emit a parsed grid as a ShakeMap ``grid.xml`` document, values verbatim."""
    nlon, nlat = grid.longitudes.size, grid.latitudes.size
    header = "\n".join(
        f'<grid_field index="{i + 1}" name="{name}" units="x" />'
        for i, name in enumerate(GRID_FIELDS)
    )
    rows = []
    for j, lat in enumerate(grid.latitudes):
        for i, lon in enumerate(grid.longitudes):
            rows.append(
                f"{lon:.6f} {lat:.6f} {grid.bands['PGA'][j, i]:.6f} "
                f"{grid.bands['PGV'][j, i]:.6f} {grid.bands['SVEL'][j, i]:.6f}"
            )
    return (
        '<?xml version="1.0" encoding="US-ASCII" standalone="yes"?>\n'
        f'<shakemap_grid event_id="{event_id}" shakemap_version="{version}">\n'
        f'<event event_id="{event_id}" magnitude="{magnitude}" depth="8.2" '
        'lat="28.2305" lon="84.7314" />\n'
        f'<grid_specification lon_min="{grid.longitudes.min():.6f}" '
        f'lat_min="{grid.latitudes.min():.6f}" lon_max="{grid.longitudes.max():.6f}" '
        f'lat_max="{grid.latitudes.max():.6f}" nominal_lon_spacing="0.0167" '
        f'nominal_lat_spacing="0.0167" nlon="{nlon}" nlat="{nlat}" />\n'
        f"{header}\n<grid_data>\n" + "\n".join(rows) + "\n</grid_data>\n</shakemap_grid>\n"
    )


@pytest.fixture(scope="module")
def committed_grid(repo_root: Path) -> ShakeMapGrid:
    return gorkha.load_shakemap(repo_root)


@pytest.fixture(scope="module")
def round_tripped(committed_grid: ShakeMapGrid, tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("shakemap") / "grid.xml"
    path.write_text(
        grid_xml_text(
            committed_grid, event_id=gorkha.EVENT_ID, magnitude=gorkha.MAGNITUDE, version="1"
        ),
        encoding="utf-8",
    )
    return path


def test_read_grid_xml_recovers_the_committed_grid_exactly(
    committed_grid: ShakeMapGrid, round_tripped: Path
) -> None:
    parsed = read_grid_xml(round_tripped, source_url="file://test", source_sha256="deadbeef")
    assert parsed.event_id == gorkha.EVENT_ID
    assert parsed.magnitude == pytest.approx(gorkha.MAGNITUDE)
    assert parsed.shakemap_version == "1"
    assert parsed.source_url == "file://test"
    assert parsed.source_sha256 == "deadbeef"
    assert np.allclose(parsed.longitudes, committed_grid.longitudes)
    assert np.allclose(parsed.latitudes, committed_grid.latitudes)
    for band in ("PGA", "PGV", "SVEL"):
        assert np.allclose(parsed.bands[band], committed_grid.bands[band], atol=1e-6)


def test_a_grid_xml_field_matches_the_csv_slices_field(
    committed_grid: ShakeMapGrid, round_tripped: Path
) -> None:
    """The whole point: the real-event route and the committed-slice route agree."""
    parsed = read_grid_xml(round_tripped)
    lons = committed_grid.longitudes[10:20]
    lats = committed_grid.latitudes[10:20]
    from_xml = parsed.ground_motion_field(imt="PGA", lons=lons, lats=lats, scenario_id="x")
    from_csv = committed_grid.ground_motion_field(imt="PGA", lons=lons, lats=lats, scenario_id="x")
    assert np.allclose(from_xml.median(), from_csv.median(), atol=1e-8)


def test_read_grid_xml_refuses_a_document_that_is_not_a_shakemap(tmp_path: Path) -> None:
    path = tmp_path / "not-a-grid.xml"
    path.write_text("<html><body>404</body></html>", encoding="utf-8")
    with pytest.raises(ValueError, match="no <grid_specification>"):
        read_grid_xml(path)


def test_the_grid_xml_route_reaches_the_models_through_the_case_registry(
    round_tripped: Path,
) -> None:
    shaking = cases.from_grid_xml(round_tripped, scenario_id=gorkha.EVENT_ID, stride=8)
    assert shaking.route == cases.SHAKEMAP_GRID_XML
    assert shaking.pgv.imt == "PGV"
    assert shaking.pga is not None
    assert shaking.magnitude == pytest.approx(gorkha.MAGNITUDE)
    assert len(shaking.pgv.sites) > 100


def test_a_stride_below_one_is_refused(round_tripped: Path) -> None:
    with pytest.raises(cases.ShakingUnavailableError, match="stride"):
        cases.from_grid_xml(round_tripped, stride=0)


# ----------------------------------------------------------------- fetch-shakemap, offline
DETAIL = {
    "properties": {
        "mag": 7.8,
        "time": 1429942285000,
        "title": "M 7.8 - Nepal",
        "products": {
            "shakemap": [
                {
                    "properties": {"version": "1"},
                    "contents": {
                        "download/grid.xml": {"url": "https://example.invalid/grid.xml"},
                        "download/info.json": {"url": "https://example.invalid/info.json"},
                    },
                }
            ]
        },
    },
    "geometry": {"coordinates": [84.7314, 28.2305, 8.2]},
}

GRID_BYTES = (
    b'<shakemap_grid event_id="us20002926"><grid_specification nlon="1" nlat="1" /></shakemap_grid>'
)


def fake_fetcher(mapping: dict[str, bytes]) -> comcat_shakemap.Fetcher:
    def fetch(url: str) -> bytes:
        if url not in mapping:
            msg = f"unexpected URL {url}"
            raise AssertionError(msg)
        return mapping[url]

    return fetch


def test_the_product_lookup_picks_the_preferred_grid_xml() -> None:
    product = comcat_shakemap.select_grid_url(DETAIL, event_id="us20002926")
    assert product.grid_url == "https://example.invalid/grid.xml"
    assert product.shakemap_version == "1"
    assert product.magnitude == pytest.approx(7.8)
    assert product.longitude == pytest.approx(84.7314)


def test_an_event_with_no_shakemap_product_fails_loudly() -> None:
    with pytest.raises(comcat_shakemap.ShakeMapFetchError, match="no shakemap product"):
        comcat_shakemap.select_grid_url({"properties": {"products": {}}}, event_id="us0000abcd")


def test_a_shakemap_product_without_a_grid_names_what_it_does_have() -> None:
    product = {"contents": {"download/info.json": {"url": "u"}}}
    detail = {"properties": {"products": {"shakemap": [product]}}}
    with pytest.raises(comcat_shakemap.ShakeMapFetchError, match=r"download/info\.json"):
        comcat_shakemap.select_grid_url(detail, event_id="us0000abcd")


def test_fetch_writes_the_grid_and_its_provenance(tmp_path: Path) -> None:
    fetcher = fake_fetcher(
        {
            comcat_shakemap.DETAIL_URL.format(event_id="us20002926"): json.dumps(DETAIL).encode(),
            "https://example.invalid/grid.xml": GRID_BYTES,
        }
    )
    written = comcat_shakemap.fetch_shakemap("us20002926", tmp_path / "out", fetcher=fetcher)
    assert written["grid"].read_bytes() == GRID_BYTES
    provenance = json.loads(written["provenance"].read_text())
    assert provenance["source_url"] == "https://example.invalid/grid.xml"
    assert provenance["sha256"] == sha256_hex(GRID_BYTES)
    assert provenance["licence"] == "public-domain (USGS)"
    assert provenance["event"]["magnitude"] == pytest.approx(7.8)
    assert provenance["retrieved_at"].endswith("+00:00")
    assert "fetch-shakemap" in provenance["rule"]


def test_a_response_that_is_not_a_grid_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    fetcher = fake_fetcher(
        {
            comcat_shakemap.DETAIL_URL.format(event_id="us20002926"): json.dumps(DETAIL).encode(),
            "https://example.invalid/grid.xml": b"<html>gateway timeout</html>",
        }
    )
    out = tmp_path / "out"
    with pytest.raises(comcat_shakemap.ShakeMapFetchError, match="did not return a ShakeMap"):
        comcat_shakemap.fetch_shakemap("us20002926", out, fetcher=fetcher)
    assert not out.exists()


def test_an_explicit_url_skips_the_product_lookup(tmp_path: Path) -> None:
    fetcher = fake_fetcher({"https://example.invalid/other.xml": GRID_BYTES})
    written = comcat_shakemap.fetch_shakemap(
        "us20002926",
        tmp_path / "out",
        fetcher=fetcher,
        grid_url="https://example.invalid/other.xml",
    )
    provenance = json.loads(written["provenance"].read_text())
    assert provenance["detail_url"] is None
    assert provenance["event"]["magnitude"] is None
