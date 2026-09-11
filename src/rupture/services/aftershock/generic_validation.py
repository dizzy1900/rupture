"""Measure the generic-prior forecast against the committed ETAS validation, window for window.

The claim this module exists to test is the one in ``RELEASE_STATUS.md``: the aftershock service
under-forecasts the first day by 3-12x because it has no generic multi-sequence parameters. The
evidence for it is committed -- ``reports/aftershock/gorkha.json`` and ``kahramanmaras.json`` hold,
for every (issue time, horizon) window they scored, the ETAS expected count above the region's
target threshold and the number of events that actually fell in that window. So the before/after
can be computed without re-running ETAS at all: take the *same* windows and the *same* observed
counts, and put the Reasenberg-Jones generic and Bayesian expected counts beside the ETAS ones.

**What is and is not a like-for-like comparison.** The observed counts come from the committed
reports, so both models are scored against identical target slices. What differs:

* ETAS's number is the mass of a *gridded* forecast summed over cells; the R-J number is
  zone-wide and aspatial. They are both "expected events at or above the target threshold, in this
  zone, in this window", but only one of them can say where.
* R-J attributes every aftershock to the mainshock. A window containing a large aftershock's own
  sequence -- Gorkha's 30-day windows contain the M7.3 of 12 May -- is one R-J structurally cannot
  forecast, and the numbers there should be read as the model being asked the wrong question.
* The observed count is every qualifying event in the zone, including the background rate, which
  R-J has no term for. After an M7.8 that is a small contamination; at +30 d it is less small.

Nothing here refits anything, nothing here is tuned, and no number in the output is typed in: the
ETAS column and the observed column are read from the committed JSON, and the R-J columns are
computed from the committed catalogue slice and the published generic table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rupture.domain import Catalog
from rupture.services.aftershock.generic import (
    GENERIC_SOURCE,
    APosterior,
    GenericRJParameters,
    generic_for_region,
    generic_prior,
    regime_for_region,
    sequence_observation,
    update,
)
from rupture.services.aftershock.sequences import (
    Mainshock,
    SequenceSpec,
    load_parent_region,
    load_sequence_catalog,
    sequence_spec,
)

REPORTS_REL = Path("reports") / "aftershock"
SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True, slots=True)
class CommittedWindow:
    """One scored window as the committed report recorded it."""

    issue_label: str
    horizon: str
    issue_time: datetime
    window_end: datetime
    etas_expected: float
    observed: int
    n_sequence_events: int


@dataclass(frozen=True, slots=True)
class GenericWindow:
    """The committed window with the generic and Bayesian expected counts added.

    ``ratio_*`` is observed over expected: above 1 the model under-forecasts, below 1 it
    over-forecasts. It is reported as ``None`` when nothing was observed, because a ratio against
    zero says nothing about either model and printing ``0.0`` invites reading it as a success.
    """

    window: CommittedWindow
    t1_days: float
    t2_days: float
    n_used_in_likelihood: int
    generic_expected: float
    bayesian_expected: float
    bayesian_probability: float
    posterior_mean_a: float

    @property
    def ratio_etas(self) -> float | None:
        return _ratio(self.window.observed, self.window.etas_expected)

    @property
    def ratio_generic(self) -> float | None:
        return _ratio(self.window.observed, self.generic_expected)

    @property
    def ratio_bayesian(self) -> float | None:
        return _ratio(self.window.observed, self.bayesian_expected)


@dataclass(frozen=True, slots=True)
class GenericComparison:
    """Everything the comparison produced for one sequence."""

    sequence_id: str
    mainshock_event_id: str
    mainshock_magnitude: float
    regime: str
    parameters: GenericRJParameters
    b_value: float
    target_min_magnitude: float
    likelihood_min_magnitude: float
    windows: list[GenericWindow]
    source: str = GENERIC_SOURCE


def _ratio(observed: int, expected: float) -> float | None:
    if observed == 0 or expected <= 0.0:
        return None
    return observed / expected


def load_committed_windows(sequence_id: str, repo_root: Path) -> list[CommittedWindow]:
    """Read the scored windows out of ``reports/aftershock/<sequence_id>.json``.

    Read-only, and deliberately so: this module measures against the committed evidence and must
    not be able to change it.
    """
    path = Path(repo_root) / REPORTS_REL / f"{sequence_id}.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: list[CommittedWindow] = []
    for w in payload["windows"]:
        out.append(
            CommittedWindow(
                issue_label=w["issue_label"],
                horizon=w["horizon"],
                issue_time=_parse(w["issue_time"]),
                window_end=_parse(w["window_end"]),
                etas_expected=float(w["total_expected_above_target"]),
                observed=int(w["n_observed_above_target"]),
                n_sequence_events=int(w["n_sequence_events"]),
            )
        )
    return out


def _parse(text: str) -> datetime:
    value = datetime.fromisoformat(text)
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def posterior_at(
    *,
    catalog: Catalog,
    mainshock: Mainshock,
    issue_time: datetime,
    parameters: GenericRJParameters,
    likelihood_min_magnitude: float,
    b_value: float | None = None,
    start_offset: timedelta = timedelta(0),
) -> tuple[APosterior, int]:
    """The posterior over ``a`` an operator would hold at ``issue_time``, and the count behind it.

    The history is truncated strictly before ``issue_time`` here rather than being trusted, for the
    same reason the ETAS path asserts it: a Bayesian update fed one aftershock from the future is a
    forecast that cannot be falsified.
    """
    prior = generic_prior(parameters, mainshock_magnitude=mainshock.magnitude, b_value=b_value)
    observation = sequence_observation(
        catalog.before(issue_time),
        mainshock=mainshock,
        issue_time=issue_time,
        min_magnitude=likelihood_min_magnitude,
        start_offset=start_offset,
    )
    return update(prior, observation), observation.n_events


def compare_sequence(
    name: str,
    repo_root: Path,
    *,
    use_region_b_value: bool = False,
    likelihood_min_magnitude: float | None = None,
    start_offset: timedelta = timedelta(0),
) -> GenericComparison:
    """Put the generic and Bayesian counts beside the committed ETAS counts for one sequence.

    ``use_region_b_value`` swaps the generic ``b = 1.0`` for the parent region's published
    long-run b. The generic ``a`` was estimated at ``b = 1.0``, so this is not a free choice and
    the default is to leave the table self-consistent; the switch exists so the sensitivity can be
    measured rather than asserted. ``likelihood_min_magnitude`` defaults to the region's Mc, which
    is the lowest threshold at which the committed catalogue is claimed to be complete.
    """
    spec: SequenceSpec = sequence_spec(name)
    catalog = load_sequence_catalog(spec, repo_root)
    region = load_parent_region(spec, repo_root)
    parameters = generic_for_region(region)
    mc = region.mc.mc if region.mc is not None else region.target_min_magnitude
    floor = mc if likelihood_min_magnitude is None else likelihood_min_magnitude
    b_override = region.mc.b_value if (use_region_b_value and region.mc is not None) else None
    b_used = parameters.b_value if b_override is None else b_override

    rows: list[GenericWindow] = []
    prior = generic_prior(
        parameters, mainshock_magnitude=spec.mainshock.magnitude, b_value=b_override
    )
    for window in load_committed_windows(spec.id, repo_root):
        posterior, n_used = posterior_at(
            catalog=catalog,
            mainshock=spec.mainshock,
            issue_time=window.issue_time,
            parameters=parameters,
            likelihood_min_magnitude=floor,
            b_value=b_override,
            start_offset=start_offset,
        )
        t1 = (window.issue_time - spec.mainshock.origin_time).total_seconds() / SECONDS_PER_DAY
        t2 = (window.window_end - spec.mainshock.origin_time).total_seconds() / SECONDS_PER_DAY
        rows.append(
            GenericWindow(
                window=window,
                t1_days=t1,
                t2_days=t2,
                n_used_in_likelihood=n_used,
                generic_expected=prior.expected_count(
                    min_magnitude=region.target_min_magnitude, t1_days=t1, t2_days=t2
                ),
                bayesian_expected=posterior.expected_count(
                    min_magnitude=region.target_min_magnitude, t1_days=t1, t2_days=t2
                ),
                bayesian_probability=posterior.probability_at_least_one(
                    min_magnitude=region.target_min_magnitude, t1_days=t1, t2_days=t2
                ),
                posterior_mean_a=posterior.mean_a(),
            )
        )
    return GenericComparison(
        sequence_id=spec.id,
        mainshock_event_id=spec.mainshock.event_id,
        mainshock_magnitude=spec.mainshock.magnitude,
        regime=regime_for_region(region),
        parameters=parameters,
        b_value=b_used,
        target_min_magnitude=region.target_min_magnitude,
        likelihood_min_magnitude=floor,
        windows=rows,
    )


def render_comparison(comparison: GenericComparison) -> str:
    """A markdown table of the before/after, with the ratios in both directions left visible."""
    p = comparison.parameters
    lines = [
        f"## {comparison.sequence_id} - generic Reasenberg-Jones against the committed ETAS run",
        "",
        f"- mainshock `{comparison.mainshock_event_id}` M{comparison.mainshock_magnitude:.1f}; "
        f"target threshold M{comparison.target_min_magnitude}",
        f"- regime `{comparison.regime}` ({p.description}): a_mean {p.a_mean}, "
        f"sigma_a {p.a_sigma_for(comparison.mainshock_magnitude):.3f}, b {comparison.b_value:.3f}, "
        f"p {p.p_value}, c {p.c_value_days} d",
        f"- likelihood counts events at or above M{comparison.likelihood_min_magnitude}",
        f"- generic parameters: {comparison.source}",
        "",
        "| issue | horizon | observed | ETAS lambda | generic lambda | Bayesian lambda | "
        "obs/ETAS | obs/generic | obs/Bayes | n in likelihood |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in comparison.windows:
        lines.append(
            f"| +{row.window.issue_label} | {row.window.horizon} | {row.window.observed} | "
            f"{row.window.etas_expected:.3g} | {row.generic_expected:.3g} | "
            f"{row.bayesian_expected:.3g} | {_fmt(row.ratio_etas)} | {_fmt(row.ratio_generic)} | "
            f"{_fmt(row.ratio_bayesian)} | {row.n_used_in_likelihood} |"
        )
    lines.append("")
    return "\n".join(lines)


def _fmt(ratio: float | None) -> str:
    return "n/a" if ratio is None else f"{ratio:.2f}"
