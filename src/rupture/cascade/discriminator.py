"""Client for the ``SourceTypeAssessment`` file contract shared with the sibling ``serac``.

The contract (``contracts/source-type-assessment.v0.json``) carries, per event, the probability
that a catalogued "earthquake" is really a mass movement. serac produces them from waveform
evidence; rupture consumes them as files and never as code.

What this module does with one:

* an event whose ``p_mass_movement`` is at or above the acceptance threshold is retagged
  :attr:`~rupture.domain.event.EventType.LANDSLIDE`, which is exactly what
  :meth:`~rupture.domain.catalog.Catalog.earthquakes` already excludes, so the event leaves the
  tectonic ETAS fit and joins the cascade layer;
* every reclassification is counted and attributed, so a fit's inputs can be reconciled with the
  catalogue it came from;
* an event **already** tagged ``landslide`` by the source catalogue (ComCat ``type=landslide``,
  e.g. ``us7000tbwb``) is counted separately: it was never in the tectonic fit, and no
  discriminator was needed to keep it out.

The retagging is deliberately one-way. rupture will move an event out of the tectonic set on
serac's evidence; it will not move one back in, because a false negative from a discriminator
would put a mass movement into an earthquake rate model, and that is the failure mode this
whole exchange exists to prevent.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from rupture.domain.catalog import Catalog
from rupture.domain.event import Event, EventType
from rupture.domain.source_type import SourceTypeAssessment

DEFAULT_ACCEPTANCE_THRESHOLD = 0.5
"""``p_mass_movement`` at or above which rupture accepts serac's assessment.

