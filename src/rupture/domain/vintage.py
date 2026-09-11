"""Data vintage: when a record came to say what it says.

A catalogue is not a fixed object. Magnitudes are revised, locations move when more picks
arrive, and an event that was automatic at the time is reviewed months later. Rupture's
evaluation is time-forward on ``origin_time`` and has been since the protocol was written, and
that is necessary and not sufficient: **the value at time *t* may not have existed at time *t*.**

ADR-0054 calls this a leakage class and the ledger records that nobody had measured it. The
measurement is uncomfortable. On the committed California fixture every one of the 1,433 events
carries a record last modified after its own origin — a median of 192 days after — and 69 of the
217 events available to the 2019-07-01 fit were last modified after that cutoff. Every existing
leakage assertion passes on all of it, because they compare ``origin_time`` and nothing else.

**What this module can and cannot establish.** ComCat gives one vintage stamp, the time of the
most recent change. That is enough to say *this record is not provably the record that existed at
t*. It is not enough to reconstruct what the record said at *t*, because the event was in the
catalogue before it was last touched, with values nobody kept. So the honest quantity here is
**exposure** — how much of a result rests on records of unproven vintage — and not the skill
difference, which needs archived vintages and is named as the next step in ADR-0064.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from rupture.domain.common import RuptureModel, UTCDatetime


class VintagePolicy(StrEnum):
    """What to do with a record whose vintage is unknown.

    There is no safe default, which is why this is never implicit. ``EXCLUDE_UNKNOWN`` is the
    provable view and will empty a catalogue that carries no vintage at all (ISC, GCMT today).
    ``INCLUDE_UNKNOWN`` is what every result in this repository already assumes; naming it makes
    the assumption visible instead of ambient.
    """

    EXCLUDE_UNKNOWN = "exclude-unknown"
    INCLUDE_UNKNOWN = "include-unknown"


class VintageSummary(RuptureModel):
    """How much of a catalogue slice is of proven vintage, and how late the rest arrived."""

    n_events: int = Field(ge=0)
    n_with_available_time: int = Field(ge=0)
    n_available_by: int | None = Field(
        default=None,
        ge=0,
        description="Events provably available by the reference instant, if one was given.",
    )
    n_revised_after: int | None = Field(
        default=None,
        ge=0,
        description="Events whose record was last modified at or after the reference instant.",
    )
    reference_time: UTCDatetime | None = None
    lag_days_median: float | None = Field(
        default=None, description="Median available_time - origin_time, in days."
    )
    lag_days_p90: float | None = None
    lag_days_max: float | None = None

    @property
    def coverage(self) -> float:
        """Fraction of events carrying any vintage at all."""
        return 0.0 if self.n_events == 0 else self.n_with_available_time / self.n_events

    @property
    def exposed_fraction(self) -> float | None:
        """Fraction of events whose record is not provably as-of the reference instant."""
        if self.n_revised_after is None or self.n_events == 0:
            return None
        return self.n_revised_after / self.n_events

    def render(self) -> str:
        """One line for a gate or a CLI."""
        bits = [f"{self.n_events} event(s)", f"vintage on {self.coverage:.0%}"]
        if self.reference_time is not None and self.n_revised_after is not None:
            bits.append(
                f"{self.n_revised_after} ({self.exposed_fraction:.0%}) last modified at or after "
                f"{self.reference_time.isoformat()}"
            )
        if self.lag_days_median is not None:
            bits.append(
                f"lag median {self.lag_days_median:.1f} d, p90 {self.lag_days_p90:.1f} d, "
                f"max {self.lag_days_max:.1f} d"
            )
        return "; ".join(bits)
