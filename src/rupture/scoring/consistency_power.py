"""Simulation-based power for the CSEP consistency tests (N, M, S, L, CL).

ADR-0055 decision 4: a p-value without a power figure is not a finding. The paired challenger
comparisons already carry one (:mod:`rupture.scoring.power`, :mod:`rupture.scoring.evidence`),
where the null is binomial or normal and the arithmetic is exact. The consistency tests are the
other half, and for them nothing is exact: a CSEP consistency test *is* a Monte Carlo procedure —
the forecast's expected counts define a Poisson process, catalogues are simulated from it, and the
observed statistic is read against the simulated distribution. Its power is therefore also
simulated, and the construction is the same two lines it always is:

* Under the **null** the forecast is correct. Simulate catalogues from the forecast's own rates,
  compute the statistic for each, and take the tail quantile to get the rejection threshold.
* Under an **alternative** the truth differs from the forecast in a named, parameterised way.
  Simulate catalogues from the *alternative* rates, compute the statistic against the *forecast*
  as the test itself would, and the power is the fraction that lands in the rejection region.

That second sentence carries the whole design: the catalogue comes from the alternative, the
statistic is evaluated against the forecast. A power routine that scored simulated catalogues
against the rates that generated them would be measuring the null twice and would report alpha
for every alternative, which is the failure this module's separate ``sample_from`` argument exists
to make impossible to write by accident.

**Why this matters more for the consistency tests than for the comparisons.** Khawaja et al.
(2023) show the S-test cannot reject a uniform, non-informative global forecast on a 0.1 degree
grid without roughly 32,000 events — about three centuries of them. A passing S-test on a decade
of data may be reporting nothing but its own blindness, and a consistency test that passes is
exactly the result that gets read as support. :func:`events_needed` is the general form of
Khawaja's 32,000: the expected event count at which a stated departure from the forecast would
first be detected at a stated power.

**The named alternatives.** They are conveniences, not a closed set — :func:`simulated_power`
takes any array of alternative rates:

* :func:`rate_multiplier_alternative` — the truth is uniformly ``k`` times the forecast. This is
  what the N-test sees, and it is the only one of the three that changes the expected count.
* :func:`spatial_concentration_alternative` — the truth's spatial density is the forecast's own,
  raised to a power and renormalised to the same total. This is what the S-test sees, and the
  N-test is blind to it by construction. **It degenerates for a uniform forecast**: a constant
  density raised to any power is the same constant density, so this family cannot express
  "the truth is clustered" relative to a uniform forecast. That degenerate case is precisely
  Khawaja's, and :func:`spatial_hotspot_alternative` is the family for it.
* :func:`magnitude_tilt_alternative` — the truth's magnitude distribution has a different b-value.
  This is what the M-test sees; N and S are blind to it.

L and CL inherit their sensitivity from all of these at once, which is both their appeal and the
reason a failing L-test names no cause.

**What a power figure from this module does and does not license.** It is a Monte Carlo estimate
with a standard error of ``sqrt(p (1 - p) / n_simulations)``, reported on every result rather than
left for the reader to work out. It assumes the forecast's Poisson independence between bins —
the same assumption the consistency tests themselves make, and one that a clustered catalogue
violates. Under real aftershock clustering the counts are overdispersed relative to Poisson, the
null distribution is wider than simulated here, and the true power is *lower* than these figures.
Nothing in this module fixes that; it inherits the assumption from the test it is powering, and
says so rather than quietly improving on it.

**NOT THE PUBLISHED TESTS — read this before quoting a figure against the 116 scored windows.**
Three of the five tests here are not the tests ``rupture.adapters.evaluation.pycsep`` ran, and the
difference is the conditioning:

* **N and L match.** Both are unconditioned, so the per-bin Poisson draw used here is the same law
  pycsep simulates.
* **M, S and CL do not.** pycsep conditions those on the observed event count
  (``use_observed_counts=True`` in ``csep.core.poisson_evaluations``): it simulates exactly
  ``n_obs`` events and allocates them multinomially, leaving the forecast rates unscaled. This
  module draws a Poisson-varying total, and for CL it additionally conditions by *rescaling* the
  rates to the observed total, which is a different statistic again.

The consequence is narrow and it is not "the figures are wrong": they are correct power figures
for the tests as defined in this module, and a sound guide to how sample size and effect size
trade off. They are **not** a statement about the specific M, S or CL results in
``reports/protocol/``. Matching pycsep's conditioning is the work that would make them one, and it
is not done. An earlier version of this docstring claimed the equivalence outright; it was wrong.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import numpy as np
import numpy.typing as npt
from scipy.special import gammaln

Rates = npt.NDArray[np.float64]

DEFAULT_SIMULATIONS = 2000
DEFAULT_ALPHA = 0.05
DEFAULT_TARGET_POWER = 0.8

# Peak working-set size for the simulated count array, in elements. Catalogues are simulated in
# chunks so that a fine grid cannot turn a power calculation into an out-of-memory crash: a
# 0.1 degree regional grid with 20 magnitude bins is already millions of bins per catalogue.
_MAX_CHUNK_ELEMENTS = 4_000_000

_SEARCH_STEPS = 60


class ConsistencyTest(StrEnum):
    """The five CSEP consistency tests, by their usual letters.

    A local enum rather than :class:`rupture.domain.evaluation.TestName` for the same reason
    :mod:`rupture.scoring.molchan` takes plain arrays: ADR-0061 commits rupture to interoperating
    with CSEP rather than forking it, and this module is written to be offerable upstream. The
    string values are identical to ``TestName``'s, so ``ConsistencyTest(result.test_name.value)``
    round-trips. The comparison tests T and W are absent because they are not simulation-based and
    already have an exact power path in :mod:`rupture.scoring.power`.
    """

    N = "N"
    M = "M"
    S = "S"
    L = "L"
    CL = "CL"


#: Tests whose rejection region is the lower tail alone. The N-test is two-sided at ``alpha / 2``
#: per tail. These tail conventions match ``rupture.adapters.evaluation.pycsep``; the *conditioning*
#: does not, for three of the five — see ``NOT THE PUBLISHED TESTS`` in the module docstring. A
#: figure from here describes the test defined in this module, which is the published test only
#: for N and L.
ONE_SIDED: frozenset[ConsistencyTest] = frozenset(
    {ConsistencyTest.M, ConsistencyTest.S, ConsistencyTest.L, ConsistencyTest.CL}
)


@dataclass(frozen=True, slots=True)
class RejectionRegion:
    """The outcomes a test would reject, estimated from a simulated null distribution.

    ``lower`` and ``upper`` are inclusive bounds: an observed statistic at or below ``lower``, or
    at or above ``upper``, rejects. Either may be ``None``, and both being ``None`` is the answer
    worth reading — see :attr:`exists`.
    """

    test: ConsistencyTest
    alpha: float
    lower: float | None
    upper: float | None
    n_simulations: int
    reason: str | None = None

    @property
    def exists(self) -> bool:
        """Whether any outcome at all would reject.

        ``False`` is not an error and is the more interesting answer: the test had no rejection
        region, so its "pass" carried no information whatsoever. Two things cause it. A discrete
        statistic whose extreme atom is larger than the tail mass — an N-test on a forecast
        expecting 0.1 events cannot reject on the low side, because observing zero is the modal
        outcome under the null. Or too few simulated catalogues: with ``n_simulations`` draws the
        finest attainable tail is ``1 / n_simulations``, so a test run at ``alpha`` with fewer
        than ``1 / alpha`` catalogues (``2 / alpha`` for the two-sided N-test) cannot reject
        whatever happens.
        """
        return self.lower is not None or self.upper is not None

    def rejects(self, statistics: npt.ArrayLike) -> npt.NDArray[np.bool_]:
        """Elementwise: would the test reject at each of these observed statistics?"""
        values = np.asarray(statistics, dtype=np.float64)
        out = np.zeros(values.shape, dtype=np.bool_)
        if self.lower is not None:
            out |= values <= self.lower
        if self.upper is not None:
            out |= values >= self.upper
        return out


@dataclass(frozen=True, slots=True)
class ConsistencyPowerResult:
    """P(reject | the truth is the alternative), with everything needed to distrust it."""

    test: ConsistencyTest
    alpha: float
    n_simulations: int
    region: RejectionRegion
    power: float | None
    null_rejection_rate: float | None
    expected_events_forecast: float
    expected_events_alternative: float

    @property
    def power_standard_error(self) -> float | None:
        """Monte Carlo standard error on :attr:`power`; ``None`` when there is no power figure.

        Reported rather than left implicit because the difference between a power of 0.78 and a
        power of 0.82 is usually this, and not the forecast.
        """
        if self.power is None:
            return None
        return float(np.sqrt(self.power * (1.0 - self.power) / self.n_simulations))

    @property
    def calibrated(self) -> bool | None:
        """Whether the measured null rejection rate sits within 3 standard errors of ``alpha``.

        This is the check the whole construction rests on: if the procedure does not reject a
        correct forecast at its nominal rate, no power figure it produces means anything. ``None``
        when calibration was not measured. A *low* rate is expected and benign for the N-test,
        whose statistic is a discrete count and whose attainable size is therefore below the
        nominal alpha; a high rate is never benign.
        """
        if self.null_rejection_rate is None:
            return None
        return bool(self.null_rejection_rate <= self.alpha + 3.0 * self.calibration_error)

    @property
    def calibration_error(self) -> float:
        """Standard error of the measured null rejection rate around ``alpha``.

        Two independent samples of ``n_simulations`` catalogues contribute, not one: the threshold
        is itself estimated from a finite null sample, so its own sampling error adds in quadrature
        to the error of the rate measured against it. Using the single-sample binomial error here
        would make a correctly calibrated procedure look miscalibrated about a third of the time.
        """
        return float(np.sqrt(2.0 * self.alpha * (1.0 - self.alpha) / self.n_simulations))


# --------------------------------------------------------------------------- statistics


def statistic(forecast: npt.ArrayLike, counts: npt.ArrayLike, test: ConsistencyTest) -> float:
    """The observed test statistic, in the convention the pycsep adapter records.

    ``forecast`` is expected counts per bin, shaped ``(n_spatial, n_magnitude)``; a 1-D array is
    read as a single magnitude bin. ``counts`` is the observed catalogue binned the same way.

    * **N** — the total observed count.
    * **L** — the Poisson joint log-likelihood of the observed counts under the forecast.
    * **CL** — the same, after rescaling the forecast to the observed total, which removes the
      rate error the N-test already reports and leaves the shape.
    * **S** — CL on the spatial marginal alone (summed over magnitude).
    * **M** — CL on the magnitude marginal alone (summed over space).

    A bin with zero forecast rate and a non-zero observed count contributes ``-inf``, which is the
    honest reading of a forecast that declared an event impossible. pycsep masks such bins
    instead; for any forecast with a background term the question does not arise, and where it
    does the two conventions disagree, so pass strictly positive rates if you want them to agree.
    """
    rates = _validate_rates(forecast)
    obs = np.asarray(counts)
    if obs.ndim == 1:
        obs = obs[:, None]
    if obs.shape != rates.shape:
        msg = f"counts and forecast must have the same shape: got {obs.shape} and {rates.shape}"
        raise ValueError(msg)
    _check_test_is_meaningful(rates, test)
    return float(_statistics(obs.astype(np.float64)[None, ...], rates, test)[0])


def simulate_statistics(
    forecast: npt.ArrayLike,
    test: ConsistencyTest,
    *,
    sample_from: npt.ArrayLike | None = None,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
) -> npt.NDArray[np.float64]:
    """Statistics of ``n_simulations`` catalogues, scored against ``forecast``.

    ``sample_from`` is the rate field the catalogues are *drawn* from, defaulting to ``forecast``
    itself, which is the null. Passing an alternative here — and only here — is what turns this
    into a power calculation: the test under study always scores against ``forecast``, because
    that is the forecast it was handed.
    """
    rates = _validate_rates(forecast)
    truth = rates if sample_from is None else _validate_rates(sample_from, name="sample_from")
    if truth.shape != rates.shape:
        msg = f"sample_from must match the forecast shape: got {truth.shape} and {rates.shape}"
        raise ValueError(msg)
    if n_simulations < 1:
        msg = f"n_simulations must be positive, got {n_simulations}"
        raise ValueError(msg)
    _check_test_is_meaningful(rates, test)

    chunk = max(1, _MAX_CHUNK_ELEMENTS // max(1, rates.size))
    out = np.empty(n_simulations, dtype=np.float64)
    done = 0
    while done < n_simulations:
        size = min(chunk, n_simulations - done)
        # Independent Poisson draws per bin. For an UNCONDITIONED test this is equivalent, by
        # Poisson thinning, to drawing a total from Poisson(sum) and allocating it multinomially
        # by the normalised rates. That equivalence is why it is the right draw for N and L, and
        # why it is the wrong one for M, S and CL: pycsep conditions those on the observed count
        # (`use_observed_counts=True`), which is the multinomial branch with the total FIXED, not
        # Poisson. The total varies here and there it does not.
        drawn = rng.poisson(truth, size=(size, *truth.shape)).astype(np.float64)
        out[done : done + size] = _statistics(drawn, rates, test)
        done += size
    return out


def rejection_region(
    forecast: npt.ArrayLike,
    test: ConsistencyTest,
    *,
    alpha: float = DEFAULT_ALPHA,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
) -> RejectionRegion:
    """Simulate the null and read off the outcomes that would reject at ``alpha``.

    The threshold is the outermost simulated value whose tail mass does not exceed the budget —
    ``alpha`` in the single lower tail for M/S/L/CL, ``alpha / 2`` in each tail for the two-sided
    N-test. Taking an attained value rather than an interpolated quantile keeps the region
    conservative for a discrete statistic: an interpolated threshold on a count statistic claims
    a size the test cannot actually attain, and then every power figure built on it is inflated.
    """
    _check_alpha(alpha)
    null = simulate_statistics(forecast, test, n_simulations=n_simulations, rng=rng)
    return region_from_null(null, test, alpha=alpha)


def region_from_null(
    null: npt.NDArray[np.float64], test: ConsistencyTest, *, alpha: float = DEFAULT_ALPHA
) -> RejectionRegion:
    """Build a :class:`RejectionRegion` from an already-simulated null distribution."""
    _check_alpha(alpha)
    n = int(null.size)
    if test in ONE_SIDED:
        lower, upper = _lower_threshold(null, alpha), None
    else:
        tail = alpha / 2.0
        lower, upper = _lower_threshold(null, tail), _upper_threshold(null, tail)
    reason = None
    if lower is None and upper is None:
        budget = alpha if test in ONE_SIDED else alpha / 2.0
        cause = (
            f"{n} simulated catalogues cannot resolve a tail of {budget:.4g} (the finest "
            f"attainable is {1.0 / n:.4g})"
            if 1.0 / n > budget
            else "the extreme atom of this statistic carries more mass than the tail budget"
        )
        reason = f"no outcome rejects at alpha={alpha}: {cause}"
    return RejectionRegion(
        test=test, alpha=alpha, lower=lower, upper=upper, n_simulations=n, reason=reason
    )


# --------------------------------------------------------------------------- power


def simulated_power(
    forecast: npt.ArrayLike,
    alternative: npt.ArrayLike,
    test: ConsistencyTest,
    *,
    alpha: float = DEFAULT_ALPHA,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
    check_calibration: bool = True,
) -> ConsistencyPowerResult:
    """P(the test rejects ``forecast`` | the truth is ``alternative``).

    ``power`` is ``None``, never ``0.0``, when the test has no rejection region. The distinction
    is the whole point: a power of zero says the effect is undetectable, while no rejection region
    says *nothing* was detectable and the test's verdict was decided before the data arrived.

    ``check_calibration`` draws a second, independent null sample and measures how often the
    region built from the first one actually rejects a correct forecast. It costs one more null
    simulation and it is the only evidence that the threshold is right; leave it on unless you are
    inside a search loop that has already validated the region.
    """
    rates = _validate_rates(forecast)
    alt = _validate_rates(alternative, name="alternative")
    if alt.shape != rates.shape:
        msg = f"alternative must match the forecast shape: got {alt.shape} and {rates.shape}"
        raise ValueError(msg)
    region = rejection_region(rates, test, alpha=alpha, n_simulations=n_simulations, rng=rng)
    null_rate: float | None = None
    if check_calibration:
        fresh = simulate_statistics(rates, test, n_simulations=n_simulations, rng=rng)
        null_rate = float(region.rejects(fresh).mean())
    power = power_of_alternative(rates, alt, test, region, n_simulations=n_simulations, rng=rng)
    return ConsistencyPowerResult(
        test=test,
        alpha=alpha,
        n_simulations=n_simulations,
        region=region,
        power=power,
        null_rejection_rate=null_rate,
        expected_events_forecast=float(rates.sum()),
        expected_events_alternative=float(alt.sum()),
    )


def power_of_alternative(
    forecast: npt.ArrayLike,
    alternative: npt.ArrayLike,
    test: ConsistencyTest,
    region: RejectionRegion,
    *,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
) -> float | None:
    """Rejection rate under ``alternative`` for an already-built region; ``None`` if it is empty.

    Split out from :func:`simulated_power` because the null — and therefore the region — does
    not depend on the alternative. A sweep over effect sizes builds the region once and pays for
    the alternative alone, which is what makes the minimum-detectable-effect searches affordable
    and also removes threshold noise from the comparison between neighbouring effect sizes.
    """
    if not region.exists:
        return None
    stats = simulate_statistics(
        forecast, test, sample_from=alternative, n_simulations=n_simulations, rng=rng
    )
    return float(region.rejects(stats).mean())


# --------------------------------------------------------------------------- alternatives


def rate_multiplier_alternative(forecast: npt.ArrayLike, multiplier: float) -> Rates:
    """The truth is ``multiplier`` times the forecast everywhere: shape right, rate wrong.

    The alternative the N-test exists to catch, and the only named one here that changes the
    expected event count. Note that the S, M and CL statistics are *not* blind to it, because they
    condition on the observed count and a rate error changes that count; their sensitivity to a
    multiplier runs entirely through the same channel the N-test uses, and reading it as spatial
    or magnitude skill is a misattribution.
    """
    rates = _validate_rates(forecast)
    if multiplier <= 0.0 or not np.isfinite(multiplier):
        msg = f"multiplier must be finite and positive, got {multiplier}"
        raise ValueError(msg)
    return np.asarray(rates * multiplier, dtype=np.float64)


def spatial_concentration_alternative(forecast: npt.ArrayLike, concentration: float) -> Rates:
    """The truth's spatial density is the forecast's, raised to ``concentration``, renormalised.

    ``concentration > 1`` means the events really are more tightly concentrated than forecast;
    ``< 1`` means more spread out; ``1`` returns the forecast unchanged. The total expected count
    and the magnitude distribution within each cell are both preserved exactly, so the N-test and
    the M-test are blind to this family by construction and any power they show against it is
    Monte Carlo noise. That is the property that makes it a clean probe of the S-test.

    **Degenerate for a uniform forecast.** A constant density raised to any power, renormalised,
    is the same constant density, so this returns the forecast unchanged and the measured power
    will be alpha. That is not a bug in the calculation — it is that this family is defined
    relative to the forecast's own shape and a uniform forecast has none. It is also exactly
    Khawaja et al.'s setting; use :func:`spatial_hotspot_alternative` there.
    """
    rates = _validate_rates(forecast)
    if concentration <= 0.0 or not np.isfinite(concentration):
        msg = f"concentration must be finite and positive, got {concentration}"
        raise ValueError(msg)
    spatial = rates.sum(axis=1)
    reweighted = np.power(spatial, concentration)
    total = reweighted.sum()
    if total <= 0.0:  # pragma: no cover - _validate_rates already forbids an all-zero forecast
        msg = "the forecast has no spatial mass to concentrate"
        raise ValueError(msg)
    reweighted *= spatial.sum() / total
    return _rescale_marginal(rates, spatial, reweighted, axis=0)


def spatial_hotspot_alternative(
    forecast: npt.ArrayLike, *, cells: npt.ArrayLike, share: float
) -> Rates:
    """The truth puts ``share`` of its events in ``cells``, spread by the forecast within them.

    The family for the case :func:`spatial_concentration_alternative` cannot express: a forecast
    with no shape of its own — the uniform, non-informative forecast — against a truth that
    clusters somewhere the caller names. ``cells`` is an index array into the spatial axis and
    ``share`` the fraction of the total expected count they carry under the alternative; the
    forecast gives them ``rates[cells].sum() / rates.sum()``. Total expected count and the
    per-cell magnitude distribution are preserved, so again only the spatial tests can see it.

    Both the hotspot and its complement must carry some forecast mass: a hotspot the forecast
    calls impossible would make the alternative's departure infinite rather than parameterised,
    and the resulting power figure would describe a single ``-inf`` statistic, not an effect size.
    """
    rates = _validate_rates(forecast)
    if not 0.0 < share < 1.0:
        msg = f"share must lie in (0, 1), got {share}"
        raise ValueError(msg)
    spatial = rates.sum(axis=1)
    index = _as_cell_mask(cells, spatial.shape[0])
    if not index.any() or index.all():
        msg = "cells must select a non-empty proper subset of the spatial bins"
        raise ValueError(msg)
    inside, outside = spatial[index].sum(), spatial[~index].sum()
    if inside <= 0.0 or outside <= 0.0:
        msg = "both the hotspot and its complement must carry non-zero forecast rate"
        raise ValueError(msg)
    total = spatial.sum()
    target = np.where(
        index, spatial * (share * total / inside), spatial * ((1.0 - share) * total / outside)
    )
    return _rescale_marginal(rates, spatial, target, axis=0)


def magnitude_tilt_alternative(
    forecast: npt.ArrayLike, *, delta_b: float, magnitudes: npt.ArrayLike
) -> Rates:
    """The truth's b-value differs from the forecast's by ``delta_b``, at the same total rate.

    Each magnitude bin is reweighted by ``10 ** (-delta_b * (m - m_min))`` and the whole field is
    renormalised to the forecast's total, so a positive ``delta_b`` means the truth is relatively
    poorer in large events than forecast. Total expected count and the spatial marginal are both
    preserved, so the N-test and the S-test are blind to this family and the M-test is not.

    ``magnitudes`` is one representative magnitude per bin — bin centres are the usual choice, and
    the calculation only depends on their spacing, not on where the sequence starts.
    """
    rates = _validate_rates(forecast)
    mags = np.asarray(magnitudes, dtype=np.float64)
    if mags.ndim != 1 or mags.size != rates.shape[1]:
        msg = f"magnitudes must be one value per magnitude bin: expected {rates.shape[1]}"
        raise ValueError(msg)
    if not np.all(np.isfinite(mags)):
        msg = "magnitudes must be finite"
        raise ValueError(msg)
    if not np.isfinite(delta_b):
        msg = f"delta_b must be finite, got {delta_b}"
        raise ValueError(msg)
    marginal = rates.sum(axis=0)
    weights = np.power(10.0, -delta_b * (mags - mags.min()))
    target = marginal * weights
    total = target.sum()
    if total <= 0.0:  # pragma: no cover - _validate_rates already forbids an all-zero forecast
        msg = "the forecast has no magnitude mass to tilt"
        raise ValueError(msg)
    target *= marginal.sum() / total
    return _rescale_marginal(rates, marginal, target, axis=1)


# --------------------------------------------------------------- minimum detectable effect


def minimum_detectable_effect(
    forecast: npt.ArrayLike,
    test: ConsistencyTest,
    family: Callable[[float], npt.ArrayLike],
    *,
    null_parameter: float,
    extreme_parameter: float,
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_TARGET_POWER,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
    rel_tol: float = 0.02,
) -> float | None:
    """The parameter closest to ``null_parameter`` that this test would reject at ``target_power``.

    ``family`` maps a parameter to an alternative rate field; ``null_parameter`` is the value that
    returns the forecast itself and ``extreme_parameter`` the far end of the search, at which the
    effect is expected to be obvious. Both must be positive, because the bisection is geometric:
    effect parameters of this kind are ratios and halving is the natural step.

    ``None`` means the effect was undetectable at ``target_power`` even at ``extreme_parameter`` —
    report it as the bound the experiment actually achieved, unattained, rather than as a number.

    **Three honest caveats.** The search assumes power increases monotonically as the parameter
    moves away from the null, which is true in expectation and not in a finite sample. Each
    evaluation is a Monte Carlo estimate with a standard error near ``0.009`` at the default
    2,000 simulations, so the returned parameter is resolved to about the change that moves power
    by a percentage point, whatever ``rel_tol`` says. And the null is simulated once and reused
    across the whole search, which is what makes neighbouring evaluations comparable at all — but
    it also means a single unlucky null sample shifts the whole curve together.
    """
    rates = _validate_rates(forecast)
    _check_alpha(alpha)
    if not alpha < target_power < 1.0:
        msg = f"target_power must lie in (alpha, 1), got {target_power}"
        raise ValueError(msg)
    if null_parameter <= 0.0 or extreme_parameter <= 0.0:
        msg = "both parameters must be positive: the search is geometric"
        raise ValueError(msg)
    region = rejection_region(rates, test, alpha=alpha, n_simulations=n_simulations, rng=rng)
    if not region.exists:
        return None

    def power_of(parameter: float) -> float:
        value = power_of_alternative(
            rates,
            _validate_rates(family(parameter), name="alternative"),
            test,
            region,
            n_simulations=n_simulations,
            rng=rng,
        )
        return 0.0 if value is None else value

    if power_of(extreme_parameter) < target_power:
        return None
    return _geometric_search(power_of, null_parameter, extreme_parameter, target_power, rel_tol)


def minimum_detectable_rate_multiplier(
    forecast: npt.ArrayLike,
    test: ConsistencyTest = ConsistencyTest.N,
    *,
    direction: Literal["above", "below"] = "above",
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_TARGET_POWER,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
    largest_multiplier: float = 100.0,
    smallest_multiplier: float = 0.01,
    rel_tol: float = 0.02,
) -> float | None:
    """Smallest rate error this test would catch at ``target_power``, as a multiplier of forecast.

    ``direction="above"`` searches multipliers greater than one — the forecast is too low — and
    ``"below"`` searches multipliers less than one. The two are not mirror images and must be
    asked for separately: a Poisson count has a longer right tail than left, so the multiplier
    detectable below one is further from one, in ratio, than the one detectable above it. Quoting
    a single figure as "the detectable rate error" hides which direction it was measured in.
    """
    extreme = largest_multiplier if direction == "above" else smallest_multiplier
    if direction == "above" and extreme <= 1.0:
        msg = f"largest_multiplier must exceed 1 for direction='above', got {extreme}"
        raise ValueError(msg)
    if direction == "below" and not 0.0 < extreme < 1.0:
        msg = f"smallest_multiplier must lie in (0, 1) for direction='below', got {extreme}"
        raise ValueError(msg)
    return minimum_detectable_effect(
        forecast,
        test,
        lambda k: rate_multiplier_alternative(forecast, k),
        null_parameter=1.0,
        extreme_parameter=extreme,
        alpha=alpha,
        target_power=target_power,
        n_simulations=n_simulations,
        rng=rng,
        rel_tol=rel_tol,
    )


def minimum_detectable_concentration(
    forecast: npt.ArrayLike,
    test: ConsistencyTest = ConsistencyTest.S,
    *,
    direction: Literal["concentrate", "disperse"] = "concentrate",
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_TARGET_POWER,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
    largest_concentration: float = 8.0,
    smallest_concentration: float = 0.05,
    rel_tol: float = 0.02,
) -> float | None:
    """Smallest spatial concentration exponent this test would catch at ``target_power``.

    Returns ``None`` for a uniform forecast whatever the sample size, because the concentration
    family is identically the forecast there — see :func:`spatial_concentration_alternative`. That
    ``None`` is a true statement about this family and *not* a statement that the forecast's
    spatial component is untestable; a hotspot alternative would still be detectable.
    """
    extreme = largest_concentration if direction == "concentrate" else smallest_concentration
    if direction == "concentrate" and extreme <= 1.0:
        msg = f"largest_concentration must exceed 1 to concentrate, got {extreme}"
        raise ValueError(msg)
    if direction == "disperse" and not 0.0 < extreme < 1.0:
        msg = f"smallest_concentration must lie in (0, 1) to disperse, got {extreme}"
        raise ValueError(msg)
    return minimum_detectable_effect(
        forecast,
        test,
        lambda c: spatial_concentration_alternative(forecast, c),
        null_parameter=1.0,
        extreme_parameter=extreme,
        alpha=alpha,
        target_power=target_power,
        n_simulations=n_simulations,
        rng=rng,
        rel_tol=rel_tol,
    )


# --------------------------------------------------------------------------- events needed


def events_needed(
    forecast: npt.ArrayLike,
    test: ConsistencyTest,
    family: Callable[[Rates], npt.ArrayLike],
    *,
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_TARGET_POWER,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
    max_events: float = 1e6,
    rel_tol: float = 0.1,
) -> float | None:
    """Expected event count at which this test would first detect this departure.

    The general form of the number Khawaja et al. (2023) report as roughly 32,000 for the S-test
    against a uniform global forecast. The forecast's *shape* is held fixed and its total expected
    count is scaled; ``family`` is applied to each scaled forecast to build the matching
    alternative, so the departure is held fixed in relative terms while the sample grows. Both the
    null and the alternative are re-simulated at every candidate total, because the rejection
    region of a count-based test depends on the count.

    Returns a float, not an integer: it is an expected count under a Poisson process, and rounding
    it to an integer would imply a precision the Monte Carlo search does not have. ``None`` means
    more than ``max_events``, which for most regions is a statement about centuries.

    The search is a geometric bracket followed by a geometric bisection, resolved to ``rel_tol``
    in relative terms — the default 10 % is deliberately coarse, because the underlying power
    estimate has a standard error of about a percentage point and pretending to three significant
    figures here would be pretending.
    """
    rates = _validate_rates(forecast)
    _check_alpha(alpha)
    if not alpha < target_power < 1.0:
        msg = f"target_power must lie in (alpha, 1), got {target_power}"
        raise ValueError(msg)
    if max_events <= 0.0:
        msg = f"max_events must be positive, got {max_events}"
        raise ValueError(msg)
    shape = rates / rates.sum()

    def power_of(total: float) -> float:
        scaled = np.asarray(shape * total, dtype=np.float64)
        region = rejection_region(scaled, test, alpha=alpha, n_simulations=n_simulations, rng=rng)
        value = power_of_alternative(
            scaled,
            _validate_rates(family(scaled), name="alternative"),
            test,
            region,
            n_simulations=n_simulations,
            rng=rng,
        )
        return 0.0 if value is None else value

    low = 1.0
    if power_of(low) >= target_power:
        return low
    high = low
    while high < max_events:
        high = min(high * 2.0, max_events)
        if power_of(high) >= target_power:
            return _geometric_search(power_of, low, high, target_power, rel_tol)
        low = high
    return None


def events_needed_for_rate_multiplier(
    forecast: npt.ArrayLike,
    multiplier: float,
    test: ConsistencyTest = ConsistencyTest.N,
    *,
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_TARGET_POWER,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
    max_events: float = 1e6,
    rel_tol: float = 0.1,
) -> float | None:
    """Expected events needed before a rate error of ``multiplier`` would be detected."""
    if multiplier <= 0.0 or multiplier == 1.0:
        msg = "a multiplier of 1 is the forecast itself and is never detectable"
        raise ValueError(msg)
    return events_needed(
        forecast,
        test,
        lambda scaled: rate_multiplier_alternative(scaled, multiplier),
        alpha=alpha,
        target_power=target_power,
        n_simulations=n_simulations,
        rng=rng,
        max_events=max_events,
        rel_tol=rel_tol,
    )


def events_needed_for_concentration(
    forecast: npt.ArrayLike,
    concentration: float,
    test: ConsistencyTest = ConsistencyTest.S,
    *,
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_TARGET_POWER,
    n_simulations: int = DEFAULT_SIMULATIONS,
    rng: np.random.Generator,
    max_events: float = 1e6,
    rel_tol: float = 0.1,
) -> float | None:
    """Expected events needed before a spatial concentration of ``concentration`` is detected."""
    if concentration <= 0.0 or concentration == 1.0:
        msg = "a concentration of 1 is the forecast itself and is never detectable"
        raise ValueError(msg)
    return events_needed(
        forecast,
        test,
        lambda scaled: spatial_concentration_alternative(scaled, concentration),
        alpha=alpha,
        target_power=target_power,
        n_simulations=n_simulations,
        rng=rng,
        max_events=max_events,
        rel_tol=rel_tol,
    )


# --------------------------------------------------------------------------- internals


def _statistics(
    counts: npt.NDArray[np.float64], rates: Rates, test: ConsistencyTest
) -> npt.NDArray[np.float64]:
    """Statistic per simulated catalogue; ``counts`` is ``(n_simulations, n_space, n_mag)``."""
    n_sims = counts.shape[0]
    totals = counts.reshape(n_sims, -1).sum(axis=1)
    if test is ConsistencyTest.N:
        return np.asarray(totals, dtype=np.float64)
    if test is ConsistencyTest.L:
        return _poisson_log_likelihood(counts.reshape(n_sims, -1), rates.reshape(1, -1))
    if test is ConsistencyTest.CL:
        flat = rates.reshape(1, -1)
        return _poisson_log_likelihood(counts.reshape(n_sims, -1), _scaled(flat, totals))
    if test is ConsistencyTest.S:
        marginal = rates.sum(axis=1).reshape(1, -1)
        return _poisson_log_likelihood(counts.sum(axis=2), _scaled(marginal, totals))
    marginal = rates.sum(axis=0).reshape(1, -1)
    return _poisson_log_likelihood(counts.sum(axis=1), _scaled(marginal, totals))


def _scaled(marginal: Rates, totals: npt.NDArray[np.float64]) -> Rates:
    """Rescale a rate marginal to each simulated catalogue's own total count.

    The "conditional" in conditional likelihood: it removes the rate error that the N-test already
    reports, so what is left is the shape. A catalogue with no events scales the rates to zero,
    which gives a log-likelihood of exactly zero — a real atom in the null distribution of every
    conditional statistic, and the reason a low-rate forecast can have no rejection region at all.
    """
    factor = totals / marginal.sum()
    return np.asarray(marginal * factor[:, None], dtype=np.float64)


def _poisson_log_likelihood(counts: npt.NDArray[np.float64], rates: Rates) -> Rates:
    """``sum_i n_i log(lambda_i) - lambda_i - log(n_i!)``, summed over the last axis."""
    safe = np.where(rates > 0.0, rates, 1.0)
    term = counts * np.log(safe) - rates - gammaln(counts + 1.0)
    term = np.where((rates <= 0.0) & (counts > 0.0), -np.inf, term)
    return np.asarray(term.sum(axis=-1), dtype=np.float64)


def _rescale_marginal(rates: Rates, current: Rates, target: Rates, *, axis: int) -> Rates:
    """Reweight ``rates`` so one marginal becomes ``target``, holding the other axis' shape.

    A bin the forecast gave zero rate stays at zero under every named alternative here. That is
    deliberate: moving rate into a cell the forecast called impossible would make the alternative's
    departure infinite rather than parameterised, and the power it reported would be an artefact
    of one ``-inf`` statistic rather than a measurement of an effect size.
    """
    safe = np.where(current > 0.0, current, 1.0)
    factor = np.where(current > 0.0, target / safe, 0.0)
    scaled = rates * (factor[:, None] if axis == 0 else factor[None, :])
    return np.asarray(scaled, dtype=np.float64)


def _lower_threshold(null: npt.NDArray[np.float64], tail: float) -> float | None:
    values, counts = np.unique(null, return_counts=True)
    cdf = np.cumsum(counts) / float(null.size)
    fits = np.flatnonzero(cdf <= tail)
    return None if fits.size == 0 else float(values[fits[-1]])


def _upper_threshold(null: npt.NDArray[np.float64], tail: float) -> float | None:
    values, counts = np.unique(null, return_counts=True)
    below = np.concatenate(([0], np.cumsum(counts)[:-1]))
    sf = (float(null.size) - below) / float(null.size)
    fits = np.flatnonzero(sf <= tail)
    return None if fits.size == 0 else float(values[fits[0]])


def _geometric_search(
    power_of: Callable[[float], float],
    failing: float,
    passing: float,
    target_power: float,
    rel_tol: float,
) -> float:
    """Bisect geometrically between a failing and a passing parameter; return the passing end."""
    if rel_tol <= 0.0:
        msg = f"rel_tol must be positive, got {rel_tol}"
        raise ValueError(msg)
    stop = np.log1p(rel_tol)
    for _ in range(_SEARCH_STEPS):
        if abs(np.log(passing / failing)) <= stop:
            break
        mid = float(np.sqrt(failing * passing))
        if power_of(mid) >= target_power:
            passing = mid
        else:
            failing = mid
    return float(passing)


def _validate_rates(expected: npt.ArrayLike, name: str = "forecast") -> Rates:
    arr = np.asarray(expected, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.ndim != 2:
        msg = f"{name} must be (n_spatial, n_magnitude) or 1-D, got shape {arr.shape}"
        raise ValueError(msg)
    if arr.size == 0:
        msg = f"{name} must have at least one bin"
        raise ValueError(msg)
    if not np.all(np.isfinite(arr)):
        msg = f"{name} expected counts must all be finite"
        raise ValueError(msg)
    if np.any(arr < 0.0):
        msg = f"{name} expected counts must be non-negative"
        raise ValueError(msg)
    if arr.sum() <= 0.0:
        msg = f"{name} must have a positive total expected count"
        raise ValueError(msg)
    return arr


def _check_test_is_meaningful(rates: Rates, test: ConsistencyTest) -> None:
    """Refuse the two tests whose statistic is a constant given the count, rather than run them.

    With a single magnitude bin the M-test statistic is determined by the total count, so it
    duplicates the N-test and reports it as magnitude skill; with a single spatial bin the S-test
    does the same. Both would return a power figure that looks like evidence about a distribution
    the forecast does not resolve.
    """
    if test is ConsistencyTest.M and rates.shape[1] < 2:
        msg = "the M-test needs at least two magnitude bins; this forecast resolves one"
        raise ValueError(msg)
    if test is ConsistencyTest.S and rates.shape[0] < 2:
        msg = "the S-test needs at least two spatial bins; this forecast resolves one"
        raise ValueError(msg)


def _check_alpha(alpha: float) -> None:
    if not 0.0 < alpha < 1.0:
        msg = f"alpha must lie in (0, 1), got {alpha}"
        raise ValueError(msg)


def _as_cell_mask(cells: npt.ArrayLike, n_cells: int) -> npt.NDArray[np.bool_]:
    """Cell selection as a boolean mask, accepting either indices or a mask.

    A boolean mask cast through ``int64`` becomes ones and zeros, so ``cells=mask`` used to
    select cells 0 and 1 whatever the mask actually said -- silently, with no error and a
    plausible-looking result. Booleans are therefore detected by dtype rather than coerced, and
    an index array is range-checked instead of being allowed to wrap on a negative value.
    """
    array = np.asarray(cells)
    if array.dtype == np.bool_:
        if array.shape != (n_cells,):
            msg = (
                "a boolean cell mask must have one entry per cell: got "
                f"{array.shape}, want ({n_cells},)"
            )
            raise ValueError(msg)
        return array.astype(np.bool_, copy=True)
    index = np.asarray(array, dtype=np.int64).ravel()
    if index.size and (index.min() < 0 or index.max() >= n_cells):
        msg = f"cell indices must lie in [0, {n_cells}); got [{index.min()}, {index.max()}]"
        raise ValueError(msg)
    mask = np.zeros(n_cells, dtype=np.bool_)
    mask[index] = True
    return mask
