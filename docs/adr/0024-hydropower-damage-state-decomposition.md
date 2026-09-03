# ADR-0024: Hydropower damage-state decomposition, and what is published versus assumed

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

The exposure the loss layer is built for is a run-of-river hydropower corridor: nine plants
between Rasuwagadhi and Betrawati, 541.4 MW in total, published by the sibling `serac`. A
hydropower plant is not one structure. Its value sits in an intake, a headrace tunnel, a penstock,
a powerhouse and a switchyard, and those five things respond to shaking in materially different
ways: a bored tunnel liner in rock is among the most shaking-resistant structures there is, while
an unanchored switchyard is among the least.

Treating a plant as a single "industrial building" with a single fragility function would produce
a number, and the number would be wrong in a direction nobody could see. So the domain already
carries `HydropowerComponent`, and the question this ADR settles is which fragility and
consequence function each component gets, and — the part that matters more — which of those are
published and which are rupture's own assumptions.

The constraint from the non-negotiables is absolute: a fragility function either carries
`source_refs` or is marked `provenance = assumed, assumption = true`. There is no third option and
no rounding of one into the other.

## Decision

### 1. A plant is decomposed into five components with value shares

| Component | Share of replacement value |
|---|---|
| Intake / headworks | 15 % |
| Headrace tunnel | 30 % |
| Penstock | 10 % |
| Powerhouse (incl. electromechanical plant) | 38 % |
| Switchyard | 7 % |

**These shares are assumed in full.** No published cost breakdown for Nepali run-of-river schemes
was verified in this pass. The split reflects the standard observation that in a run-of-river
scheme the waterway (intake, tunnel, penstock) is the largest civil-cost block while the powerhouse
carries the electromechanical plant — but "reflects the standard observation" is not a citation, and
the shares are labelled accordingly. They are the single largest modelling assumption in the loss
figure and `docs/RISK.md` reports their sensitivity.

### 2. Three components use published HAZUS functions

Source: FEMA, *HAZUS 5.1 Earthquake Model Technical Manual* (July 2022) — a US Government work.

| Component | Fragility (PGA) | Consequence |
|---|---|---|
| Powerhouse | Table 8-31 (< 100 MW) / 8-32 (>= 100 MW), unanchored | Table 11-18, Generation Plants |
| Switchyard | Table 8-29, medium-voltage substation, unanchored | Table 11-18, Substations |
| Headrace tunnel | Table 7-9, bored/drilled (HTU1) | Table 11-10, Tunnel's Lining |

HAZUS's own default is used where it states one: "Damage functions available within Hazus are the
functions for facilities with unanchored components" (section 8.5.6.1). The **anchored** variants
are also carried, because they are what ADR-0025's `structural_retrofit` swaps to.

Two things about these functions are recorded rather than hidden:

- HAZUS's ground-shaking fragility for tunnels reaches only **Slight** and **Moderate**. The
  heavier tunnel damage states are driven by permanent ground deformation, which is a cascade
  input rupture does not have yet. So a headrace tunnel in this model cannot be destroyed by
  shaking alone, which is physically reasonable and also a real gap.
- HAZUS Table 11-18's "Range of Damage Ratios" for Substations/Moderate is 0.15-0.40, which does
  not contain its own best estimate of 0.11. rupture uses the best-estimate column **as
  published** and records the inconsistency; silently correcting a published table would be worse
  than carrying its blemish.

Applying a United States model to Nepali assets is itself an approximation — HAZUS's component
inventory and construction practice are not Nepal's — and every model built from these curves
carries that in its `notes`.

### 3. Intake and penstock are explicitly assumed

No published component fragility function was located for either. They are shipped with
`provenance = assumed`, `assumption = true`, no `source_refs`, and a stated parameterisation:

| Component | Median PGA: slight / moderate / extensive / complete | Beta |
|---|---|---|
| Intake | 0.20 / 0.40 / 0.70 / 1.10 g | 0.60 |
| Penstock | 0.15 / 0.30 / 0.55 / 0.90 g | 0.65 |

The reasoning, so a reviewer can disagree with something specific:

- **Intake.** A mass-concrete headworks with gates, founded on rock, is stiffer and much less
  equipment-dominated than a powerhouse but far more exposed than a bored tunnel liner. The
  medians are placed between HAZUS's unanchored small generation facility (0.10 / 0.17 / 0.42 /
  0.58 g) and its bored/drilled tunnel (0.6 g at slight).
- **Penstock.** For a surface steel penstock on anchor blocks, shaking damage is governed by
  support, anchor-block and expansion-joint failure rather than by pipe-wall capacity. The medians
  sit a little above the powerhouse's equipment-dominated curve and well below the tunnel's, with a
  wider dispersion for the variety of support arrangements found in the field.

Their consequence functions reuse the *shape* of HAZUS's generation-plant damage ratios
(0.08 / 0.35 / 0.72 / 1.00), also marked assumed.

### 4. Every result reports how much of the loss rests on an assumption

`PortfolioLoss.assumed_share` is the fraction of the best-estimate loss coming from components
whose fragility or consequence function is assumed. For the Gorkha-repeat scenario on the Trishuli
corridor it is **27 %**. That number is printed by the CLI and checked by the gate, so the
assumption cannot become invisible as the code grows.

### 5. Asset classes with no model are named, not defaulted

The corridor also holds a bridge, a border post and three settlements. rupture has no fragility
function for them and does not invent one: they appear in the portfolio, are listed as not
modelled with the reason, and contribute nothing. Five of fourteen assets, every time, in the CLI
output and in the gate findings.

## Consequences

- The loss figure can be decomposed by component, so a reader can see that (for example) most of
  the modelled loss comes from the powerhouse and switchyard rather than from the tunnel.
- `structural_retrofit` has a published meaning (ADR-0025) instead of an invented median shift.
- The corridor's headline loss depends on assumed value shares and, for 27 % of it, on assumed
  fragility functions. It is a defensible engineering estimate and it is **not** underwriting-grade
  until those two are replaced with sourced ones. `reports/MODEL_CARD_risk.md` says the same.
- The tunnel's inability to reach extensive damage under shaking alone will change when C3
  supplies permanent ground deformation; the `HazardComponent` decomposition already carries the
  slot as an explicit zero.

## Alternatives considered

- **One fragility function per plant.** Rejected: it hides which part of the plant drives the loss,
  and there is no published whole-hydropower-plant fragility function to use for it either, so it
  would be an assumption with less structure rather than more.
- **Ship only the three published components and price the other two at zero.** Rejected: it would
  understate the loss by a quarter of the plant's value while looking better sourced. An explicit
  assumption that is labelled is more honest than an omission that is not.
- **Derive the value shares from a scaling relation.** Rejected: no verified relation was found, and
  fabricating one would be worse than admitting the split is assumed.
- **Use GEM's global vulnerability functions instead of HAZUS.** Not rejected on merit — GEM's
  functions are the better fit for a non-US country — but no GEM function for hydropower components
  was verified in this pass. This is the first thing to revisit.
