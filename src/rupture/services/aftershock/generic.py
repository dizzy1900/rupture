"""Generic (multi-sequence) Reasenberg-Jones parameters and the Bayesian update toward a sequence.

**The defect this module exists to address.** The ETAS path in
:mod:`rupture.services.aftershock.forecaster` fits the aftershock zone's *own* catalogue. One hour
after a mainshock that catalogue is a decade of mostly isolated background seismicity plus a
handful of aftershocks, so the estimated productivity is the productivity of a quiet region and
the first day is under-forecast; ``reports/aftershock/`` measures that at 3-12x on the two
committed sequences. Nothing about the fit is wrong -- there is simply almost no sequence yet to
fit, and a maximum-likelihood estimate on almost no data is not a forecast. Operational practice
(Reasenberg & Jones 1989, 1994; Page et al. 2016) answers this with parameters estimated *across
many sequences* in the same tectonic regime, which carry the first hours and are then updated
toward the sequence as its own events arrive.

**The model.** Reasenberg & Jones (1989, 1994) give the rate of aftershocks of magnitude at least
``m`` at ``t`` days after a mainshock of magnitude ``M`` as

    ``lambda(t, m) = 10 ** (a + b * (M - m)) * (t + c) ** (-p)``   [events per day]

-- a Gutenberg-Richter magnitude distribution times a modified-Omori (Utsu) decay. ``a`` is the
productivity: the log rate of aftershocks *of the mainshock's own magnitude* at one day, offset by
``c``. The expected number in ``[t1, t2)`` is the integral of that rate, which is closed-form
(:func:`expected_count`). This is a different model from ETAS: it is aspatial, it has no
background term, and every aftershock is attributed to the mainshock rather than to a cascade. It
is much less expressive than ETAS and far easier to constrain from three events, which is exactly
why operational systems run it early.

**The generic table.** :data:`GENERIC_RJ` is the USGS operational table of generic ``(a, sigma_a,
b, p, c)`` by Garcia et al. (2012) tectonic regime, from Page et al. (2016). It is reproduced
verbatim from ``PageEtAlGenericParams_032116.csv`` in the USGS/SCEC ``opensha-oaf`` distribution
(CC0 1.0, https://github.com/opensha/opensha-oaf), retrieved 2026-09-10; the same numbers appear
in that repository's ``GenericRJ_ParametersFetch.json``. rupture does not estimate these itself
and could not: estimating them needs a global multi-sequence catalogue and a regionalisation,
neither of which this repository has.

**The Bayesian update.** Page et al. (2016) treat the generic ``a`` as a *distribution* over
sequences, not a point: within one regime, sequences differ in productivity by a Gaussian in ``a``
of standard deviation ``sigma_a`` (their third ingredient, inter-sequence variability). That
Gaussian is a prior. Given the aftershocks observed so far, the posterior is

    ``P(a | n) ∝ N(a; a_mean, sigma_a) * Poisson(n; Lambda(a))``,
    ``Lambda(a) = 10 ** a * 10 ** (b * (M - m_obs)) * Integral[(t + c) ** -p, t_start, t_end]``

evaluated on a grid in ``a`` (:class:`APosterior`), which is how ``opensha-oaf`` forms it too
(``RJ_AftershockModel_Bayesian``: ``P(a) = P1(a) * P2(a)`` on a discretised ``a`` axis, with
``b``, ``p`` and ``c`` held fixed and shared). ``b``, ``p`` and ``c`` stay at their generic values
throughout: with a handful of events they are not identifiable, and the repository has no
multi-sequence data to update them against.

**Why that is a blend and not a weighted average.** There is no weight anywhere in it. The
posterior interpolates on its own: with no elapsed observation window ``Lambda`` is zero for every
``a``, the likelihood is flat, and the posterior *is* the generic prior; as the exposure
``Lambda(a) / 10 ** a`` grows the likelihood sharpens around the sequence's own maximum-likelihood
productivity ``n / exposure`` and the prior stops mattering. The rate at which that happens is set
by ``sigma_a`` -- a measured spread between real sequences -- and by how many events have actually
arrived. Nothing here is tuned to the two sequences this repository validates on.

**What is deliberately not implemented.** Page et al.'s second ingredient, time-dependent
catalogue incompleteness, is absent. The count ``n`` fed to the likelihood is of events above the
region's *long-run* Mc, and a catalogue is demonstrably incomplete for hours after an M7.8, so
``n`` is too low, so the posterior is pulled below the truth exactly when the prior matters most.
That biases this module in the same direction as the defect it addresses, and it is not corrected
here because correcting it needs an Mc(t) relation this repository has no source for. It is
visible in the measurement: on Kahramanmaras at +1 h the update makes the forecast *worse* than
the untouched prior, which is what a likelihood fed a depleted count does. See
:func:`sequence_observation` and :mod:`rupture.services.aftershock.generic_validation`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import numpy.typing as npt

from rupture.domain import Catalog, Region, TectonicSetting
from rupture.services.aftershock.sequences import Mainshock
from rupture.services.aftershock.window import aftershock_zone_radius_km, sequence_catalog

SECONDS_PER_DAY = 86400.0

GENERIC_SOURCE = (
    "Page, van der Elst, Hardebeck, Felzer & Michael (2016), BSSA 106(5), 2290-2301, "
    "doi:10.1785/0120160073, as distributed in PageEtAlGenericParams_032116.csv / "
    "GenericRJ_ParametersFetch.json by opensha-oaf (CC0 1.0), retrieved 2026-09-10"
)
"""Provenance of every number in :data:`GENERIC_RJ`. Quoted in the notes of anything it produces."""


@dataclass(frozen=True, slots=True)
class GenericRJParameters:
    """Generic Reasenberg-Jones parameters for one tectonic regime, with the spread in ``a``.

    ``a_mean`` and ``a_sigma`` describe the Gaussian *across sequences* in that regime: a sequence
    drawn from this regime has productivity ``a`` distributed about ``a_mean``. ``a_sigma0`` and
    ``a_sigma1`` are the magnitude-dependent form of the same spread (:meth:`a_sigma_for`), which
    exists because the productivity of a small mainshock is estimated from few aftershocks and is
    correspondingly more variable. ``a_min``, ``a_max`` and ``a_delta`` are the discretisation the
    USGS table ships for the Bayesian combination and are used here for the same purpose.
    """

    regime: str
    description: str
    a_mean: float
    a_sigma: float
    a_sigma0: float
    a_sigma1: float
    b_value: float
    p_value: float
    c_value_days: float
    a_max_likelihood: float
    a_min: float = -4.5
    a_max: float = -0.5
    a_delta: float = 0.01

    def a_sigma_for(self, magnitude: float) -> float:
        """Magnitude-dependent ``sigma_a``: ``sqrt(sigma0^2 + sigma1^2 / 10^max(M, 6))``.

        The form and the floor at M6 are the USGS table's own
        (``GenericRJ_Parameters.get_aValueSigma(double)``); below M6 the spread is held at its M6
        value rather than continuing to grow, because the fits behind the table did not include
        smaller mainshocks. Regimes whose ``sigma1`` is zero return ``sigma0`` at every magnitude.
        """
        m = max(magnitude, 6.0)
        return math.sqrt(self.a_sigma0**2 + self.a_sigma1**2 / 10.0**m)


def _regime(
    name: str,
    description: str,
    *,
    a_max_like: float,
    p_max_like: float,
    a_mean: float,
    a_sigma: float,
    a_sigma1: float,
    a_sigma0: float = 0.49,
    b_value: float = 1.00,
    c_value: float = 0.018,
) -> GenericRJParameters:
    """One row of the USGS CSV, transcribed under its own column names.

    The table publishes both a maximum-likelihood ``(a, p)`` pair and the mean and sigma of the
    Gaussian over sequences in the regime. The forecast uses the *mean and sigma*, because the
    spread is the point of the exercise; ``a_max_likelihood`` is kept so the transcription can be
    checked against the published row and so a caller can see how far the two differ. ``p`` has
    only the one published value, the maximum-likelihood one.
    """
    return GenericRJParameters(
        regime=name,
        description=description,
        a_mean=a_mean,
        a_sigma=a_sigma,
        a_sigma0=a_sigma0,
        a_sigma1=a_sigma1,
        b_value=b_value,
        p_value=p_max_like,
        c_value_days=c_value,
        a_max_likelihood=a_max_like,
    )


GENERIC_RJ: dict[str, GenericRJParameters] = {
    p.regime: p
    for p in (
        _regime(
            "ANSR-DEEPCON",
            "ACR (deep) - active crustal region, deep continental",
            a_max_like=-2.01,
            p_max_like=0.98,
            a_mean=-2.13,
            a_sigma=0.52,
            a_sigma1=250,
        ),
        _regime(
            "ANSR-HOTSPOT",
            "ACR (hot spot)",
            a_max_like=-2.84,
            p_max_like=1.12,
            a_mean=-3.00,
            a_sigma=0.68,
            a_sigma1=680,
        ),
        _regime(
            "ANSR-OCEANBD",
            "ACR (oceanic boundary)",
            a_max_like=-2.69,
            p_max_like=1.08,
            a_mean=-3.19,
            a_sigma=0.60,
            a_sigma1=500,
        ),
        _regime(
            "ANSR-SHALCON",
            "ACR (shallow) - active crustal region, shallow continental",
            a_max_like=-2.16,
            p_max_like=0.98,
            a_mean=-2.42,
            a_sigma=0.63,
            a_sigma1=570,
        ),
        _regime(
            "ANSR-ABSLDEC",
            "ACR deep (above slab)",
            a_max_like=-2.04,
            p_max_like=1.01,
            a_mean=-2.29,
            a_sigma=0.63,
            a_sigma1=560,
        ),
        _regime(
            "ANSR-ABSLOCB",
            "ACR oceanic boundary (above slab)",
            a_max_like=-2.00,
            p_max_like=0.64,
            a_mean=-2.82,
            a_sigma=0.80,
            a_sigma1=890,
        ),
        _regime(
            "ANSR-ABSLSHC",
            "ACR shallow (above slab)",
            a_max_like=-2.44,
            p_max_like=1.06,
            a_mean=-2.85,
            a_sigma=0.75,
            a_sigma1=800,
        ),
        _regime(
            "SCR-GENERIC",
            "SCR (generic) - stable continental region",
            a_max_like=-2.28,
            p_max_like=0.73,
            a_mean=-2.85,
            a_sigma=0.78,
            a_sigma1=870,
        ),
        _regime(
            "SCR-ABVSLAB",
            "SCR (above slab)",
            a_max_like=-2.28,
            p_max_like=0.73,
            a_mean=-2.85,
            a_sigma=0.78,
            a_sigma1=870,
        ),
        _regime(
            "SOR-GENERIC",
            "SOR (generic) - stable oceanic region",
            a_max_like=-2.98,
            p_max_like=0.97,
            a_mean=-3.04,
            a_sigma=0.67,
            a_sigma1=650,
        ),
        _regime(
            "SOR-ABVSLAB",
            "SOR (above slab)",
            a_max_like=-2.98,
            p_max_like=0.97,
            a_mean=-3.04,
            a_sigma=0.67,
            a_sigma1=650,
        ),
        _regime(
            "SZ-GENERIC",
            "SZ (generic) - subduction zone",
            a_max_like=-2.09,
            p_max_like=0.88,
            a_mean=-2.47,
            a_sigma=0.63,
            a_sigma1=570,
        ),
        _regime(
            "SZ-INLBACK",
            "SZ (inland/back-arc)",
            a_max_like=-2.09,
            p_max_like=0.86,
            a_mean=-2.43,
            a_sigma=0.66,
            a_sigma1=640,
        ),
        _regime(
            "SZ-ONSHORE",
            "SZ (on-shore)",
            a_max_like=-2.02,
            p_max_like=0.81,
            a_mean=-2.34,
            a_sigma=0.60,
            a_sigma1=500,
        ),
        _regime(
            "SZ-OUTERTR",
            "SZ (outer-trench)",
            a_max_like=-1.97,
            p_max_like=0.92,
            a_mean=-2.42,
            a_sigma=0.64,
            a_sigma1=540,
        ),
    )
}
"""The 15 Garcia et al. (2012) regimes of Page et al. (2016). See :data:`GENERIC_SOURCE`.

