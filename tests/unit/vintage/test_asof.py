"""The second clock: when a record came to say what it says.

`origin_time` says when the earthquake happened. `available_time` says when this description of
it came to exist. A fit at *t* may use an event only if both precede *t*, and every leakage
assertion written before ADR-0064 checked only the first.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from rupture.adapters.forecasting.leakage import (
    LeakageError,
    assert_all_before,
    assert_available_before,
)
from rupture.domain import Catalog, Event, Provenance, VintagePolicy
from rupture.validation._fixture import load_fixture
from tests.unit.conftest import make_event

CUT = datetime(2019, 7, 1, tzinfo=UTC)


def _stamped(
    provenance: Provenance, eid: str, origin: datetime, available: datetime | None
) -> Event:
    return make_event(provenance, eid=eid, when=origin).model_copy(
        update={"available_time": available}
    )


@pytest.fixture
def revised_catalog(provenance: Provenance) -> Catalog:
    """One event of each kind: in time, revised after the cut, and of unknown vintage."""
    return Catalog(
        id="vintage-fixture",
        events=(
            _stamped(provenance, "in-time", CUT - timedelta(days=100), CUT - timedelta(days=90)),
            _stamped(provenance, "revised", CUT - timedelta(days=100), CUT + timedelta(days=400)),
            _stamped(provenance, "unknown", CUT - timedelta(days=100), None),
        ),
        built_at=CUT,
        builder_version="tests",
    )


def test_the_origin_time_assertion_is_blind_to_revision(revised_catalog: Catalog) -> None:
    """The failure ADR-0064 exists for: every event is old enough, one is not old enough *yet*."""
    assert_all_before(revised_catalog, CUT, what="training")  # does not raise


def test_the_vintage_assertion_sees_it(revised_catalog: Catalog) -> None:
    with pytest.raises(LeakageError, match="not provably available"):
        assert_available_before(
            revised_catalog, CUT, what="training", policy=VintagePolicy.EXCLUDE_UNKNOWN
        )


def test_unknown_vintage_is_refused_under_the_strict_policy(revised_catalog: Catalog) -> None:
    """ "We do not know when this value came to exist" is not evidence that it existed in time."""
    with pytest.raises(LeakageError, match="unknown vintage"):
        assert_available_before(
            revised_catalog.as_of(CUT, VintagePolicy.INCLUDE_UNKNOWN).model_copy(
                update={"events": (revised_catalog.events[0], revised_catalog.events[2])}
            ),
            CUT,
            what="training",
            policy=VintagePolicy.EXCLUDE_UNKNOWN,
        )


def test_unknown_vintage_passes_under_the_permissive_policy(revised_catalog: Catalog) -> None:
    kept = revised_catalog.model_copy(
        update={"events": (revised_catalog.events[0], revised_catalog.events[2])}
    )
    assert_available_before(kept, CUT, what="training", policy=VintagePolicy.INCLUDE_UNKNOWN)


@pytest.mark.parametrize(
    ("policy", "expected"),
    [
        (VintagePolicy.EXCLUDE_UNKNOWN, {"in-time"}),
        (VintagePolicy.INCLUDE_UNKNOWN, {"in-time", "unknown"}),
    ],
)
def test_as_of_keeps_what_the_policy_says(
    revised_catalog: Catalog, policy: VintagePolicy, expected: set[str]
) -> None:
    assert {e.id for e in revised_catalog.as_of(CUT, policy).events} == expected


def test_as_of_and_before_are_different_questions(revised_catalog: Catalog) -> None:
    """Every event predates the cut; only one is provably available by it."""
    assert len(revised_catalog.before(CUT)) == 3
    assert len(revised_catalog.as_of(CUT, VintagePolicy.EXCLUDE_UNKNOWN)) == 1


def test_the_summary_counts_what_it_says_it_counts(revised_catalog: Catalog) -> None:
    s = revised_catalog.vintage_summary(CUT)
    assert s.n_events == 3
    assert s.n_with_available_time == 2
    assert s.n_revised_after == 1
    assert s.n_available_by == 1
    assert s.coverage == pytest.approx(2 / 3)
    assert s.exposed_fraction == pytest.approx(1 / 3)


def test_a_catalogue_with_no_vintage_reports_none_rather_than_zero(provenance: Provenance) -> None:
    cat = Catalog(
        id="bare",
        events=(make_event(provenance, eid="a", when=CUT - timedelta(days=1)),),
        built_at=CUT,
        builder_version="tests",
    )
    s = cat.vintage_summary()
    assert s.coverage == 0.0
    assert s.lag_days_median is None
    assert s.exposed_fraction is None
    assert cat.n_events_without_vintage() == 1


# ---------------------------------------------------------------- the real fixture


@pytest.fixture(scope="module")
def fixture_catalog() -> Catalog:
    return load_fixture(Path.cwd())[0]


def test_the_comcat_adapter_reads_the_revision_stamp(fixture_catalog: Catalog) -> None:
    assert fixture_catalog.vintage_summary().coverage == 1.0


def test_every_fixture_record_was_revised_after_its_own_origin(fixture_catalog: Catalog) -> None:
    """Not a hypothetical: the median record is 192 days younger than its earthquake."""
    summary = fixture_catalog.vintage_summary()
    assert summary.lag_days_median is not None
    assert summary.lag_days_median > 30.0


def test_a_third_of_the_2019_training_slice_is_of_unproven_vintage(
    fixture_catalog: Catalog,
) -> None:
    """The measurement `validate-asof` reports, pinned so a change to it is deliberate."""
    training = fixture_catalog.earthquakes().before(CUT).at_least(3.0)
    summary = training.vintage_summary(CUT)
    assert summary.n_events == 217
    assert summary.n_revised_after == 69
    assert summary.exposed_fraction == pytest.approx(69 / 217)
    assert_all_before(training, CUT, what="training")  # the old assertion is content
    with pytest.raises(LeakageError):
        assert_available_before(
            training, CUT, what="training", policy=VintagePolicy.EXCLUDE_UNKNOWN
        )
