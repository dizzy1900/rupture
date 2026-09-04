# ADR-0050 — a documented hook for a learned global ground-failure model, not trained here

- **Status:** accepted
- **Date:** 2026-09-03
- **Relates to:** ADR-0022 (leakage engineering for learned models), ADR-0026 (USGS ground-failure
  models), ADR-0035 (the models/data seam)

## Context

The cascade layer ships two published, empirically fitted models: Nowicki Jessee et al. (2018) for
landslide areal coverage and Zhu et al. (2017) for liquefaction. Both are logistic regressions on
shaking plus static conditioning rasters, and both are evaluated — not fitted — here.

The brief asks for something in addition: **leave a documented hook for a learned global model —
the 2025 deep-learning generation of earthquake-triggered landslide models — as the v1 candidate,
and do not train it.** That instruction has two halves, and both matter. A seam that is never
written down means the next person guesses where a learned model plugs in, what it must emit, and
what it must survive. A seam that quietly acquires a half-trained model means rupture is shipping a
susceptibility product nobody validated.

There is also a constraint peculiar to this repository: rupture does not restate a citation it has
not read against a primary source. `docs/CASCADE.md` §1.4 already refuses to reconcile the
interaction-sign discrepancy for exactly that reason. The 2025 model named in the brief is not in
this implementation's hands, and inventing a plausible-looking bibliography entry for it would be
the same failure the rest of this layer is careful to avoid.

## Decision

**1. The hook is a module, not a promise in prose.** `src/rupture/cascade/learned.py` exists, is
importable, reserves the model id `learned_global_landslide_v1`, and raises `NotImplementedError`
on construction with the contract in the message. `docs/CASCADE.md` §9 states the same thing for a
reader who never opens the code.

**2. Nothing answers to the reserved id.** It is deliberately absent from
`rupture.cascade.models.MODEL_CLASSES` and `ALIASES`, so `build("learned_global_landslide_v1")`
raises. A test asserts that absence. A registered stub would be an untrained model shipping.

**3. What an implementation owes.** Recorded in `learned.REQUIRED_OF_AN_IMPLEMENTATION` and
asserted by `tests/unit/cascade/test_learned_hook.py`:

- satisfy `rupture.ports.cascade.CascadeModel` — `model_id`, `model_version`, `source_refs`, and
  `evaluate(field, *, scenario_id) -> GroundFailureField`;
- emit a `GroundFailureField` whose cells are probabilities or areal fractions in `[0, 1]`, whose
  `provenance` names the weights (source, URL, sha256, licence), and whose `notes` still carry the
  susceptibility label;
- name every covariate it consumes. The covariate rule of `rupture.cascade.covariates` is
  unchanged: sourced with provenance, or absent and declared. A network that silently imputes a
  missing raster is not admissible;
- ship or fetch weights with provenance. Weights are data and obey the data rules;
- if it is **fitted or fine-tuned in this repository**, obey ADR-0022: the events its training
  inventories come from are disjoint from the events it is scored on, cutoffs are half-open
  `[from, to)`, and the assertion lives in the test that fits it. (Evaluating a model fitted
  elsewhere carries no cutoff, which is why the two incumbents carry none.);
- be scored by the same code on the same targets — `adapters.cascade.reproduction` against the
  published USGS Gorkha rasters, and `adapters.cascade.chamoli` on the scenario route — and report
  the same comparisons the incumbents report;
- be registered under its own id, and take the `landslide` alias **only** after it beats the
  incumbent on those targets. A learned model is not adopted because it is learned.

**4. rupture does not name the paper.** The brief identifies the v1 candidate as the 2025
deep-learning earthquake-triggered landslide model; this implementation does not have that paper's
primary source and will not restate a citation it has not read. Whoever implements the hook commits
the citation, the weights and the licence with the code, and supersedes this ADR with the one that
adopts it.

## Consequences

- The seam is discoverable from the package and from the documentation, and a reader who greps for
  a learned model finds a statement rather than silence.
- rupture ships no learned ground-failure model and makes no claim about one. `RELEASE_STATUS.md`
  and `docs/CASCADE.md` §8 say so.
- The Gorkha and Chamoli cases become the acceptance targets for the eventual implementation,
  which is the point of having built them first.

## Alternatives rejected

- **Nothing but a paragraph in `docs/CASCADE.md`.** Cheaper, and it is what the audit found
  missing: prose alone is not greppable from the code and drifts from it.
- **A registered stub returning zeros.** It would make `build("learned...")` succeed and produce a
  field of zeros carrying a model id — an untrained model shipping, with a susceptibility record to
  match. Refused.
- **Naming and citing the 2025 model from memory.** Refused; see decision 4.