The USGS table also carries four California-specific regimes (``CAL-SCSN``, ``CAL-NCSS``,
``CAL-MENDOCINO``, ``CAL-HYDROTHERMAL``) which are **not** reproduced here: they come from a later
California re-estimation whose citation this module could not verify, and no rupture region is in
California. Adding them means naming their source first.
"""


SETTING_TO_REGIME: dict[TectonicSetting, str] = {
    TectonicSetting.CONTINENTAL_COLLISION: "ANSR-SHALCON",
    TectonicSetting.TRANSFORM: "ANSR-SHALCON",
    TectonicSetting.EXTENSIONAL: "ANSR-SHALCON",
    TectonicSetting.SUBDUCTION: "SZ-GENERIC",
    TectonicSetting.INTRAPLATE: "SCR-GENERIC",
}
"""rupture's ``TectonicSetting`` to a Garcia regime. **This mapping is a judgement, not a lookup.**

The authoritative assignment in the USGS system is by hypocentre: the Garcia et al. (2012)
regionalisation polygons decide the regime, including whether the point sits above a slab. Those
polygons are not in this repository, so the regime is derived from the coarse
``Region.tectonic_setting`` instead. Collision, transform and extensional crustal settings all map
to the shallow active-crust regime, which is what a shallow continental mainshock in an actively
deforming belt is in that scheme; a subducting or stable setting maps to its generic regime.
``MIXED`` and ``OTHER`` are deliberately absent -- they carry no information a regime could be read
off, and guessing one silently is worse than making the caller name it.
"""


def regime_for_region(region: Region) -> str:
    """The Garcia regime for ``region``'s tectonic setting, or a ``KeyError`` naming the problem."""
    try:
        return SETTING_TO_REGIME[region.tectonic_setting]
    except KeyError:
        msg = (
            f"region {region.id!r} has tectonic_setting '{region.tectonic_setting}', which "
            "has no generic-parameter regime; pass a regime from GENERIC_RJ explicitly"
        )
        raise KeyError(msg) from None