0.5 is "more likely than not". It is a decision threshold, not a physical constant, and it is
the caller's to change; the accounting always reports which threshold was used and how many
events sat close to it.
"""

BORDERLINE_BAND = 0.1
"""Assessments within this much of the threshold are reported as borderline, not hidden."""


@dataclass(frozen=True, slots=True)
class Reclassification:
    """One event moved out of the tectonic set, with the evidence that moved it."""

    event_id: str
    from_type: EventType
    to_type: EventType
    p_mass_movement: float
    classifier: str
    evidence: tuple[str, ...]


@dataclass(slots=True)
class DiscriminatorAccounting:
    """What the discriminator client did to a catalogue. Every number is reported, not summarised.

    ``already_tagged`` are events the *source catalogue* had already typed as a mass movement —
    for those, rupture's catalogue layer was already keeping them out of the tectonic fit and the
    discriminator changed nothing. ``reclassified`` are the ones serac's evidence moved.
    """

    threshold: float
    n_events: int = 0
    n_assessments_read: int = 0
    n_assessments_matched: int = 0
    n_assessments_unmatched: int = 0
    already_tagged: list[str] = field(default_factory=list)
    reclassified: list[Reclassification] = field(default_factory=list)
    borderline: list[str] = field(default_factory=list)
    unmatched_event_ids: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def n_reclassified(self) -> int:
        return len(self.reclassified)

    @property
    def n_already_tagged(self) -> int:
        return len(self.already_tagged)

    @property
    def n_excluded_from_tectonic_fit(self) -> int:
        """Events the tectonic ETAS fit will not see, from either route."""
        return self.n_reclassified + self.n_already_tagged

    def as_dict(self) -> dict[str, object]:
        return {
            "threshold": self.threshold,
            "n_events": self.n_events,
            "n_assessments_read": self.n_assessments_read,
            "n_assessments_matched": self.n_assessments_matched,
            "n_assessments_unmatched": self.n_assessments_unmatched,
            "n_already_tagged_by_source_catalogue": self.n_already_tagged,
            "already_tagged_event_ids": sorted(self.already_tagged),
            "n_reclassified_by_discriminator": self.n_reclassified,
            "reclassified": [
                {
                    "event_id": r.event_id,
                    "from": r.from_type.value,
                    "to": r.to_type.value,
                    "p_mass_movement": r.p_mass_movement,
                    "classifier": r.classifier,
                    "evidence": list(r.evidence),
                }
                for r in self.reclassified
            ],
            "n_excluded_from_tectonic_fit": self.n_excluded_from_tectonic_fit,
            "borderline_event_ids": sorted(self.borderline),
            "unmatched_assessment_event_ids": sorted(self.unmatched_event_ids),
            "sources": sorted(self.sources),
        }

    def render(self) -> list[str]:
        lines = [
            f"discriminator: {self.n_assessments_read} assessment(s) read from "
            f"{len(self.sources)} file(s), threshold p_mass_movement >= {self.threshold}",
            f"discriminator: {self.n_already_tagged} event(s) already tagged landslide by the "
            f"source catalogue (never in the tectonic fit)",
            f"discriminator: {self.n_reclassified} event(s) reclassified by serac's evidence",
            f"discriminator: {self.n_excluded_from_tectonic_fit} of {self.n_events} event(s) "
            f"excluded from tectonic fitting and counted in the cascade layer",
        ]
        if self.borderline:
            lines.append(
                f"discriminator: {len(self.borderline)} assessment(s) within "
                f"{BORDERLINE_BAND} of the threshold: {', '.join(sorted(self.borderline))}"
            )
        if self.unmatched_event_ids:
            lines.append(
                f"discriminator: {self.n_assessments_unmatched} assessment(s) matched no "
                f"catalogue event: {', '.join(sorted(self.unmatched_event_ids))}"
            )
        return lines


def read_assessments(path: Path) -> tuple[tuple[SourceTypeAssessment, ...], tuple[str, ...]]:
    """Read one file, or every ``*.json`` under one directory, as ``SourceTypeAssessment``.

    Accepts a single object, a JSON array, or ``{"assessments": [...]}``. A file that does not
    validate against the contract is an error: rupture does not silently drop a record it cannot
    read, because a dropped assessment leaves a mass movement in the tectonic fit.
    """
    paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
    if not paths:
        msg = f"no SourceTypeAssessment files under {path}"
        raise FileNotFoundError(msg)
    out: list[SourceTypeAssessment] = []
    for candidate in paths:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        records = (
            payload.get("assessments", [])
            if isinstance(payload, dict) and "assessments" in payload
            else payload
            if isinstance(payload, list)
            else [payload]
        )
        for record in records:
            out.append(SourceTypeAssessment.model_validate(record))
    return tuple(out), tuple(str(p) for p in paths)


def _candidate_keys(event: Event) -> set[str]:
    """The identifiers an assessment may address this event by."""
    return {
        event.id,
        event.source_event_id,
        f"{event.source_catalog}:{event.source_event_id}",
        *event.contributing_ids,
    }


def apply_assessments(
    catalog: Catalog,
    assessments: Iterable[SourceTypeAssessment],
    *,
    threshold: float = DEFAULT_ACCEPTANCE_THRESHOLD,
    sources: Sequence[str] = (),
) -> tuple[Catalog, DiscriminatorAccounting]:
    """Retag events serac assesses as mass movements, and account for every one.

    Returns a new catalogue (nothing mutates) and the accounting. Events the source catalogue
    already typed as a mass movement are counted but not touched.
    """
    accounting = DiscriminatorAccounting(threshold=threshold, sources=list(sources))
    accounting.n_events = len(catalog.events)
    by_key: dict[str, Event] = {}
    for event in catalog.events:
        for key in _candidate_keys(event):
            by_key.setdefault(key, event)
        if event.event_type is EventType.LANDSLIDE:
            accounting.already_tagged.append(event.id)

    retag: dict[str, Reclassification] = {}
    for assessment in assessments:
        accounting.n_assessments_read += 1
        event = by_key.get(assessment.event_id)
        if event is None:
            accounting.n_assessments_unmatched += 1
            accounting.unmatched_event_ids.append(assessment.event_id)
            continue
        accounting.n_assessments_matched += 1
        if abs(assessment.p_mass_movement - threshold) <= BORDERLINE_BAND:
            accounting.borderline.append(event.id)
        if assessment.p_mass_movement < threshold:
            continue
        if event.event_type is EventType.LANDSLIDE:
            continue  # already out of the tectonic set; counted under already_tagged
        retag[event.id] = Reclassification(
            event_id=event.id,
            from_type=event.event_type,
            to_type=EventType.LANDSLIDE,
            p_mass_movement=assessment.p_mass_movement,
            classifier=f"{assessment.classifier_id}@{assessment.classifier_version}",
            evidence=assessment.evidence,
        )

    accounting.reclassified = [retag[k] for k in sorted(retag)]
    if not retag:
        return catalog, accounting
    events = tuple(
        event.model_copy(update={"event_type": EventType.LANDSLIDE})
        if event.id in retag
        else event
        for event in catalog.events
    )
    updated = catalog.model_copy(
        update={
            "events": events,
            "notes": " | ".join(
                filter(
                    None,
                    [
                        catalog.notes,
                        f"{len(retag)} event(s) retagged landslide from serac "
                        f"SourceTypeAssessment records at p_mass_movement >= {threshold}",
                    ],
                )
            ),
        }
    )
    return updated, accounting


def apply_from_export(
    catalog: Catalog,
    export_dir: Path,
    *,
    threshold: float = DEFAULT_ACCEPTANCE_THRESHOLD,
    subdirectory: str = "source-type-assessments",
) -> tuple[Catalog, DiscriminatorAccounting]:
    """Apply every assessment serac has exported under ``SERAC_EXPORT_DIR``.

    Looks in ``<export_dir>/<subdirectory>/`` and falls back to ``<export_dir>`` itself. When
    serac has exported nothing, the catalogue comes back unchanged and the accounting says so —
    which is the current state of the world, and is not an error.
    """
    for candidate in (export_dir / subdirectory, export_dir):
        if candidate.is_dir() and any(candidate.glob("*.json")):
            assessments, paths = read_assessments(candidate)
            return apply_assessments(
                catalog, assessments, threshold=threshold, sources=paths
            )
    accounting = DiscriminatorAccounting(threshold=threshold)
    accounting.n_events = len(catalog.events)
    accounting.already_tagged = [
        e.id for e in catalog.events if e.event_type is EventType.LANDSLIDE
    ]
    return catalog, accounting
