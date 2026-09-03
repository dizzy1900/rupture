# ADR-0025: Intervention models, the replacement-cost basis, and how the scenarios are built

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

ADR-0021 settled the *shape* of the avoided-loss contract. It did not say what any intervention
actually does to a loss, what a megawatt of installed capacity is worth, or where the rupture
geometry a scenario is priced against comes from. Those three are where a loss layer either earns
an underwriter's attention or quietly becomes a random number generator with good typography.

Each of the three has the same failure mode available to it: pick a plausible factor, present the
result as a model. This ADR records the decision to refuse that in every case, and what was done
instead.

## Decision

### 1. Avoided loss is a difference over shared realisations

Every branch — the baseline and each intervention — is priced on **one** ground-motion field, the
same realisations in the same order. Avoided loss is then computed realisation by realisation and
aggregated. Two independent samples would differ by sampling noise of the same order as the effect
being measured, so a difference taken across them would not be a measurement.

The implementation checks the identity: for every intervention, `expected_loss + avoided == baseline`
to within floating point. The test asserts it.

### 2. Interventions

**`structural_retrofit` — published.** HAZUS publishes *paired* fragility curves for anchored and
unanchored components of the same facility class (Tables 8-29, 8-31, 8-32). Retrofitting is
modelled as the swap from the unanchored curve to the anchored one. This is the only intervention
whose effect is a published quantity rather than a chosen factor; nothing here is a "median shift
of x".

The implied shift is small at the intensities this corridor sees. For a Gorkha repeat the modelled
avoided loss is about **7 %** of the baseline, because at a median PGA near 0.5 g both the anchored
and the unanchored curves put most plants in extensive or complete damage. That is a finding, not a
defect: anchoring components buys a great deal at 0.2 g and little at 0.5 g.

**`automated_shutdown` — assumed.** Tripping the units and closing the intake gates on a
strong-motion trigger. No published fragility pair for a tripped versus running hydropower unit was
found. The measure is therefore parameterised as avoiding a stated fraction of the **powerhouse
component's** loss, default **15 %**, marked assumed, exposed as a request parameter
(`parameters.avoided_fraction`) so a consumer can substitute their own number, and reported in
`assumptions` on every response that uses it. The response says which fraction the run used.

**`land_use_exclusion` — definitional.** The named assets are removed from the exposure; their loss
is avoided in full. Nothing is modelled about what is built instead, or where, and the response
says so. This is the largest measure in the corridor precisely because it is the bluntest: excluding
Upper Trishuli-1 alone avoids about 39 % of the modelled loss, which is the same statement as "one
asset is 40 % of the portfolio".

**`insurance_layer` — financial, not physical.** A simple excess-of-loss layer: per realisation, the
loss between an attachment point and a limit is ceded. Physical damage is unchanged and the
response carries a note saying the measure "changes who pays, not what breaks". Keeping it in the
same enum as the physical measures is deliberate — an underwriter compares them — but conflating
the two in prose would not be.

serac's `warning` and `evacuation` kinds are representable in the shared enum (ADR-0021) and are
**refused** by rupture's seismic path with a message saying they are serac's semantics. A silent
zero would be worse.

### 3. The replacement-cost basis

Capacity is not money. Converting the corridor's 541.4 MW into a portfolio value needs a cost
basis, and rupture carries exactly one, cited:

> IRENA (2024), *Renewable power generation costs in 2023*, International Renewable Energy Agency,
> Abu Dhabi (ISBN 978-92-9260-621-3): "the global weighted average total installed cost of new
> hydropower projects decreased from USD 3 053/kW to USD 2 806/kW - a fall of 8 %".

rupture uses **USD 2 806/kW in 2023 USD**. The corridor's total is therefore
USD 1.519 billion, which is arithmetic on a published figure and reproducible to the penny. As a
sanity check that is worth recording: Upper Trishuli-1 (216 MW) prices at USD 606 million on this
basis, against the USD 647 million total project cost widely reported for it — close enough to
suggest the basis is not wildly wrong for this corridor, and not a substitute for a Nepal-specific
figure.

**The interval around that figure is an assumption, and is labelled one.** A band of +/- 40 % is
applied and the resulting `MoneyRange` carries `ModelProvenance.ASSUMED` and
`ConfidenceTier.LOW`. The reasons the published central value cannot carry a published interval
here: IRENA's number is a *global* weighted average of *newly commissioned greenfield* projects;
Nepal's projects are widely reported as costing more than the global average; and post-earthquake
reinstatement is not the same activity as greenfield construction. The same IRENA series moved 8 %
in one year and 92 % since 2010, so the true dispersion is certainly not narrow — but "certainly not
narrow" does not give a number, so the number is stated as a judgement.