def generic_for_region(region: Region) -> GenericRJParameters:
    """The generic parameters for ``region``. Convenience over :func:`regime_for_region`."""
    return GENERIC_RJ[regime_for_region(region)]


# ---------------------------------------------------------------------- the rate model
def omori_integral(p: float, c_days: float, t1_days: float, t2_days: float) -> float:
    """``Integral[(t + c) ** -p, t1, t2]`` in days, the time factor of the R-J rate.

    Closed form in both branches, with ``p == 1`` handled as the logarithm rather than by a limit,
    because the generic table has regimes at ``p`` within 0.01 of 1 and the ``1 - p`` denominator
    loses all its precision there.
    """
    if t2_days < t1_days:
        msg = f"window end {t2_days} precedes its start {t1_days}"
        raise ValueError(msg)
    if t1_days < 0.0:
        msg = f"time since mainshock must not be negative: {t1_days}"
        raise ValueError(msg)
    if c_days <= 0.0:
        msg = f"c must be positive: {c_days}"
        raise ValueError(msg)
    lo, hi = c_days + t1_days, c_days + t2_days
    if abs(1.0 - p) < 1e-6:
        return float(math.log(hi) - math.log(lo))
    q = 1.0 - p
    return float((hi**q - lo**q) / q)


def expected_count(
    *,
    a: float,
    b: float,
    mainshock_magnitude: float,
    min_magnitude: float,
    p: float,
    c_days: float,
    t1_days: float,
    t2_days: float,
) -> float:
    """Reasenberg-Jones expected number of aftershocks at or above ``min_magnitude`` in the window.

    ``10 ** (a + b * (M - m)) * Integral[(t + c) ** -p]``, with ``t`` in days since the mainshock.
    """
    k = 10.0 ** (a + b * (mainshock_magnitude - min_magnitude))
    return float(k * omori_integral(p, c_days, t1_days, t2_days))


