"""Short-term aftershock incompleteness (STAI): completeness as a function of time.

A catalogue that is complete at magnitude ``mc`` in the long run is *not* complete at ``mc`` in
the minutes and hours after a large earthquake. The coda of the mainshock buries small events,
analysts fall behind, and the detection threshold rises by magnitude units before decaying back.
ADR-0060 records the consequence: completeness is a field Mc(x, t), not a scalar, and ADR-0059
makes ETAS-I — ETAS fitted with a per-event completeness — the mandatory reference whenever an
event below the long-run threshold enters a score.

This module is the time argument of that field, and nothing else. It does not estimate
completeness from data; it evaluates a *declared, cited* empirical law and reduces it to the
per-event array ``mc_current`` that :mod:`etas.inversion` consumes when its metadata sets
``mc="var"``. Keeping it here, in pure numpy, is deliberate: the same curve is needed by the
aftershock service and by any scorer that has to say which targets were detectable, and none of
those should have to import a forecasting adapter to ask.

**The law.** Helmstetter, Kagan & Jackson (2006) fitted southern Californian sequences with

    Mc(t) = Mm - 4.5 - 0.75 * log10(t),    t in days after a trigger of magnitude Mm

which is the default here, :data:`HELMSTETTER_2006`. The coefficients are fields of
:class:`StaiCoefficients` rather than literals in the arithmetic, because they are regional
measurements: a network with different station density and different analyst latency has
different ones, and a number that cannot be swapped is a number nobody checks.

**What this is not.** Mizrahi, Nandan & Wiemer (2021) — the paper behind the pinned ``etas``
package — supply two methods. The first inverts ETAS on a catalogue whose completeness varies in
time, taking ``mc_current`` as *given*; that is the path this module feeds. The second replaces
the sharp threshold entirely with a rate- and magnitude-dependent detection probability. **This
module implements neither of their estimators.** It supplies an externally declared Mc(t) to
their first method. Which Mc(t) they themselves used for their California ETAS-I results was not
verified against the paper when this module was written, so no claim is made that these
coefficients reproduce theirs; see ADR-0066.

**What it also is not.** ``mc="positive"`` in the same package is the b-positive variant of
Van der Elst (2021), which conditions on magnitude differences rather than modelling a threshold.
It is a different model and is not reachable from here.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
from pydantic import Field

from rupture.domain.common import RuptureModel

FloatArray = npt.NDArray[np.float64]


class StaiCoefficients(RuptureModel):
    """The two coefficients of ``Mc(t) = m_trigger - offset - decay * log10(t_days)``.

    ``citation`` is required and has no default. A completeness curve carried around without the
    measurement it came from is indistinguishable from an invented one at the point of use, and
    the whole reason ETAS-I exists in this repository is that unstated baselines are how the
    surveyed literature went wrong.
    """

    offset: float = Field(
        gt=0.0,
        description="Magnitude units the threshold sits above the trigger's at t = 1 day.",
    )
    decay: float = Field(
        gt=0.0, description="Magnitude units the threshold falls per decade of elapsed time."
    )
    citation: str = Field(min_length=1, description="Where these two numbers were measured.")
    notes: str | None = None

    def mc_after(self, trigger_magnitude: npt.ArrayLike, days_since: npt.ArrayLike) -> FloatArray:
        """The raw curve, capped at the trigger's own magnitude and *not* floored at background.

        The cap is the reason this diverges nowhere: ``log10(t)`` runs to minus infinity as the
        trigger is approached, and with these coefficients the curve crosses ``Mm`` about 0.09 s
        after it. An "unrecorded" event at or above the size of its own trigger is not a thing
        the catalogue can miss — it would be a mainshock in its own right — so the cap is the
        physically meaningful bound rather than an arbitrary clip, and it stops a nanosecond-scale
        timestamp collision from producing an infinite completeness.

        ``days_since`` must be strictly positive: an event does not raise the threshold for itself
        or for anything sharing its timestamp, and silently admitting ``0`` here would mean an
        event's own presence proved it undetectable.
        """
        m = np.asarray(trigger_magnitude, dtype=np.float64)
        dt = np.asarray(days_since, dtype=np.float64)
        if np.any(dt <= 0.0):
            msg = "days_since must be strictly positive (a trigger does not precede itself)"
            raise ValueError(msg)
        return np.minimum(m - self.offset - self.decay * np.log10(dt), m)

    def influence_days(self, trigger_magnitude: npt.ArrayLike, background_mc: float) -> FloatArray:
        """Elapsed days after which this trigger's curve has fallen back to ``background_mc``.

        Solving ``m - offset - decay*log10(t) = background_mc``. Beyond it the trigger contributes
        nothing, which is what makes :func:`stai_mc_current` cheap: each trigger is applied to a
        bounded slice of the catalogue rather than to all of it.
        """
        m = np.asarray(trigger_magnitude, dtype=np.float64)
        return np.asarray(
            np.power(10.0, (m - self.offset - background_mc) / self.decay), dtype=np.float64
        )


HELMSTETTER_2006 = StaiCoefficients(
    offset=4.5,
    decay=0.75,
    citation=(
        "Helmstetter, A., Kagan, Y. Y. & Jackson, D. D. (2006). Comparison of short-term and "
        "time-independent earthquake forecast models for southern California. BSSA 96(1), 90-106."
    ),
    notes=(
        "Mc(t) = Mm - 4.5 - 0.75*log10(t), t in days. Fitted to southern Californian sequences; "
        "applying it to another network is an assumption, not a measurement, and should be said "
        "out loud wherever it is done."
    ),
)
"""The default STAI law. Regional: see :attr:`StaiCoefficients.notes`."""


def stai_mc(
    trigger_magnitude: npt.ArrayLike,
    days_since: npt.ArrayLike,
    *,
    background_mc: float,
    coefficients: StaiCoefficients = HELMSTETTER_2006,
) -> FloatArray:
    """Completeness at ``days_since`` days after one trigger, floored at ``background_mc``.

    The floor is the network's long-run threshold: short-term incompleteness raises Mc, it never
    lowers it below what the network can do on a quiet day.
    """
    return np.maximum(coefficients.mc_after(trigger_magnitude, days_since), background_mc)


def stai_mc_current(
    days: npt.ArrayLike,
    magnitudes: npt.ArrayLike,
    *,
    background_mc: float,
    coefficients: StaiCoefficients = HELMSTETTER_2006,
) -> FloatArray:
    """Per-event completeness: the largest Mc any strictly earlier event imposes, floored.

    ``days`` are event times as floating-point days on any common origin — only differences are
    used — and ``magnitudes`` are the matching magnitudes. Input order is free; the result comes
    back in the order given. The output is the ``mc_current`` column
    :mod:`etas.inversion` requires when its metadata sets ``mc="var"``.

    Every event is a trigger: ETAS has no mainshocks, and a M5 inside a sequence blinds the
    network to its own aftershocks whether or not anybody called it a mainshock.

    Cost. The naive reading — each event against every earlier one — is quadratic and unusable on
    a 10^5-event catalogue. Two bounds make it near-linear instead, and both are exact rather than
    approximations:

    1. **Expiry.** A trigger stops mattering once its curve reaches ``background_mc``, after
       :meth:`StaiCoefficients.influence_days`. ``searchsorted`` turns that into an index range.
    2. **Domination.** If a later event is at least as large, it imposes at least as high a
       threshold at every instant after it — later start, so smaller elapsed time, so higher
       curve — and the earlier trigger can be cut off there. A long run of shrinking aftershocks
       therefore costs one pass, not one pass per member.

    What it does *not* know: only the events handed to it are triggers. A mainshock that was
    filtered out — below the cut, outside the region polygon, wrong event type — leaves no trace
    here, and its sequence will be modelled as complete when it was not.
    """
    t_in = np.asarray(days, dtype=np.float64)
    m_in = np.asarray(magnitudes, dtype=np.float64)
    if t_in.ndim != 1 or m_in.ndim != 1:
        msg = "days and magnitudes must be one-dimensional"
        raise ValueError(msg)
    if t_in.shape != m_in.shape:
        msg = f"days {t_in.shape} and magnitudes {m_in.shape} must have the same length"
        raise ValueError(msg)
    n = t_in.size
    out = np.full(n, float(background_mc), dtype=np.float64)
    if n == 0:
        return out
    if not np.all(np.isfinite(t_in)) or not np.all(np.isfinite(m_in)):
        msg = "days and magnitudes must be finite"
        raise ValueError(msg)

    order = np.argsort(t_in, kind="stable")
    t = t_in[order]
    m = m_in[order]
    sorted_out = np.full(n, float(background_mc), dtype=np.float64)

    horizon = coefficients.influence_days(m, background_mc)
    # Time of the first later event that dominates this one; +inf when none does.
    dom = _next_ge_index(m)
    dom_time = np.where(dom < n, t[np.minimum(dom, n - 1)], np.inf)
    # side="right" on both ends: an event never triggers itself, nor anything sharing its instant.
    lo_all = np.searchsorted(t, t, side="right")
    hi_all = np.searchsorted(t, np.minimum(t + horizon, dom_time), side="right")

    for j in np.flatnonzero(hi_all > lo_all):
        lo, hi = int(lo_all[j]), int(hi_all[j])
        contribution = coefficients.mc_after(m[j], t[lo:hi] - t[j])
        np.maximum(sorted_out[lo:hi], contribution, out=sorted_out[lo:hi])

    out[order] = sorted_out
    return out


def _next_ge_index(magnitudes: FloatArray) -> npt.NDArray[np.int64]:
    """For each index, the first later index whose magnitude is >= it; ``len`` if there is none.

    The classic monotone-stack pass. Written as an explicit loop because numpy has no vectorised
    form of it; it is amortised O(n) and costs well under a second on a 10^5-event catalogue.
    """
    n = magnitudes.size
    out = np.full(n, n, dtype=np.int64)
    stack: list[int] = []
    for i in range(n):
        mi = magnitudes[i]
        while stack and magnitudes[stack[-1]] <= mi:
            out[stack.pop()] = i
        stack.append(i)
    return out
