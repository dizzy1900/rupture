"""The discriminator client: what leaves the tectonic fit, and the accounting for it.

The fixture case is ``us7000tbwb`` — the real ComCat record (``type=landslide``, M 5.2,
2026-08-26, Nepal) already committed under ``data/fixtures/comcat/``. It is reused, not refetched.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rupture.cascade import discriminator
from rupture.domain.catalog import Catalog
from rupture.domain.event import EventType
from rupture.domain.source_type import SourceTypeAssessment
from rupture.validation.cascade import catalog_from_comcat_geojson

FIXTURE = Path("data") / "fixtures" / "comcat" / "nepal-2026-landslide-us7000tbwb.geojson"
EVENT_ID = "us7000tbwb"


@pytest.fixture
def comcat_catalog(repo_root: Path) -> Catalog:
    return catalog_from_comcat_geojson(repo_root / FIXTURE)


def assessment(event_id: str, p: float, **kwargs: object) -> SourceTypeAssessment:
    return SourceTypeAssessment(
        event_id=event_id,
        source_catalog="usgs-comcat",
        assessed_at=datetime(2026, 9, 1, tzinfo=UTC),
        p_mass_movement=p,
        p_tectonic=1.0 - p,
        classifier_id="serac-discriminator",
        classifier_version="0.1.0",
        evidence=("long-period surface-wave energy without a clear P onset",),
        **kwargs,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------ the fixture case
def test_us7000tbwb_is_tagged_landslide_by_the_source_catalogue(comcat_catalog: Catalog) -> None:
    event = next(e for e in comcat_catalog.events if e.source_event_id == EVENT_ID)
    assert event.event_type is EventType.LANDSLIDE
    assert event.magnitude.value == pytest.approx(5.2)


def test_us7000tbwb_is_excluded_from_tectonic_fitting(comcat_catalog: Catalog) -> None:
    tectonic = {e.source_event_id for e in comcat_catalog.earthquakes().events}
    assert EVENT_ID not in tectonic


def test_the_accounting_counts_it_in_the_cascade_layer(comcat_catalog: Catalog) -> None:
    _, accounting = discriminator.apply_assessments(comcat_catalog, ())
    assert accounting.n_already_tagged >= 1
    assert accounting.n_reclassified == 0
    assert accounting.n_excluded_from_tectonic_fit == accounting.n_already_tagged
    rendered = " ".join(accounting.render())
    assert "excluded from tectonic fitting" in rendered


def test_an_assessment_of_an_already_tagged_event_does_not_double_count(
    comcat_catalog: Catalog,
) -> None:
    _, accounting = discriminator.apply_assessments(comcat_catalog, [assessment(EVENT_ID, 0.97)])
    assert accounting.n_assessments_matched == 1
    assert accounting.n_reclassified == 0, "it was already out of the tectonic set"
    assert accounting.n_excluded_from_tectonic_fit == accounting.n_already_tagged


# ------------------------------------------------------------------ retagging
def test_an_earthquake_above_the_threshold_is_retagged(catalog: Catalog) -> None:
    before = catalog.count_by_type()
    updated, accounting = discriminator.apply_assessments(catalog, [assessment("e1", 0.91)])
    after = updated.count_by_type()
    assert accounting.n_reclassified == 1
    assert after[EventType.LANDSLIDE] == before[EventType.LANDSLIDE] + 1
    assert after[EventType.EARTHQUAKE] == before[EventType.EARTHQUAKE] - 1
    assert "e1" not in {e.id for e in updated.earthquakes().events}
    assert updated.notes is not None
    assert "retagged landslide" in updated.notes


def test_an_earthquake_below_the_threshold_is_left_alone(catalog: Catalog) -> None:
    updated, accounting = discriminator.apply_assessments(catalog, [assessment("e1", 0.2)])
    assert accounting.n_reclassified == 0
    assert updated is catalog


def test_retagging_is_one_way(catalog: Catalog) -> None:
    """A low p_mass_movement never pulls a landslide back into the tectonic set."""
    updated, _ = discriminator.apply_assessments(catalog, [assessment("ls", 0.01)])
    event = next(e for e in updated.events if e.id == "ls")
    assert event.event_type is EventType.LANDSLIDE


def test_borderline_assessments_are_reported(catalog: Catalog) -> None:
    _, accounting = discriminator.apply_assessments(catalog, [assessment("e1", 0.52)])
    assert accounting.borderline == ["e1"]
    assert "within" in " ".join(accounting.render())


def test_an_unmatched_assessment_is_reported_not_dropped(catalog: Catalog) -> None:
    _, accounting = discriminator.apply_assessments(catalog, [assessment("not-here", 0.99)])
    assert accounting.n_assessments_unmatched == 1
    assert accounting.unmatched_event_ids == ["not-here"]
    assert "matched no" in " ".join(accounting.render())


def test_events_can_be_addressed_by_their_source_catalogue_id(catalog: Catalog) -> None:
    _, accounting = discriminator.apply_assessments(catalog, [assessment("test:e1", 0.9)])
    assert accounting.n_reclassified == 1


# ------------------------------------------------------------------ file reading
def test_reading_an_export_directory(tmp_path: Path, catalog: Catalog) -> None:
    export = tmp_path / "source-type-assessments"
    export.mkdir()
    (export / "a.json").write_text(json.dumps([assessment("e1", 0.9).model_dump(mode="json")]))
    (export / "b.json").write_text(
        json.dumps({"assessments": [assessment("e2", 0.9).model_dump(mode="json")]})
    )
    updated, accounting = discriminator.apply_from_export(catalog, tmp_path)
    assert accounting.n_assessments_read == 2
    assert accounting.n_reclassified == 2
    assert len(accounting.sources) == 2
    assert {e.id for e in updated.earthquakes().events} == {"e0"}


def test_a_missing_export_is_not_an_error_but_is_reported(tmp_path: Path, catalog: Catalog) -> None:
    updated, accounting = discriminator.apply_from_export(catalog, tmp_path)
    assert updated is catalog
    assert accounting.n_assessments_read == 0
    assert accounting.n_already_tagged == 1


def test_an_invalid_assessment_fails_loudly(tmp_path: Path) -> None:
    """A record rupture cannot read leaves a mass movement in the tectonic fit; refuse it."""
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"event_id": "x", "p_mass_movement": 0.9}))
    with pytest.raises(ValueError, match="validation error"):
        discriminator.read_assessments(bad)


def test_probabilities_that_do_not_sum_to_one_are_refused() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        SourceTypeAssessment(
            event_id="x",
            source_catalog="usgs-comcat",
            assessed_at=datetime(2026, 9, 1, tzinfo=UTC),
            p_mass_movement=0.9,
            p_tectonic=0.9,
            classifier_id="c",
            classifier_version="1",
        )


def test_the_accounting_serialises(comcat_catalog: Catalog) -> None:
    _, accounting = discriminator.apply_assessments(comcat_catalog, ())
    payload = accounting.as_dict()
    assert json.loads(json.dumps(payload))["n_excluded_from_tectonic_fit"] >= 1