def productivity_exposure(
    *,
    b: float,
    mainshock_magnitude: float,
    min_magnitude: float,
    p: float,
    c_days: float,
    t1_days: float,
    t2_days: float,
) -> float:
    """The window's expected count *per unit* ``10 ** a`` -- what the likelihood divides by.

    Separating this out is the whole of the update: the expected count is linear in ``10 ** a``,
    so the observation constrains ``10 ** a`` through a single number, and the sequence's own
    maximum-likelihood productivity is ``n / exposure``.
    """
    return expected_count(
        a=0.0,
        b=b,
        mainshock_magnitude=mainshock_magnitude,
        min_magnitude=min_magnitude,
        p=p,
        c_days=c_days,
        t1_days=t1_days,
        t2_days=t2_days,
    )


# ---------------------------------------------------------------------- the observation
@dataclass(frozen=True, slots=True)
class SequenceObservation:
    """What the sequence has shown so far, in the form the likelihood needs.

    ``n_events`` counts events at or above ``min_magnitude`` inside the aftershock zone with
    ``t1_days <= t < t2_days`` since the mainshock. The mainshock itself is excluded (it is the
    conditioning event, not an aftershock).
    """

    n_events: int
    min_magnitude: float
    t1_days: float
    t2_days: float

    @property
    def is_empty(self) -> bool:
        """True when no time has elapsed, so the likelihood carries nothing and the prior stands."""
        return self.t2_days <= self.t1_days