**Asset classes with no cost basis are carried at zero and counted.** The corridor's bridge, border
post and three settlements have no verified replacement cost here. Inventing one would make the
portfolio total look complete when five of fourteen assets are missing from it.

### 4. The scenarios

**Gorkha 2015 repeat — a published rupture model.** The plane comes from the USGS NEIC finite-fault
inversion for event `us20002926`, committed verbatim as an FSP file with its provenance. The
inversion grid is 193 x 168 km, deliberately larger than the area that slipped, so using it whole
would put the rupture implausibly close to sites. rupture takes the **smallest rectangle in fault
coordinates holding 90 % of the slip**, trimming whole rows and columns from the edges, always the
one carrying least slip. On a uniform sub-fault grid at constant rigidity that is the smallest
rectangle holding 90 % of the released moment. It yields 144 x 126 km with the top of rupture at
7.7 km — consistent with the published account that the Gorkha rupture did not reach the surface.
The threshold is a parameter, not a constant buried in a formula, and `docs/RISK.md` reports what
other values do (for this corridor: almost nothing, because Rjb is zero either way).

**MHT M8+ — hypothetical, and computed rather than asserted.** A Main Himalayan Thrust rupture
reaching the surface at the Main Frontal Thrust: 250 km along strike, 7 degrees dip (as resolved for
Gorkha), from `ztor = 0` down dip to 20 km depth, 5 m average slip. The extent follows published
constraints on the great central-Himalayan earthquakes (Sapkota et al. 2013 on the 1255 and 1934
surface ruptures; Bollinger et al. 2014; Stevens & Avouac 2016). The **magnitude is then computed
from that area and slip** through Hanks & Kanamori (1979), giving M 8.49 — so the geometry and the
magnitude cannot disagree, and no magnitude-area scaling relation had to be adopted unverified.
`hypothetical = True`, and every report repeats it. It is a what-if, not a statement about the
future.

**Stochastic event sets — the interface, not the data.** `from_stochastic_event` is the hook the
forecasting layer plugs an ETAS catalogue into. An event **with** a finite-fault geometry keeps it.
An event **without** one becomes a point rupture, and the returned rupture's notes say so in full:
Rjb is the epicentral distance, distances are therefore longer than a finite rupture of that
magnitude would give, and the loss is a lower estimate. rupture does not manufacture a fault plane
from a magnitude.

## Consequences

- Three of the four interventions have effects a reviewer can check against a source or argue with
  as a stated assumption. None of them is an unattributed multiplier.
- The portfolio valuation is arithmetic on a published figure with an assumed interval, so the
  headline loss is reproducible and its weakest link is visible.
- The corridor's loss can be recomputed from a fresh clone with no network: the rupture model, the
  exposure and the reference tables are all committed with digests.
- Two known consequences of these choices, recorded rather than smoothed over: the retrofit looks
  weak because the shaking is severe, and the exclusion measure looks strong because the portfolio
  is concentrated. Both are properties of the corridor, not of the model.

## Alternatives considered

- **A published median-shift factor for retrofit.** Rejected because HAZUS's own anchored/unanchored
  pair is strictly better: it is a published pair for the same facility class, not a factor lifted
  from a different context.
- **Model `automated_shutdown` as a fragility-median shift.** Rejected: with no published pair, a
  shift factor and a loss-ratio fraction are equally assumed, and the fraction is easier for a
  consumer to reason about and to override.
- **A Nepal-specific cost per MW from secondary reporting.** The USD 2 million/MW figure that
  circulates in Nepali press coverage could not be traced to a primary source, and the Upper
  Trishuli-1 total project cost is not disclosed on the IFC or AIIB project pages. Using an
  untraceable number as the basis would have been worse than using a traceable global average and
  saying it is global.
- **Use the whole USGS inversion grid as the rupture surface.** Rejected: it would overstate ground
  motion for a reason that has nothing to do with the earthquake and everything to do with how the
  inversion was parameterised.
- **Set the MHT magnitude to 8.5 and derive the area from it.** Rejected: it would require a
  magnitude-area scaling relation that this pass did not verify. Computing the magnitude from the
  geometry needs only Hanks & Kanamori (1979), which is not in dispute.
