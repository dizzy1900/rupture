"""ISC-GEM parser (format only; no fixture obtainable), Scordilis conversions, Mw precedence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rupture.adapters.catalogs import isc_gem
from rupture.domain import MagnitudeRecord, MagnitudeType, Provenance
from rupture.pipelines import magnitudes as mg

# A header line in the documented ISC-GEM layout followed by ONE SYNTHETIC ROW that exists only
# to exercise the column mapping. It is not a catalogue entry and is never presented as data.
SYNTHETIC_ISC_GEM = (
    "# ISC-GEM format test (synthetic row, not a real event)\n"
    "#  date         , lat     , lon     , smajax , sminax , strike , q , depth , unc , q , mw  , unc , q , s , mo     , fac , mo_auth , mpp , mpr , mrr , mrt , mtp , mtt , str1 , dip1 , rake1 , str2 , dip2 , rake2 , type , eventid\n"  # noqa: E501
    "2000-01-01 00:00:00.00, 10.0000, 20.0000, 12.3, 8.1, 45, A, 15.0, 4.0, A, 6.10, 0.10, A, 1, 1.5e+25, 1, GCMT, 0,0,0,0,0,0, 10, 45, 90, 190, 45, 90, ,  9999999\n"  # noqa: E501
)


def test_isc_gem_parser_reads_documented_columns(test_provenance: Provenance) -> None:
    events = isc_gem.parse_isc_gem_csv(SYNTHETIC_ISC_GEM, provenance=test_provenance)
    assert len(events) == 1
    e = events[0]
    assert e.source_event_id == "9999999"
    assert e.origin_time == datetime(2000, 1, 1, tzinfo=UTC)
    assert (e.latitude, e.longitude, e.depth_km) == (10.0, 20.0, 15.0)
    assert e.horizontal_uncertainty_km == 12.3
    assert e.depth_uncertainty_km == 4.0
    assert e.magnitude.type is MagnitudeType.MW
    assert e.magnitude.value == 6.1
    assert e.magnitude.uncertainty == 0.1
    assert e.mw_conversion == "identity:mw"
    assert e.source_catalog == "isc-gem"


def test_isc_gem_requires_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(isc_gem.ENV_VAR, raising=False)
    with pytest.raises(isc_gem.IscGemUnavailableError, match=isc_gem.ENV_VAR):
        isc_gem.configured_path()
    monkeypatch.setenv(isc_gem.ENV_VAR, "/nonexistent/isc-gem.csv")
    with pytest.raises(isc_gem.IscGemUnavailableError, match="does not exist"):
        isc_gem.configured_path()


def test_isc_gem_fixture_mode_reports_absence(fixtures_root: Path, nepal) -> None:  # type: ignore[no-untyped-def]
    """No ISC-GEM fixture is committed (form-gated download, ADR-0005): the source says so."""
    src = isc_gem.IscGemSource(offline_fixtures=fixtures_root)
    with pytest.raises(isc_gem.IscGemUnavailableError, match="form"):
        src.fetch(nepal, datetime(2015, 1, 1, tzinfo=UTC), datetime(2016, 1, 1, tzinfo=UTC))


# ----------------------------------------------------------------- conversions


@pytest.mark.parametrize(
    ("mtype", "value", "expected"),
    [
        (MagnitudeType.MB, 5.0, 0.85 * 5.0 + 1.03),
        (MagnitudeType.MB, 3.5, 0.85 * 3.5 + 1.03),
        (MagnitudeType.MB, 6.2, 0.85 * 6.2 + 1.03),
        (MagnitudeType.MS, 5.0, 0.67 * 5.0 + 2.07),
        (MagnitudeType.MS, 7.0, 0.99 * 7.0 + 0.08),
    ],
)
def test_scordilis_2006_inside_ranges(mtype: MagnitudeType, value: float, expected: float) -> None:
    assert mg.scordilis_2006(mtype, value) == pytest.approx(round(expected, 2), abs=1e-9)


@pytest.mark.parametrize(
    ("mtype", "value"),
    [
        (MagnitudeType.MB, 3.4),
        (MagnitudeType.MB, 6.3),
        (MagnitudeType.MS, 2.9),
        (MagnitudeType.MS, 8.3),
        (MagnitudeType.ML, 4.0),
        (MagnitudeType.MD, 4.0),
        (MagnitudeType.OTHER, 5.2),
    ],
)
def test_no_conversion_outside_ranges_or_for_uncited_scales(
    mtype: MagnitudeType, value: float
) -> None:
    assert mg.scordilis_2006(mtype, value) is None


def _m(source: str, mtype: MagnitudeType, value: float) -> mg.SourcedMagnitude:
    return mg.SourcedMagnitude(source, MagnitudeRecord(value=value, type=mtype))


def test_preferred_mw_precedence_gcmt_first() -> None:
    res = mg.preferred_mw(
        [
            _m("usgs-comcat", MagnitudeType.MWW, 7.8),
            _m("isc", MagnitudeType.MW, 7.88),
            _m("gcmt", MagnitudeType.MWC, 7.88),
            _m("isc", MagnitudeType.MB, 6.1),
        ]
    )
    assert (res.mw, res.conversion) == (7.88, "identity:mwc")


def test_preferred_mw_identity_before_conversion() -> None:
    res = mg.preferred_mw(
        [_m("usgs-comcat", MagnitudeType.MB, 5.0), _m("usgs-comcat", MagnitudeType.MWR, 4.9)]
    )
    assert (res.mw, res.conversion) == (4.9, "identity:mwr")


def test_preferred_mw_converts_mb_when_nothing_better() -> None:
    res = mg.preferred_mw([_m("isc", MagnitudeType.MB, 5.0)])
    assert res.conversion == "scordilis2006:mb"
    assert res.mw == pytest.approx(5.28)


def test_preferred_mw_prefers_ms_over_mb_within_a_source() -> None:
    res = mg.preferred_mw([_m("isc", MagnitudeType.MB, 5.0), _m("isc", MagnitudeType.MS, 5.5)])
    assert res.conversion == "scordilis2006:ms"


def test_preferred_mw_unconvertible_is_none_pair() -> None:
    res = mg.preferred_mw([_m("usgs-comcat", MagnitudeType.ML, 3.0)])
    assert (res.mw, res.conversion) == (None, None)
    assert "no accepted relation" in res.detail
