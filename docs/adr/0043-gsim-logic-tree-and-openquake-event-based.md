# ADR-0043: A GSIM logic tree, and the engine's event-based path

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)
- **Extends:** ADR-0020 (two ground-motion adapters), ADR-0033 (GSIM coefficient provenance)

## Context

Every loss figure rupture had reported was conditional on **one** ground-shaking model. That is
the narrowest assumption in the whole chain and rarely the most defensible: `docs/RISK.md` § 8
already showed that swapping BSSA14 for the BC Hydro interface model moves the MHT median PGA from
0.53 g to 0.78 g and the expected loss by 21 %. The brief asked for a **GMPE logic tree per
OpenQuake regional practice, documented**, which is how a hazard model carries that epistemic
uncertainty rather than hiding it behind a default. What existed instead was a `--gsim` flag and an
`--allow-tectonic-mismatch` escape hatch.

Separately, the port's own docstring promised "scenario and event-based" and exposed only
`scenario()`; `calculation_mode = event_based` appeared nowhere. That is the calculator the
engine uses to get annualised loss out of a source model, so the authoritative path could only
ever reproduce what the native path already did for a fixed rupture.

## Decision

### 1. `GsimLogicTree` is a domain object, and both engines evaluate it

`rupture.domain.groundmotion` gains `GsimBranch` (a GSIM, a weight, a rationale, sources) and
`GsimLogicTree` (branches, tectonic region, `provenance` on the *weights*, and an `excluded` tuple
naming models a fuller tree would carry). Weights must sum to one; a tree claiming
`ModelProvenance.PUBLISHED` weights must cite them.

`NativeGsimEngine.scenario_logic_tree` allocates realisations between branches by
**largest-remainder**, not by sampling: the weights are then honoured exactly rather than in
expectation, two runs with the same seed agree, and no branch is ever silently dropped (fewer
realisations than branches is refused). The resulting field's `gsim` is `logic-tree:<id>`, never a
model name, and its `notes` list every branch and its realisation count, so a mixed field cannot
be mistaken for a single-model one. `RunConfig.gsim_logic_tree` threads it through every path in
the risk layer via one helper, `loss.ground_motion`, so a run configured with a tree gets one
everywhere rather than in whichever module remembered to ask.

The OpenQuake side writes the same object as `gsim_logic_tree.xml`
(`logic_trees.gsim_logic_tree_nrml`), so the two engines cannot drift apart by editing one.

The port is split into three protocols — `GroundMotionEngine`, `LogicTreeGroundMotionEngine`,
`EventBasedGroundMotionEngine` — rather than growing one. Forcing a single protocol would have made
the native engine carry an `event_based` method it can only raise from, which is a worse lie than
an honest capability check.

### 2. The tree rupture ships, and the tree it is not

Two GSIMs are added to the registry and **verified against OpenQuake's own committed expected
values** exactly as ADR-0020 requires: `BooreEtAl2014HighQ` and `BooreEtAl2014LowQ`, the paper's
own regional anelastic-attenuation (`Dc3`) adjustments for high-Q regions (China, Turkey) and
low-Q regions (Italy, Japan). Both reproduce 70 200 reference values at the same tolerance as the
base model (worst mean 1.759 %, which is the coefficient-interpolation artefact ADR-0033 and
`docs/RISK.md` already explain). The coefficient tables and the expected-value tables were
extracted by the existing refresh scripts from the pinned `engine-3.26` tag, never hand-typed.

`rupture-asc-bssa14-q-v0` is those three branches at equal weight.

**What it is not, stated on the tree itself and in every document that quotes it.** It is not the
multi-model tree a national or regional PSHA uses. Such a tree for active shallow crust carries
several *independent* NGA-West2 models — Chiou & Youngs 2014, Campbell & Bozorgnia 2014,
Abrahamson, Silva & Kamai 2014, Idriss 2014 — which differ from one another far more than one
model's Q-regions differ from each other. rupture has implemented and verified none of those four.
They are named in `GsimLogicTree.excluded`, and the consequence is repeated wherever the tree is
used: **the spread this tree produces is a lower bound on GSIM epistemic uncertainty, not an
estimate of it.**