def sequence_observation(
    history: Catalog,
    *,
    mainshock: Mainshock,
    issue_time: datetime,
    min_magnitude: float,
    start_offset: timedelta = timedelta(0),
) -> SequenceObservation:
    """Count the sequence so far out of ``history``, which must not reach ``issue_time``.

    The count is of homogenised Mw at or above ``min_magnitude`` within the aftershock-zone radius,
    between ``mainshock_time + start_offset`` and ``issue_time``. Events without an Mw are not
    counted -- they are not counted by the forecast's target slice either, so counting them here
    would update the productivity against a population the forecast does not describe.

    ``start_offset`` exists for the incompleteness problem named in the module docstring: skipping
    the first minutes, when a catalogue after an M7.8 is missing most of its M4s, removes the worst
    of the depletion from the likelihood at the cost of removing most of the data with it. It
    defaults to zero -- no correction, the bias left in the open where it can be measured.
    """
    if start_offset < timedelta(0):
        msg = "start_offset must not be negative"
        raise ValueError(msg)
    start = mainshock.origin_time + start_offset
    # Earthquakes only: the region catalogues carry non-tectonic entries (Nepal has a
    # landslide-type ComCat event), and an aftershock productivity updated on one of those is
    # updated on a population the Reasenberg-Jones rate does not describe.
    zone = sequence_catalog(
        history.earthquakes(),
        mainshock_time=start,
        latitude=mainshock.latitude,
        longitude=mainshock.longitude,
        radius_km=aftershock_zone_radius_km(mainshock.magnitude),
    )
    n = sum(
        1
        for e in zone.events
        if e.mw is not None
        and e.mw >= min_magnitude - 1e-9
        and e.origin_time < issue_time
        and e.source_event_id != mainshock.event_id
    )
    return SequenceObservation(
        n_events=n,
        min_magnitude=min_magnitude,
        t1_days=start_offset.total_seconds() / SECONDS_PER_DAY,
        t2_days=(issue_time - mainshock.origin_time).total_seconds() / SECONDS_PER_DAY,
    )


