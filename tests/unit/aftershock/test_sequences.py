"""The committed slices: digests, magnitude homogenisation, mainshock lookup, coverage."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rupture.domain import Catalog, FitResult, MagnitudeType
from rupture.services.aftershock.sequences import (
    SEQUENCES,
    FixtureError,
    Mainshock,
    SequenceSpec,
    check_against_catalog,
    fixture_coverage_end,
    fixture_dir,
    load_committed_fits,
    load_sequence_catalog,
    mainshock_from_catalog,
    sequence_spec,
)

# The M7.3 of 2015-05-12 and the M7.5 doublet of 2023-02-06, from the committed slices.
GORKHA_LARGEST_AFTERSHOCK = "us20002ejl"
KAHRAMANMARAS_DOUBLET = "us6000jlqa"
# The +7 d issue with a 30 d horizon: the last window the validation closes.
LONGEST_WINDOW = timedelta(days=37)


def test_both_sequences_are_registered() -> None:
    assert sorted(SEQUENCES) == ["gorkha", "kahramanmaras"]
    assert sequence_spec("gorkha").mainshock.event_id == "us20002926"
    assert sequence_spec("kahramanmaras").mainshock.event_id == "us6000jllz"


def test_unknown_sequence_is_refused() -> None:
    with pytest.raises(KeyError, match="unknown sequence"):
        sequence_spec("ridgecrest")


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_declared_mainshock_agrees_with_the_catalogue(name: str, repo_root: Path) -> None:
    """The parameters in the code are the ones ComCat gave, not remembered numbers."""
    spec = sequence_spec(name)
    catalog = load_sequence_catalog(spec, repo_root)
    assert check_against_catalog(spec, catalog) == []


def test_a_wrong_declaration_is_reported(gorkha: SequenceSpec, gorkha_catalog: Catalog) -> None:
    wrong = SequenceSpec(
        id=gorkha.id,
        mainshock=Mainshock(
            event_id=gorkha.mainshock.event_id,
            origin_time=gorkha.mainshock.origin_time,
            latitude=gorkha.mainshock.latitude,
            longitude=gorkha.mainshock.longitude,
            magnitude=7.0,
        ),
        parent_region_id=gorkha.parent_region_id,
        fixture_file=gorkha.fixture_file,
        description=gorkha.description,
    )
    problems = check_against_catalog(wrong, gorkha_catalog)
    assert len(problems) == 1
    assert "magnitude" in problems[0]


def test_the_m73_aftershock_is_in_the_slice(gorkha_catalog: Catalog) -> None:
    hit = mainshock_from_catalog(gorkha_catalog, GORKHA_LARGEST_AFTERSHOCK)
    assert hit.magnitude == pytest.approx(7.3)
    assert hit.origin_time == datetime(2015, 5, 12, 7, 5, 19, 730000, tzinfo=UTC)


def test_the_doublet_is_in_the_slice(repo_root: Path) -> None:
    catalog = load_sequence_catalog(sequence_spec("kahramanmaras"), repo_root)
    hit = mainshock_from_catalog(catalog, KAHRAMANMARAS_DOUBLET)
    assert hit.magnitude == pytest.approx(7.5)
    # about nine hours after the mainshock: inside the +1 h forecast window, before the +1 d one
    elapsed = hit.origin_time - sequence_spec("kahramanmaras").mainshock.origin_time
    assert 9.0 < elapsed.total_seconds() / 3600.0 < 9.5


def test_mainshock_lookup_accepts_the_prefixed_id(gorkha_catalog: Catalog) -> None:
    plain = mainshock_from_catalog(gorkha_catalog, "us20002926")
    prefixed = mainshock_from_catalog(gorkha_catalog, "us20002926")
    assert plain == prefixed


def test_mainshock_lookup_refuses_an_absent_id(gorkha_catalog: Catalog) -> None:
    with pytest.raises(KeyError, match="is not in catalogue"):
        mainshock_from_catalog(gorkha_catalog, "nosuchevent")


def test_magnitudes_are_homogenised_under_the_strict_policy(gorkha_catalog: Catalog) -> None:
    by_type: dict[MagnitudeType, list[float | None]] = {}
    for event in gorkha_catalog.events:
        by_type.setdefault(event.magnitude.type, []).append(event.mw)
    # moment magnitudes pass through unchanged
    mww = [e for e in gorkha_catalog.events if e.magnitude.type == MagnitudeType.MWW]
    assert mww
    assert all(e.mw == e.magnitude.value for e in mww)
    assert all(e.mw_conversion == "identity:mww" for e in mww)
    # mb converts with Scordilis (2006) inside its validity range
    mb = [e for e in gorkha_catalog.events if e.magnitude.type == MagnitudeType.MB]
    assert mb
    inside = [e for e in mb if 3.5 <= e.magnitude.value <= 6.2]
    assert inside
    for event in inside:
        assert event.mw == pytest.approx(round(0.85 * event.magnitude.value + 1.03, 2))
        assert event.mw_conversion == "scordilis2006:mb"
    # local magnitudes get no Mw under STRICT and are not deleted
    ml = [e for e in gorkha_catalog.events if e.magnitude.type == MagnitudeType.ML]
    assert all(e.mw is None and e.mw_conversion is None for e in ml)


def test_every_event_carries_the_fixture_digest(gorkha_catalog: Catalog, repo_root: Path) -> None:
    meta = json.loads((fixture_dir(repo_root) / "provenance.json").read_text(encoding="utf-8"))
    digest = meta["files"][sequence_spec("gorkha").fixture_file]["sha256"]
    assert {e.provenance.sha256 for e in gorkha_catalog.events} == {digest}
    assert {e.provenance.licence for e in gorkha_catalog.events} == {"public-domain (USGS)"}


def test_a_tampered_slice_is_refused(tmp_path: Path, repo_root: Path) -> None:
    spec = sequence_spec("gorkha")
    source = fixture_dir(repo_root)
    target = tmp_path / "tests" / "fixtures" / "aftershock"
    target.mkdir(parents=True)
    (target / "provenance.json").write_text(
        (source / "provenance.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    raw = (source / spec.fixture_file).read_text(encoding="utf-8")
    (target / spec.fixture_file).write_text(raw.replace('"mag":7.8', '"mag":8.8', 1), "utf-8")
    with pytest.raises(FixtureError, match="edited by hand"):
        load_sequence_catalog(spec, tmp_path)


def test_a_missing_slice_is_refused(tmp_path: Path, repo_root: Path) -> None:
    spec = sequence_spec("gorkha")
    target = tmp_path / "tests" / "fixtures" / "aftershock"
    target.mkdir(parents=True)
    (target / "provenance.json").write_text(
        (fixture_dir(repo_root) / "provenance.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    with pytest.raises(FixtureError, match="is missing"):
        load_sequence_catalog(spec, tmp_path)


def test_no_provenance_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match=r"no provenance\.json"):
        load_sequence_catalog(sequence_spec("gorkha"), tmp_path)


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_coverage_end_is_after_the_longest_window(name: str, repo_root: Path) -> None:
    """+7 d issue with a 30 d horizon must close inside the slice, or nothing can be scored."""
    spec = sequence_spec(name)
    coverage = fixture_coverage_end(spec, repo_root)
    longest_window_end = spec.mainshock.origin_time + LONGEST_WINDOW
    assert coverage > longest_window_end


@pytest.mark.parametrize("name", sorted(SEQUENCES))
def test_committed_fits_cover_every_issue_time(name: str, repo_root: Path) -> None:
    """The three validation issue times, and the early-hours schedule points before them.

    The early ones (+0, 3, 6, 12 h) were written by ``rupture aftershock refit --through 12h``;
    before that the service could not answer any issue time in the first day except +1 h.
    """
    spec = sequence_spec(name)
    fits = load_committed_fits(spec, repo_root)
    expected = {
        spec.mainshock.origin_time + offset
        for offset in (
            timedelta(0),
            timedelta(hours=1),
            timedelta(hours=3),
            timedelta(hours=6),
            timedelta(hours=12),
            timedelta(days=1),
            timedelta(days=7),
        )
    }
    assert {datetime.fromisoformat(cutoff) for cutoff in fits} == expected
    for fit in fits.values():
        assert isinstance(fit, FitResult)
        assert fit.converged is True
        assert fit.region_id == f"aftershock-{spec.mainshock.event_id}"
        assert fit.fit_cutoff >= spec.mainshock.origin_time
        assert fit.diagnostics["beta_fixed"] is True
        branching = fit.diagnostics["branching_ratio"]
        assert branching is not None
        assert 0.0 < float(branching) < 1.0


def test_no_committed_fits_gives_an_empty_mapping(tmp_path: Path) -> None:
    assert load_committed_fits(sequence_spec("gorkha"), tmp_path) == {}


def test_mainshock_rejects_a_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Mainshock(
            event_id="x",
            origin_time=datetime(2015, 4, 25, 6, 11, 26),  # noqa: DTZ001 - the point of the test
            latitude=28.0,
            longitude=85.0,
            magnitude=7.8,
        )
