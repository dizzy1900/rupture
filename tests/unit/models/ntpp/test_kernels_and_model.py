"""Shapes, exactness and leakage properties of the neural point process.

Fast by construction: nothing here trains. The kernels are checked against their closed forms by
numerical integration, the log-likelihood is checked for the one property that makes it a
likelihood at all (only strictly earlier events contribute), and the weight digest is checked for
the property the protocol's constancy rule depends on. Training is exercised in
``tests/integration``.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from rupture.domain import Catalog, Region
from rupture.models.challengers.ntpp.kernels import (
    geometric_scales,
    gr_log_density,
    omori_density,
    omori_integral,
    powerlaw_density,
    powerlaw_mass_within,
    sample_omori,
    sample_powerlaw_radius,
)
from rupture.models.challengers.ntpp.model import (
    FeatureBuilder,
    NeuralKernelHawkes,
    NTPPConfig,
    sequence_tensors,
)
from rupture.models.data import Standardiser, build_sequence, causal_slice
from tests.unit.models.conftest import CUTOFF, MC

CONFIG = NTPPConfig(n_time_basis=4, n_space_basis=3, hidden=4, epochs=1)


def _net(mc: float = MC) -> NeuralKernelHawkes:
    net = NeuralKernelHawkes(CONFIG)
    net.set_mc(mc)
    net.set_delta_m(0.1)
    net.set_background(np.array([0.0, 10.0]), np.array([0.0, -5.0]))
    return net


def _features() -> FeatureBuilder:
    return FeatureBuilder(
        mc=MC,
        depth_fill=8.0,
        standardiser=Standardiser.fit(
            np.array([[0.0, 5.0], [2.0, 15.0]]), ("mw_above_mc", "depth_km")
        ),
    )


# ---------------------------------------------------------------------- kernels
def test_the_omori_basis_elements_are_densities() -> None:
    c = torch.tensor(geometric_scales(1e-3, 100.0, 4))
    # p = 1.15 decays slowly: the tail needs a very distant upper limit before it is negligible.
    total = omori_integral(torch.tensor([0.0]), torch.tensor([1e80]), c, CONFIG.omori_p)
    assert torch.allclose(total, torch.ones_like(total), atol=1e-6)


def test_the_omori_integral_matches_numerical_quadrature() -> None:
    c = torch.tensor(geometric_scales(0.01, 10.0, 3))
    grid = torch.linspace(0.5, 4.0, 40_001, dtype=torch.float64)
    density = omori_density(grid, c, CONFIG.omori_p)
    quadrature = torch.trapezoid(density, grid, dim=0)
    exact = omori_integral(torch.tensor([0.5]), torch.tensor([4.0]), c, CONFIG.omori_p)[0]
    assert torch.allclose(quadrature, exact, rtol=1e-5)


def test_the_spatial_basis_elements_are_densities_on_the_plane() -> None:
    d = np.array([1.0, 5.0, 20.0])
    mass = powerlaw_mass_within(1e7, d, CONFIG.spatial_s)
    assert np.allclose(mass, 1.0, atol=1e-6)
    # And the radial integral of 2 pi r q(r) agrees with that closed form.
    r = torch.linspace(1e-6, 5000.0, 200_001, dtype=torch.float64)
    q = powerlaw_density(r, torch.tensor(d), CONFIG.spatial_s)
    radial = torch.trapezoid(2.0 * np.pi * r.unsqueeze(-1) * q, r, dim=0)
    assert torch.allclose(
        radial, torch.tensor(powerlaw_mass_within(5000.0, d, CONFIG.spatial_s)), rtol=1e-3
    )


def test_samplers_reproduce_their_own_distributions() -> None:
    rng = np.random.default_rng(7)
    c = np.full(20_000, 1.0)
    draws = sample_omori(rng.random(20_000), c, 1.5)
    # Median of the Omori density with p = 1.5, c = 1: c (2^(1/(p-1)) - 1) = 3.
    assert np.median(draws) == pytest.approx(3.0, rel=0.05)
    radii = sample_powerlaw_radius(rng.random(20_000), np.full(20_000, 4.0), 1.5)
    inside = float(np.mean(radii <= 8.0))
    assert inside == pytest.approx(
        float(powerlaw_mass_within(8.0, np.array([4.0]), 1.5)[0]), abs=0.02
    )


def test_gr_log_density_integrates_to_one() -> None:
    m = torch.linspace(2.95, 12.0, 100_001, dtype=torch.float64)
    log_beta = torch.tensor(np.log(2.3), dtype=torch.float64)
    density = torch.exp(gr_log_density(m, 2.95, log_beta))
    assert float(torch.trapezoid(density, m)) == pytest.approx(1.0, abs=1e-4)


def test_geometric_scales_are_ordered_and_bounded() -> None:
    scales = geometric_scales(0.5, 50.0, 5)
    assert scales[0] == pytest.approx(0.5)
    assert scales[-1] == pytest.approx(50.0)
    assert np.all(np.diff(scales) > 0)


# ---------------------------------------------------------------------- the network
def test_kernel_weights_are_convex_and_shaped_per_event() -> None:
    net = _net()
    features = torch.tensor(np.zeros((5, 2)), dtype=torch.float64)
    w_time, w_space = net.kernel_weights(features)
    assert w_time.shape == (5, CONFIG.n_time_basis)
    assert w_space.shape == (5, CONFIG.n_space_basis)
    assert torch.allclose(w_time.sum(-1), torch.ones(5, dtype=torch.float64))
    assert torch.all(w_time >= 0.0)


def test_productivity_is_non_decreasing_in_magnitude() -> None:
    """The constraint that replaced an unbounded neural offset; see :mod:`.model`."""
    net = _net()
    magnitudes = torch.tensor(np.arange(3.0, 8.01, 0.25), dtype=torch.float64)
    amp = net.productivity(magnitudes)
    assert torch.all(torch.diff(amp) >= 0.0)
    assert float(net.alpha.item()) >= 0.0


def test_features_are_clipped_so_an_unseen_magnitude_cannot_extrapolate() -> None:
    features = _features()
    ordinary = features.transform([4.0], [10.0])
    extreme = features.transform([9.5], [10.0])
    assert np.all(np.abs(extreme) <= features.clip + 1e-12)
    assert np.abs(extreme[0, 0]) > np.abs(ordinary[0, 0])


def test_only_strictly_earlier_events_enter_the_intensity() -> None:
    """Two events at the same instant must not trigger each other.

    Events 2 and 3 share a timestamp and a mark. If simultaneity were treated as causal, event 3
    would raise event 2's intensity (or vice versa) and the two log-rates would differ from the
    single-event case. Because the window is open on the right, each sees only event 1, so the
    summed log-rate over the pair is exactly twice the single event's.
    """
    net = _net()
    features = _features()
    depth = np.full(3, 8.0)
    mw = np.array([5.0, 3.5, 3.5])
    feat = torch.tensor(features.transform(mw, depth), dtype=torch.float64)
    kwargs = {"window_start": 0.5, "window_end": 1.5}

    def temporal(n: int) -> float:
        return float(
            net.log_likelihood_terms(
                t=torch.tensor([0.0, 1.0, 1.0][:n], dtype=torch.float64),
                x=torch.zeros(n, dtype=torch.float64),
                y=torch.zeros(n, dtype=torch.float64),
                mw=torch.tensor(mw[:n], dtype=torch.float64),
                features=feat[:n],
                **kwargs,
            )["sum_log_temporal"].item()
        )

    assert temporal(3) == pytest.approx(2.0 * temporal(2), rel=1e-12)


def test_the_compensator_matches_numerical_integration_of_the_total_rate() -> None:
    """The exact integral is what keeps the likelihood a likelihood; check it against quadrature."""
    net = _net()
    features = _features()
    t = torch.tensor([0.0, 0.4], dtype=torch.float64)
    x = torch.zeros(2, dtype=torch.float64)
    y = torch.zeros(2, dtype=torch.float64)
    mw = torch.tensor([5.0, 4.0], dtype=torch.float64)
    feat = torch.tensor(features.transform(mw.numpy(), np.full(2, 8.0)), dtype=torch.float64)
    end = 3.0
    terms = net.log_likelihood_terms(
        t=t, x=x, y=y, mw=mw, features=feat, window_start=0.2, window_end=end
    )
    with torch.no_grad():
        w_time, _ = net.kernel_weights(feat)
        amp = net.productivity(mw)
        grid = torch.linspace(0.2, end, 60_001, dtype=torch.float64)
        dt = grid.unsqueeze(1) - t.unsqueeze(0)
        h = (omori_density(dt, net.time_scales, CONFIG.omori_p) * w_time.unsqueeze(0)).sum(-1)
        rate = torch.exp(net.log_mu) + (amp.unsqueeze(0) * h * (dt > 0)).sum(-1)
    assert float(torch.trapezoid(rate, grid)) == pytest.approx(
        float(terms["compensator"].item()), rel=2e-3
    )


def test_the_likelihood_refuses_an_empty_window() -> None:
    net = _net()
    features = _features()
    t = torch.tensor([0.0, 1.0], dtype=torch.float64)
    feat = torch.tensor(features.transform([4.0, 4.0], [8.0, 8.0]), dtype=torch.float64)
    with pytest.raises(ValueError, match="no events inside"):
        net.log_likelihood_terms(
            t=t,
            x=torch.zeros(2, dtype=torch.float64),
            y=torch.zeros(2, dtype=torch.float64),
            mw=torch.tensor([4.0, 4.0], dtype=torch.float64),
            features=feat,
            window_start=5.0,
            window_end=6.0,
        )


def test_the_weight_digest_changes_with_any_weight() -> None:
    """Protocol § 7 rule 4 needs this: a retrain must be visible in the snapshot hash."""
    net = _net()
    before = net.weight_digest()
    assert net.weight_digest() == before
    with torch.no_grad():
        net.log_mu += 1e-12
    assert net.weight_digest() != before


def test_the_config_hash_changes_with_any_hyperparameter() -> None:
    base = NTPPConfig()
    assert base.config_hash() == NTPPConfig().config_hash()
    assert base.with_(hidden=base.hidden + 1).config_hash() != base.config_hash()
    assert NTPPConfig.from_dict(base.to_dict()) == base


def test_sequence_tensors_line_up_with_the_sequence(
    fixture_catalog: Catalog, region: Region
) -> None:
    sequence = build_sequence(
        causal_slice(fixture_catalog, region, CUTOFF, MC), region, CUTOFF, mc=MC
    )
    tensors = sequence_tensors(sequence, _features())
    assert tensors["t"].shape == (len(sequence),)
    assert tensors["features"].shape == (len(sequence), 2)
    assert torch.all(torch.isfinite(tensors["features"]))
