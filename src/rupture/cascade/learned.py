"""The documented seam for a **learned** global ground-failure model. Not trained here.

The brief asks the cascade layer to leave a hook for a learned global earthquake-triggered
landslide model — the 2025 deep-learning generation of them — as the v1 candidate, and to **not
train it**. This module is that hook: a contract, an unimplemented class that names it, and a
registry entry that stays absent until someone fills it. ADR-0042 records the decision.

Nothing in rupture is trained on landslide inventories today, and nothing here pretends to be.
:class:`LearnedGroundFailureModel` raises :class:`NotImplementedError` on construction; the point
of it existing is that the next person does not have to guess where a learned model plugs in, what
it must emit, or what it must survive before it is allowed to be the default.

What the implementer must do
----------------------------

1. **Implement the port.** Satisfy :class:`rupture.ports.cascade.CascadeModel`: carry ``model_id``,
   ``model_version`` and ``source_refs``, and implement
   ``evaluate(field: GroundMotionField, *, scenario_id: str) -> GroundFailureField``. The two
   published models do this through :class:`rupture.cascade.models.LogisticGroundFailureModel`; a
   learned model does not have to inherit from it, and probably should not.
2. **Emit the same record.** A :class:`~rupture.domain.cascade.GroundFailureField` with
   ``kind``, ``model_id``, ``model_version``, ``cell_size_deg``, ``shaking_source``, a
   :class:`~rupture.domain.common.Provenance` naming the weights (source, URL, sha256, licence),
   and ``notes`` carrying the susceptibility label. Cells hold a probability or areal fraction in
   ``[0, 1]``; a model that emits a class label must state the mapping in ``notes``.
3. **Declare its inputs.** State every covariate the network consumes and where each comes from.
   rupture's covariate rule (:mod:`rupture.cascade.covariates`) is unchanged and applies in full:
   a covariate is sourced with provenance, or it is absent and the output says so. A learned model
   that quietly imputes a missing raster is not admissible.
4. **Ship the weights with provenance, or fetch them loudly.** Weights are data. They carry a
   source, a URL, a sha256 and a licence, exactly as a fixture does; the model does not run on
   weights whose origin is unknown.
5. **Respect the leakage rule (ADR-0022).** The published models are fitted elsewhere and rupture
   only evaluates them, so no cutoff applies. A model *fitted* in this repository, or fine-tuned
   in it, is a different object: the events its training inventories come from must be disjoint
   from the events it is scored on, the cutoff is half-open ``[from, to)``, and the assertion
   belongs in the test that fits it.
6. **Be scored on the same targets, by the same code.** Run it through
   :mod:`rupture.adapters.cascade.reproduction` against the published USGS Gorkha rasters, and
   through :mod:`rupture.adapters.cascade.chamoli` for the scenario route, and report the same
   comparisons the incumbent reports. A learned model is not adopted because it is learned.
7. **Register it.** Add the class to ``MODEL_CLASSES`` and, if it is to have a friendly name, to
   ``ALIASES`` in :mod:`rupture.cascade.models`, and extend
   :func:`rupture.cascade.models.build`. Until it beats the incumbent on the published targets it
   is registered under its own id and is **not** the ``landslide`` alias.

What rupture deliberately does not do here
------------------------------------------

It does not name a paper. The brief identifies the v1 candidate as the 2025 deep-learning
earthquake-triggered landslide model, and rupture does not have that paper's primary source in
hand; restating a citation it has not read would be exactly the kind of borrowed authority
``docs/CASCADE.md`` section 1.4 already refuses elsewhere. The implementer commits the citation,
the weights and their licence together with the code, and ADR-0042 is superseded by the ADR that
adopts it.
"""

from __future__ import annotations

from typing import Never

from rupture.domain.cascade import CascadeKind

MODEL_ID = "learned_global_landslide_v1"
"""The reserved id. It is not in ``MODEL_CLASSES``: nothing answers to it yet, by design."""

KIND = CascadeKind.LANDSLIDE

STATUS = (
    "hook only — rupture does not train, fine-tune, ship or evaluate a learned ground-failure "
    "model. See ADR-0042 and docs/CASCADE.md section 9."
)

REQUIRED_OF_AN_IMPLEMENTATION: tuple[str, ...] = (
    "satisfies rupture.ports.cascade.CascadeModel",
    "emits GroundFailureField with model_id, model_version, provenance and the susceptibility "
    "label in notes",
    "names every covariate it consumes, each sourced with provenance or declared absent",
    "ships weights with source, URL, sha256 and licence, or fetches them loudly",
    "obeys the leakage rule of ADR-0022 if it is fitted or fine-tuned in this repository",
    "is scored against the published Gorkha rasters by adapters.cascade.reproduction and on the "
    "scenario route by adapters.cascade.chamoli, and reports the same comparisons",
    "is registered in rupture.cascade.models.MODEL_CLASSES under its own id, and takes the "
    "'landslide' alias only after it beats the incumbent on those targets",
)


class LearnedGroundFailureModel:
    """Placeholder for the learned global model. Constructing one raises, on purpose.

    It exists so the seam is discoverable from the package rather than only from a document, and
    so a reader who greps for a learned model finds this statement instead of silence.
    """

    model_id = MODEL_ID
    model_version = "unimplemented"
    source_refs: tuple[str, ...] = ()

    def __init__(self, *_args: object, **_kwargs: object) -> Never:
        msg = (
            f"{MODEL_ID} is a documented hook, not an implementation: {STATUS} "
            f"An implementation must: " + "; ".join(REQUIRED_OF_AN_IMPLEMENTATION) + "."
        )
        raise NotImplementedError(msg)