# ---------------------------------------------------------------------- the posterior
@dataclass(frozen=True, slots=True)
class APosterior:
    """A distribution over the productivity ``a`` on a regular grid, prior or posterior.

    ``pdf`` is normalised so that ``sum(pdf) * delta == 1`` over ``a_grid``. Truncating an infinite
    Gaussian to ``[a_min, a_max]`` and renormalising is what the USGS discretisation does; the
    table's range is four log units wide, so for a posterior that has not run into an edge the
    truncation is immaterial, and :meth:`mass_at_edges` reports it when it is not.
    """

    a_grid: npt.NDArray[np.float64]
    pdf: npt.NDArray[np.float64]
    parameters: GenericRJParameters
    observation: SequenceObservation | None
    b_value: float
    mainshock_magnitude: float

    @property
    def delta(self) -> float:
        return float(self.a_grid[1] - self.a_grid[0])

    def mean_a(self) -> float:
        """Posterior mean of ``a`` itself. Reported for interpretation, never used as a rate."""
        return float(np.sum(self.a_grid * self.pdf) * self.delta)

    def mean_productivity(self) -> float:
        """``E[10 ** a]`` -- the quantity an expected count is actually linear in.

        Expected counts are averaged over the posterior, not evaluated at the posterior mean of
        ``a``: the two differ by a factor of order ``exp(0.5 * (ln10 * sigma_a) ** 2)``, which at
        the table's ``sigma_a ~ 0.63`` is about 5. Using the mean of ``a`` would quietly throw away
        most of the productivity the inter-sequence spread implies.
        """
        return float(np.sum(10.0**self.a_grid * self.pdf) * self.delta)

    def mass_at_edges(self) -> float:
        """Fraction of the posterior in the two end cells of the grid: a truncation warning."""
        return float((self.pdf[0] + self.pdf[-1]) * self.delta)

    def expected_count(self, *, min_magnitude: float, t1_days: float, t2_days: float) -> float:
        """Posterior-mean expected count over ``[t1, t2)``: ``E[10 ** a]`` times the exposure."""
        exposure = productivity_exposure(
            b=self.b_value,
            mainshock_magnitude=self.mainshock_magnitude,
            min_magnitude=min_magnitude,
            p=self.parameters.p_value,
            c_days=self.parameters.c_value_days,
            t1_days=t1_days,
            t2_days=t2_days,
        )
        return self.mean_productivity() * exposure

    def probability_at_least_one(
        self, *, min_magnitude: float, t1_days: float, t2_days: float
    ) -> float:
        """``Integral[P(a) * (1 - exp(-Lambda(a)))]`` -- the mixture, not ``1 - exp(-E[Lambda])``.

        Averaging the Poisson probability over the posterior rather than plugging the posterior
        mean into it is the honest form when ``a`` is uncertain by half a log unit: the two agree
        only while ``Lambda`` is small everywhere. It is still Poisson *given* ``a``, so it still
        ignores the clustering within a sequence, the same assumption the ETAS path declares.
        """
        exposure = productivity_exposure(
            b=self.b_value,
            mainshock_magnitude=self.mainshock_magnitude,
            min_magnitude=min_magnitude,
            p=self.parameters.p_value,
            c_days=self.parameters.c_value_days,
            t1_days=t1_days,
            t2_days=t2_days,
        )
        lam = 10.0**self.a_grid * exposure
        return float(np.sum(-np.expm1(-lam) * self.pdf) * self.delta)


