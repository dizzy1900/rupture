"""ISC FDSN text parser and GCMT NDK parser on the committed real slices."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from rupture.adapters.catalogs import gcmt, isc
from rupture.domain import EventType, MagnitudeType, Provenance
from tests.unit.catalogs.conftest import fixture_file

# ---------------------------------------------------------------------------- ISC


def test_isc_gorkha_week_parses() -> None:
    f = fixture_file("isc", "gorkha-2015-7d-m4.txt")
    events = isc.parse_isc_text(f.content, provenance=f.provenance)
    data_rows = [ln for ln in f.content.decode().splitlines() if ln and not ln.startswith("#")]
    assert len(events) == len(data_rows)
    main = next(e for e in events if e.source_event_id == "607208674")
    assert main.origin_time == datetime(2015, 4, 25, 6, 11, 26, 634000, tzinfo=UTC)
    assert main.magnitude.type is MagnitudeType.MW
    assert main.magnitude.agency == "GCMT"
    assert main.magnitude.value == 7.88
    assert main.mw_conversion == "identity:mw"
    assert main.depth_km == 13.4
    assert main.event_type is EventType.EARTHQUAKE
    assert main.provenance.sha256 == f.provenance.sha256


def test_isc_types_are_normalised_and_raw_kept() -> None:
    f = fixture_file("isc", "gorkha-2015-7d-m4.txt")
    events = isc.parse_isc_text(f.content, provenance=f.provenance)
    raw_types = {e.magnitude.raw_type for e in events}
    assert "mb" in raw_types
    mb1 = [e for e in events if e.magnitude.raw_type == "mb1"]
    assert mb1
    assert all(e.magnitude.type is MagnitudeType.OTHER for e in mb1)
    assert all(e.mw is None for e in mb1)


def test_isc_rows_before_header_raise(test_provenance: Provenance) -> None:
    with pytest.raises(ValueError, match="header"):
        isc.parse_isc_text(
            "1|2015-01-01T00:00:00|0|0|10|ISC|ISC|ISC|1|mb|4.0|ISC|x|earthquake",
            provenance=test_provenance,
        )


def test_year_windows_split_at_new_year() -> None:
    w = isc.year_windows(datetime(2014, 6, 1, tzinfo=UTC), datetime(2016, 3, 1, tzinfo=UTC))
    assert [(a.year, b.year) for a, b in w] == [(2014, 2015), (2015, 2016), (2016, 2016)]
    assert w[-1][1] == datetime(2016, 3, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("earthquake", EventType.EARTHQUAKE),
        ("", EventType.EARTHQUAKE),
        ("known explosion", EventType.EXPLOSION),
        ("landslide", EventType.LANDSLIDE),
        ("rock burst", EventType.OTHER),
    ],
)
def test_isc_event_type_mapping(raw: str, expected: EventType) -> None:
    assert isc.map_event_type(raw) is expected


# --------------------------------------------------------------------------- GCMT


def test_gcmt_april_2015_parses_all_records() -> None:
    f = fixture_file("gcmt", "apr15.ndk")
    events = gcmt.parse_ndk(f.content, provenance=f.provenance)
    n_lines = len([ln for ln in f.content.decode().splitlines() if ln.strip()])
    assert len(events) == n_lines // 5
    g = next(e for e in events if e.source_event_id == "C201504250611A")
    # centroid values from line 3; Mw from the scalar moment 8.386e27 dyne-cm
    assert (g.latitude, g.longitude, g.depth_km) == (27.91, 85.33, 12.0)
    assert g.origin_time == datetime(2015, 4, 25, 6, 11, 26, 300000, tzinfo=UTC).replace(
        second=58, microsecond=600000
    )
    assert g.mw == 7.88
    assert g.magnitude.type is MagnitudeType.MWC
    assert g.mw_conversion == "identity:mwc"
    assert g.other_magnitudes[0].type is MagnitudeType.MS
    assert g.other_magnitudes[0].value == 7.8
    ref = gcmt.reference_hypocentre(g)
    assert ref is not None
    assert ref[0] == datetime(2015, 4, 25, 6, 11, 26, 300000, tzinfo=UTC)
    assert ref[1:] == (28.15, 84.71)


def test_mw_from_moment_is_hanks_kanamori() -> None:
    assert gcmt.mw_from_moment(1e27) == pytest.approx(7.27, abs=0.005)
    assert gcmt.mw_from_moment(8.386e27) == 7.88
    with pytest.raises(ValueError, match="positive"):
        gcmt.mw_from_moment(0.0)


def test_ndk_record_count_must_be_multiple_of_five(test_provenance: Provenance) -> None:
    f = fixture_file("gcmt", "apr15.ndk")
    lines = f.content.decode().splitlines()[:7]
    with pytest.raises(gcmt.NdkFormatError, match="multiple"):
        gcmt.parse_ndk("\n".join(lines), provenance=test_provenance)


def test_gcmt_matches_obspy_reader_on_the_same_slice() -> None:
    """Cross-check the in-house parser against obspy's NDK reader (offline, ADR-0006)."""
    obspy = pytest.importorskip("obspy")
    f = fixture_file("gcmt", "may15.ndk")
    ours = gcmt.parse_ndk(f.content, provenance=f.provenance)
    theirs = obspy.read_events(str(f.path), format="NDK")
    assert len(ours) == len(theirs)
    by_name = {e.source_event_id: e for e in ours}
    for ev in theirs:
        name = next(d.text for d in ev.event_descriptions if d.type == "earthquake name")
        assert name in by_name
        mine = by_name[name]
        assert abs(mine.mw - ev.magnitudes[0].mag) <= 0.011
        centroid = ev.preferred_origin() or ev.origins[-1]
        assert mine.latitude == pytest.approx(centroid.latitude, abs=1e-6)
        assert mine.longitude == pytest.approx(centroid.longitude, abs=1e-6)


def test_gcmt_month_helpers() -> None:
    assert gcmt.monthly_file_path(2021, 1) == "NEW_MONTHLY/2021/jan21.ndk"
    assert gcmt.monthly_file_path(2026, 4) == "NEW_MONTHLY/2026/apr26.ndk"
    months = gcmt.months_between(
        datetime(2020, 11, 15, tzinfo=UTC), datetime(2021, 2, 1, tzinfo=UTC)
    )
    assert months == [(2020, 11), (2020, 12), (2021, 1)]