The weights are `ASSUMED` and the tree says so. No published weighting of the Q-region choice for
the Himalaya was found; the region's crustal attenuation is itself contested. Equal weights are the
statement "rupture cannot choose between them", not a claim about which is right.

Shipping a tree whose branch names rupture cannot evaluate was considered and rejected: a declared
branch that nothing runs is a claim the repository cannot back, which is the failure mode the GSIM
registry exists to prevent.

### 3. `event_based` on the engine side

`rupture.adapters.groundmotion.openquake_event_based` renders `calculation_mode = event_based`
with `investigation_time`, `ses_per_logic_tree_path`, `number_of_logic_tree_samples`, a
`gsim_logic_tree_file` and a source model, and parses the `gmf_data`, `events` and `ruptures`
exports into one field per sampled rupture with the rate each carries.

`grid_source_model_nrml` is the bridge that lets the **same** `ForecastGrid` drive both routes: one
`pointSource` per cell with an `incrementalMFD` whose rates are the grid's own, annualised, and the
same stated geometry assumptions the native route makes (ADR-0042).

A weighted tree may not be enumerated. Enumerating a weighted GSIM tree gives realisations that are
not equally likely, and the rate arithmetic downstream (every event of an event set carries the
same rate) assumes they are. Sampling the tree in proportion to its weights is what makes them
equally likely, so a multi-branch tree requires `n_logic_tree_samples >= 1` and asking for
enumeration is refused rather than silently mis-weighted.

## Consequences

- **The shipped tree barely moves this corridor's answer, and the reason matters.** Gorkha repeat:
  USD 631.4 M single-GSIM against USD 622.3 M with the tree, and the 90 % interval *narrows* by
  1 %. The `Dc3` adjustment is an anelastic-attenuation term that only bites with distance, and the
  corridor sits at Rjb = 0 under a shallow thrust. It is the same limitation as `docs/RISK.md` § 8
  item 1, seen from a different angle: at zero distance the choice among these three branches is
  almost no choice at all. At 100 km the branches span a factor of 1.6; at 200 km, 2.7. The tree
  is doing real work — just not here.
- Anyone reading a corridor interval as "including GSIM uncertainty" would be wrong, and both this
  ADR and `docs/RISK.md` say so.
- The engine's event-based path has **never produced a number on this machine**: the image is
  `linux/amd64`-only and the development host is arm64 (ADR-0011 addendum). The job rendering and
  every export parser are unit tested against captured export text; the container run is exercised
  only by `tests/integration/risk/test_event_based_engine.py`, which runs in CI on amd64 and skips
  locally with the reason printed. `RUPTURE_RISK_REQUIRE_ENGINE=1` turns the skip into a failure.
- The `ground-motion-field.v0` contract has no field for a logic-tree id or a per-realisation
  branch label, so the tree is recorded in `notes` and in the field's provenance. A `v1` of that
  contract carrying them is a request to the architect, recorded in `docs/RISK.md`.

## Alternatives considered

- **Ship a named regional model's tree (a GEM mosaic or national PSHA tree).** Rejected because no
  such tree for the Himalaya could be obtained under a licence and in a form rupture could verify,
  and because rupture implements none of the models such a tree contains. Naming branches it
  cannot run would be worse than shipping a narrower tree that it can.
- **Implement one more independent NGA-West2 model to widen the tree.** Not rejected — wanted. It
  is the single highest-value addition to this layer and is recorded as an open gap rather than
  attempted at the end of a pass.
- **Sample a branch per realisation.** Rejected in favour of deterministic allocation: sampling
  honours the weights only in expectation and makes a seeded run depend on branch order.
