"""Serving a catalogue the repository does not ship.

The modelling code has always handled an arbitrary built catalogue (``rupture aftershock forecast
--catalog <dir> --region <file>``), but the HTTP service could only serve the two committed
validation sequences: there was no way to point it at a built catalogue directory. These tests
build a catalogue directory from the committed Gorkha slice, hand it to the service the way a
deployment would (``RUPTURE_AFTERSHOCK_CATALOGS`` or ``--catalog``), and forecast against it.
"""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rupture.domain import Catalog, Region
from rupture.pipelines.io import save_catalog
from rupture.services.aftershock.forecaster import AftershockForecaster
from rupture.services.aftershock.sequences import SequenceSpec, fits_dir
from rupture.services.aftershock.service import (
    CATALOGS_ENV,
    SequenceSource,
    create_app,
    load_sequences,
    parse_catalog_specs,
)

KEY = "catalog-test-key"
HEADERS = {"X-API-Key": KEY}


@pytest.fixture
def built_catalogue(
    tmp_path: Path, gorkha_catalog: Catalog, nepal_region: Region
) -> SequenceSource:
    """The committed slice written out as a built catalogue directory plus a region file."""
    catalog_dir = tmp_path / "catalog"
    save_catalog(gorkha_catalog, catalog_dir)
    region_path = tmp_path / "region.json"
    region_path.write_text(nepal_region.model_dump_json(indent=2), encoding="utf-8")
    return SequenceSource(id="nepal-live", catalog_dir=catalog_dir, region_path=region_path)


def test_a_built_catalogue_is_servable_over_http(
    built_catalogue: SequenceSource,
    repo_root: Path,
    gorkha: SequenceSpec,
    fast_forecaster: AftershockForecaster,
) -> None:
    source = SequenceSource(
        id=built_catalogue.id,
        catalog_dir=built_catalogue.catalog_dir,
        region_path=built_catalogue.region_path,
        fits_dir=fits_dir(gorkha, repo_root),
    )
    client = TestClient(
        create_app(api_key=KEY, forecaster=fast_forecaster, defaults=False, sources=(source,))
    )
    health = client.get("/healthz").json()
    assert health["sequences"] == ["nepal-live"]
    assert health["fits_loaded"]["nepal-live"]

    body = {
        "sequence": "nepal-live",
        "mainshock_id": gorkha.mainshock.event_id,
        "issue_time": (gorkha.mainshock.origin_time + timedelta(days=1)).isoformat(),
        "horizon": "1d",
        "n_simulations": 1,
    }
    response = client.post("/aftershock/forecast", json=body, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["mainshock_event_id"] == gorkha.mainshock.event_id


def test_the_environment_variable_configures_the_same_thing(
    built_catalogue: SequenceSource, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(
        CATALOGS_ENV,
        f"nepal-live={built_catalogue.catalog_dir},{built_catalogue.region_path}",
    )
    loaded = load_sequences(repo_root, defaults=False)
    assert sorted(loaded) == ["nepal-live"]
    assert loaded["nepal-live"].catalog.events


def test_a_configured_catalogue_can_bring_its_own_fits_directory(
    built_catalogue: SequenceSource, repo_root: Path, gorkha: SequenceSpec
) -> None:
    text = (
        f"nepal-live={built_catalogue.catalog_dir},{built_catalogue.region_path},"
        f"{fits_dir(gorkha, repo_root)}"
    )
    (source,) = parse_catalog_specs(text)
    assert source.fits_dir == fits_dir(gorkha, repo_root)
    assert source.load().current_fits()


def test_several_sequences_are_separated_by_semicolons() -> None:
    sources = parse_catalog_specs("a=/c/a,/r/a.json; b=/c/b,/r/b.json,/f/b")
    assert [s.id for s in sources] == ["a", "b"]
    assert sources[0].fits_dir is None
    assert sources[1].fits_dir == Path("/f/b")


@pytest.mark.parametrize("text", ["nofits", "name=/only-one-path", "name=/a,/b,/c,/d", "=/a,/b"])
def test_a_malformed_entry_refuses_to_start_rather_than_serving_less(text: str) -> None:
    with pytest.raises(ValueError, match=CATALOGS_ENV):
        parse_catalog_specs(text)


def test_no_configuration_is_no_sources() -> None:
    assert parse_catalog_specs(None) == ()
    assert parse_catalog_specs("   ") == ()


def test_a_configured_sequence_replaces_a_committed_one_of_the_same_name(
    built_catalogue: SequenceSource, repo_root: Path, tmp_path: Path
) -> None:
    """A deployment can serve its own, longer Nepal catalogue under the committed name."""
    renamed = SequenceSource(
        id="gorkha",
        catalog_dir=built_catalogue.catalog_dir,
        region_path=built_catalogue.region_path,
    )
    loaded = load_sequences(repo_root, defaults=True, sources=(renamed,), env={})
    assert sorted(loaded) == ["gorkha", "kahramanmaras"]
    assert loaded["gorkha"].fits_store is None
    meta = json.loads((built_catalogue.catalog_dir / "catalog.meta.json").read_text("utf-8"))
    assert loaded["gorkha"].catalog.id == meta["id"]