def generic_prior(
    parameters: GenericRJParameters,
    *,
    mainshock_magnitude: float,
    b_value: float | None = None,
) -> APosterior:
    """The generic Gaussian in ``a``, discretised: the forecast before any aftershock is seen.

    ``b_value`` defaults to the table's own ``b``. Overriding it with a region's fitted b is
    *not* free: ``a`` was estimated jointly with ``b = 1.0``, so a different b re-scales the
    productivity at every magnitude below the mainshock's. The override exists because a caller
    may want consistency with the rest of rupture's fixed-b machinery, and the choice is recorded
    wherever the result is reported.
    """
    sigma = parameters.a_sigma_for(mainshock_magnitude)
    grid = np.arange(
        parameters.a_min,
        parameters.a_max + 0.5 * parameters.a_delta,
        parameters.a_delta,
        dtype=np.float64,
    )
    log_pdf = -0.5 * ((grid - parameters.a_mean) / sigma) ** 2
    pdf = _normalise(log_pdf, float(grid[1] - grid[0]))
    return APosterior(
        a_grid=grid,
        pdf=pdf,
        parameters=parameters,
        observation=None,
        b_value=parameters.b_value if b_value is None else b_value,
        mainshock_magnitude=mainshock_magnitude,
    )


def update(prior: APosterior, observation: SequenceObservation) -> APosterior:
    """Posterior over ``a`` given the aftershocks seen so far: prior times the Poisson likelihood.

    The likelihood is ``Poisson(n; 10 ** a * exposure)`` with the exposure computed at the generic
    ``b``, ``p`` and ``c``. An empty observation window returns the prior unchanged rather than
    multiplying by a constant, so "nothing has happened yet" and "nothing has been observed yet"
    do not silently become the same statement.
    """
    if observation.is_empty:
        return APosterior(
            a_grid=prior.a_grid,
            pdf=prior.pdf,
            parameters=prior.parameters,
            observation=observation,
            b_value=prior.b_value,
            mainshock_magnitude=prior.mainshock_magnitude,
        )
    exposure = productivity_exposure(
        b=prior.b_value,
        mainshock_magnitude=prior.mainshock_magnitude,
        min_magnitude=observation.min_magnitude,
        p=prior.parameters.p_value,
        c_days=prior.parameters.c_value_days,
        t1_days=observation.t1_days,
        t2_days=observation.t2_days,
    )
    lam = 10.0**prior.a_grid * exposure
    # log Poisson pmf without the n! term, which is constant in a and drops out of the
    # normalisation. n == 0 leaves the pure -lam penalty, which is the correct statement that a
    # quiet first hour is evidence against a very high productivity.
    log_like = observation.n_events * np.log(lam) - lam
    log_post = np.log(prior.pdf, out=np.full_like(prior.pdf, -np.inf), where=prior.pdf > 0.0)
    log_post = log_post + log_like
    return APosterior(
        a_grid=prior.a_grid,
        pdf=_normalise(log_post, prior.delta),
        parameters=prior.parameters,
        observation=observation,
        b_value=prior.b_value,
        mainshock_magnitude=prior.mainshock_magnitude,
    )


def _normalise(log_pdf: npt.NDArray[np.float64], delta: float) -> npt.NDArray[np.float64]:
    """Exponentiate a log density and scale it to unit integral on a regular grid."""
    finite = log_pdf[np.isfinite(log_pdf)]
    if finite.size == 0:  # pragma: no cover - only reachable from an all-zero prior
        msg = "log density is -inf everywhere; the prior and the data are incompatible"
        raise ValueError(msg)
    pdf = np.exp(log_pdf - float(finite.max()))
    pdf[~np.isfinite(pdf)] = 0.0
    total = float(pdf.sum()) * delta
    if total <= 0.0:  # pragma: no cover - guarded by the finite check above
        msg = "log density does not normalise"
        raise ValueError(msg)
    out: npt.NDArray[np.float64] = pdf / total
    return out
