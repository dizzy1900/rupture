"""ETAS-I: the STAI completeness curve, and the adapter switch that feeds it to the package.

Two halves. The first pins the shape of Mc(t) — decay, floor, scaling with trigger size — against
an independent brute-force implementation, because the fast path in
:func:`~rupture.domain.completeness.stai_mc_current` prunes triggers and a pruning bug is
invisible in the output. The second pins the adapter's opt-in: plain ETAS must be untouched by the
existence of this feature, and ETAS-I must emit a ``mc_current`` column and an ``m_ref`` the
package will accept rather than silently repair.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from rupture.adapters.forecasting.etas_mizrahi import MizrahiETAS, save_fit
from rupture.domain import (
    HELMSTETTER_2006,
    Catalog,
    FitResult,
    Provenance,
    Region,
    StaiCoefficients,
    stai_mc,
    stai_mc_current,
)
from tests.unit.conftest import make_event
from tests.unit.forecasting.conftest import FIT_CUTOFF

MC = 3.5
"""The higher cut of ``test_etas_log_likelihood``: 61 training events, so a fit takes seconds."""


def _brute_force_mc_current(
    days: np.ndarray, magnitudes: np.ndarray, background_mc: float, c: StaiCoefficients
) -> np.ndarray:
    """The quadratic definition, written out. Independent of the pruned implementation."""
    out = np.full(days.size, background_mc, dtype=float)
    for i in range(days.size):
        for j in range(days.size):
            if days[j] < days[i]:
                raw = magnitudes[j] - c.offset - c.decay * np.log10(days[i] - days[j])
                out[i] = max(out[i], min(raw, magnitudes[j]))
    return np.maximum(out, background_mc)


# --------------------------------------------------------------------------- the curve
def test_the_curve_decays_with_time_and_floors_at_background() -> None:
    days = np.array([1e-3, 1e-2, 1e-1, 1.0, 10.0, 100.0])
    mc = stai_mc(7.0, days, background_mc=3.0)
    assert (mc[:-1] >= mc[1:]).all()
    assert mc[0] > mc[-1]
    assert mc.min() == pytest.approx(3.0)
    # Mm - 4.5 - 0.75*log10(1) = 2.5 at one day, which is under the floor, so the floor wins.
    assert mc[3] == pytest.approx(3.0)
    # At 0.01 d the curve is 7.0 - 4.5 + 1.5 = 4.0, well clear of it.
    assert mc[1] == pytest.approx(4.0)


def test_a_bigger_trigger_raises_completeness_further() -> None:
    at = np.array([0.01])
    small = stai_mc(5.0, at, background_mc=1.0)
    large = stai_mc(7.0, at, background_mc=1.0)
    assert large[0] - small[0] == pytest.approx(2.0)


def test_the_curve_never_exceeds_the_trigger_magnitude() -> None:
    """Otherwise a timestamp collision would make the threshold infinite, and nothing detectable."""
    tiny = np.array([1e-12, 1e-9, 1e-6])
    assert (stai_mc(6.0, tiny, background_mc=3.0) <= 6.0).all()


def test_a_trigger_does_not_precede_itself() -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        stai_mc(6.0, np.array([0.0]), background_mc=3.0)


def test_coefficients_are_declared_not_hidden() -> None:
    assert "Helmstetter" in HELMSTETTER_2006.citation
    assert HELMSTETTER_2006.offset == 4.5
    assert HELMSTETTER_2006.decay == 0.75
    with pytest.raises(ValueError, match="citation"):
        StaiCoefficients(offset=4.5, decay=0.75, citation="")


def test_a_different_law_gives_a_different_curve() -> None:
    gentler = StaiCoefficients(offset=4.5, decay=0.25, citation="hypothetical, for this test")
    at = np.array([0.01])
    assert (
        stai_mc(7.0, at, background_mc=1.0, coefficients=gentler)[0]
        < stai_mc(7.0, at, background_mc=1.0)[0]
    )


# --------------------------------------------------------------------------- mc_current
def test_no_trigger_means_background_everywhere() -> None:
    assert stai_mc_current([], [], background_mc=3.0).tolist() == []
    assert stai_mc_current([10.0], [7.0], background_mc=3.0).tolist() == [3.0]
    # Widely separated small events: each expires long before the next one.
    days = np.arange(0.0, 10.0)
    out = stai_mc_current(days, np.full(10, 3.2), background_mc=3.0)
    assert out == pytest.approx(np.full(10, 3.0))


def test_a_mainshock_raises_completeness_for_the_events_that_follow_it() -> None:
    days = np.array([0.0, 1e-4, 1e-2, 1.0])
    mags = np.array([7.0, 3.0, 3.0, 3.0])
    out = stai_mc_current(days, mags, background_mc=3.0)
    assert out[0] == pytest.approx(3.0)  # nothing precedes the mainshock
    assert out[1] > out[2] > 3.0  # the threshold decays
    assert out[3] == pytest.approx(3.0)  # and is back to background a day later


def test_the_pruned_implementation_matches_the_quadratic_definition() -> None:
    """The fast path drops triggers two ways (expiry, domination); both must be exact."""
    rng = np.random.default_rng(20260910)
    for _ in range(25):
        n = int(rng.integers(1, 150))
        # Rounded times deliberately collide, which is where the pruning is easiest to get wrong.
        days = np.round(rng.random(n) * 2.0, 3)
        mags = np.round(rng.random(n) * 4.0 + 1.0, 1)
        got = stai_mc_current(days, mags, background_mc=1.0)
        want = _brute_force_mc_current(days, mags, 1.0, HELMSTETTER_2006)
        assert got == pytest.approx(want)


def test_the_result_comes_back_in_the_order_it_was_given() -> None:
    days = np.array([5.0, 0.0, 0.001, 2.0])
    mags = np.array([3.0, 7.0, 3.0, 3.0])
    out = stai_mc_current(days, mags, background_mc=3.0)
    order = np.argsort(days, kind="stable")
    sorted_out = stai_mc_current(days[order], mags[order], background_mc=3.0)
    assert out[order] == pytest.approx(sorted_out)


def test_mismatched_inputs_are_refused() -> None:
    with pytest.raises(ValueError, match="same length"):
        stai_mc_current([1.0, 2.0], [3.0], background_mc=3.0)


# --------------------------------------------------------------------------- the adapter
def _sequence(provenance: Provenance) -> Catalog:
    """A M6.5 followed by twenty events at one-minute spacing: STAI territory."""
    start = datetime(2019, 1, 1, tzinfo=UTC)
    events = [make_event(provenance, eid="main", when=start, mw=6.5)]
    events += [
        make_event(provenance, eid=f"as{i}", when=start + timedelta(minutes=i), mw=3.4)
        for i in range(1, 21)
    ]
    return Catalog(
        id="stai-sequence",
        region_id="california-fixture",
        events=tuple(events),
        sources=("test",),
        built_at=start,
        builder_version="test",
    )


def _metadata_for(model: MizrahiETAS, catalog: Catalog, region: Region, mc: float) -> dict:
    start = datetime(2018, 12, 1, tzinfo=UTC)
    # The test needs the exact configuration a fit would use, so it calls the private builder.
    return model._metadata(
        catalog,
        region,
        mc,
        auxiliary_start=start,
        timewindow_start=start + timedelta(days=15),
        timewindow_end=datetime(2019, 2, 1, tzinfo=UTC),
        name="test",
    )


def test_plain_etas_is_the_default_and_is_untouched(provenance: Provenance, region: Region) -> None:
    model = MizrahiETAS(auxiliary_years=0.5)
    assert model.incompleteness is None
    assert model.model_id == "etas-mizrahi"
    metadata = _metadata_for(model, _sequence(provenance), region, 3.0)
    assert metadata["mc"] == 3.0
    assert "m_ref" not in metadata
    assert "mc_current" not in metadata["catalog"].columns


def test_etas_i_emits_a_valid_mc_current_and_m_ref(provenance: Provenance, region: Region) -> None:
    model = MizrahiETAS(auxiliary_years=0.5, incompleteness=HELMSTETTER_2006)
    assert model.model_id == "etas-i-mizrahi"
    metadata = _metadata_for(model, _sequence(provenance), region, 3.0)

    assert metadata["mc"] == "var"
    assert metadata["m_ref"] == 3.0
    frame = metadata["catalog"]
    values = frame["mc_current"].to_numpy(dtype=float)
    # The package lowers m_ref behind the caller's back if any mc_current sits below it, which
    # would silently change the reference magnitude the fitted parameters are expressed in.
    assert values.min() >= metadata["m_ref"] - 1e-9
    # ...and it warns about "rounding issues" unless mc_current lies on the delta_m grid.
    steps = values / region.magnitude_bin_width
    on_grid = np.abs(steps - np.round(steps)) < 1e-6
    assert on_grid.all()
    assert (values > 3.0).any(), "the M6.5 must raise the threshold for its own aftershocks"
    assert values[0] == pytest.approx(3.0), "nothing precedes the mainshock"


def test_the_two_models_cannot_be_confused_for_one_another(
    committed_fit: FitResult, region: Region
) -> None:
    etas_i = MizrahiETAS(auxiliary_years=0.5, incompleteness=HELMSTETTER_2006)
    with pytest.raises(ValueError, match="etas-i-mizrahi"):
        etas_i.load_fit(committed_fit, region)


def test_etas_i_refuses_to_issue_rather_than_issue_a_plain_etas_forecast(
    region: Region, fixture_catalog: Catalog
) -> None:
    model = MizrahiETAS(auxiliary_years=0.5, incompleteness=HELMSTETTER_2006)
    history = fixture_catalog.earthquakes().before(FIT_CUTOFF).at_least(3.0)
    with pytest.raises(NotImplementedError, match="ADR-0066"):
        model.forecast(history, FIT_CUTOFF, timedelta(days=30))


def test_on_the_committed_fixture_window_etas_i_reduces_exactly_to_plain_etas(
    fixture_catalog: Catalog, region: Region
) -> None:
    """The fixture's training window ends before Ridgecrest, so the STAI curve never bites.

    That makes it the sharpest available check that the switch is inert when it should be: the
    same catalogue, the same EM loop, and parameters that must agree to the last bit. It is also
    the honest reading of this fixture — ETAS-I has nothing to measure on it.
    """
    etas_i = MizrahiETAS(auxiliary_years=0.5, incompleteness=HELMSTETTER_2006)
    plain = MizrahiETAS(auxiliary_years=0.5)
    fit_i = etas_i.fit(fixture_catalog, region, FIT_CUTOFF, mc=MC)
    fit_p = plain.fit(fixture_catalog, region, FIT_CUTOFF, mc=MC)

    assert fit_i.model_id == "etas-i-mizrahi"
    assert fit_p.model_id == "etas-mizrahi"
    assert fit_i.converged
    assert fit_p.converged
    assert fit_i.parameters == fit_p.parameters
    assert fit_i.diagnostics["n_target_events"] == fit_p.diagnostics["n_target_events"]

    inc = fit_i.diagnostics["incompleteness"]
    assert inc["m_ref"] == MC
    assert inc["n_events_above_background_mc"] == 0
    assert "Helmstetter" in inc["coefficients"]["citation"]
    assert "incompleteness" not in fit_p.diagnostics


def test_an_etas_i_fit_cannot_overwrite_a_plain_etas_baseline(
    baselines_with_committed_fit: Path, committed_fit: FitResult
) -> None:
    """``fit_dir`` keys on the region alone, so the two models resolve to one directory."""
    forged = committed_fit.model_copy(update={"model_id": "etas-i-mizrahi"})
    with pytest.raises(ValueError, match="refusing to overwrite"):
        save_fit(forged, baselines_with_committed_fit)
