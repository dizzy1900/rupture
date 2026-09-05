# ADR-0061 — Interoperate with CSEP and the existing benchmarks; do not fork them

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Extends:** [ADR-0010](0010-pycsep-evaluation.md) (pycsep as the evaluation engine)
- **Related:** [ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md),
  [ADR-0057](0057-prospective-open-benchmark.md),
  [ADR-0062](0062-third-party-licence-quarantine.md)

## Context

A project that aims at prediction and operates its own benchmark has an obvious failure mode: it
builds a parallel universe of tools, formats and scores in which it is the only inhabitant, and its
results become unfalsifiable by anyone else because nobody else can run them.

The tools rupture would otherwise rebuild already exist, are permissively licensed, and are
maintained. pyCSEP (BSD-3) implements the consistency and comparison tests, the catalogue readers,
the Cartesian and quadtree regions and the plotting; rupture already depends on it at a pinned
0.8.0 (ADR-0010). floatCSEP (BSD-3) runs whole prospective experiments from a YAML file with
Docker-pinned models and a `reproduce` command. EarthquakeNPP supplies datasets, splits and an
operational ETAS. `lmizrahi/etas` (MIT) is the baseline (ADR-0009). SeisBench is the standard
picking API. The asset audit checked these directly: all of them resolve, all are actively
maintained with pushes within weeks, and their licence claims are correct — which is not true of
the bibliography's licence column in general
([ADR-0062](0062-third-party-licence-quarantine.md)).

Extending them buys credibility with exactly the people whose adjudication rupture needs. Forking
them buys isolation. The review's cautionary examples are concrete: `gmprocess` lost community
visibility when it moved to an agency GitLab, and the `pick-benchmark` repository froze in 2023
while SeisBench moved on for three years.

One correction while we are here: the audit found four repository owner renames, and pyCSEP is now
`cseptesting/pycsep`. ADR-0010 names `SCECCode/pycsep`, which redirects.

## Decision

1. **Adopt, do not rebuild.** pyCSEP stays the scorer for the `RateForecast` and
   `SimulatedCatalogues` arms; floatCSEP becomes the experiment runner for
   [ADR-0057](0057-prospective-open-benchmark.md); EarthquakeNPP's datasets are consumed through
   its own loaders rather than reformatted into a rupture-native corpus; `lmizrahi/etas` stays the
   baseline. Where a capability exists upstream, rupture calls it.

2. **New evaluation code that CSEP could use is written to be upstreamed.** The alarm-forecast
   class and the Molchan / area-skill-score / probability-gain module
   ([ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md)) are the first candidates, because
   pyCSEP has none and the gap is the reason alarm-based claims currently cannot be adjudicated in
   a form the field recognises. rupture carries its own implementation only until the pull request
   lands, and the code is structured so that carrying it is temporary — no rupture domain types in
   the module, no rupture-specific configuration.

3. **Rupture's models are submitted to third-party experiments, not only to rupture's board.**
   Every model is packaged floatCSEP-compatible and submitted to the live CSEP Italy 2024
   short-term experiment. The 2024 Delphi elicitation of 20 experts found 74 % agree a model is
   ready when tested by a third party such as CSEP and 79 % consider comparison to a benchmark
   model important — the only near-consensus requirement in the survey. Self-testing is not that.

4. **Do not build another picker, associator or locator.** PhaseNet, EQTransformer, PhaseNO,
   PyOcto, GENIE and GaMMA are permissively licensed with pretrained weights, and SeisBench is the
   standard API. Scaling is explicitly inefficient at this task (Ma et al. 2026 report a 120×
   larger teleseismic PhaseNet gaining 15.6 % precision for 87 % less GPU throughput,
   `single-study`). Rupture consumes picks; it does not produce a new picker.

5. **Do not build a parallel benchmark format.** Where rupture's benchmark scores an arm CSEP does
   not have, it adds an arm; it does not restate the arms CSEP already scores in a different
   vocabulary.

6. **Pins are exact and moving one is an ADR-worthy change**, as ADR-0010 already says of pycsep
   and ADR-0009 of the ETAS commit: an upstream minor release changes the arithmetic that defines
   rupture's published numbers.

7. **Interoperation is a two-way obligation.** rupture publishes its datasets in
   SeisBench-compatible form where the shape allows, and its as-of API is documented as a public
   contract rather than an internal convenience — adoption of that API by an external group is one
   of [ADR-0057](0057-prospective-open-benchmark.md)'s success criteria.

## Consequences

- Rupture's ability to change the scoring arithmetic is bounded by upstream's release cadence and
  by upstream's willingness to accept a contribution. That is a real loss of autonomy and it is the
  price of the credibility this ADR is buying. Where a pull request is rejected, rupture keeps its
  module and says in the module why it is not upstream.
- pyCSEP's heavy dependencies (cartopy, rasterio) remain accepted, as ADR-0010 already records,
  along with the fallback that plotting becomes optional where wheels will not resolve.
- Some upstream tools are new and small. floatCSEP was published in February 2026 with a few
  hundred commits and a handful of stars; the survey tagged it `widely-used` and the audit
  downgraded that, because a tool six months old cannot be. Depending on it is a bet on the CSEP
  community rather than on a proven artefact, and it is made deliberately.
- ADR-0010's repository reference is stale: `SCECCode/pycsep` is now `cseptesting/pycsep`. The
  distribution name and pin are unchanged.
- Not everything can be interoperated with. Japanese and Chinese waveform corpora, proprietary
  smartphone data and operational alerting all require agreements or agency status rupture will not
  have. Naming them is more credible than pretending otherwise, and the layers rupture *can* build
  make other people's instrumentation more useful rather than replacing it.

## Alternatives considered

- **Fork pyCSEP and move fast.** Rejected: the tests are the protocol, and a rupture-only variant
  of the protocol is a rupture-only claim. The 2023 freeze of `pick-benchmark` while SeisBench
  moved on is what forking looks like eighteen months later.
- **Write a clean-room evaluation stack.** Rejected on ADR-0010's original reasoning — reproducing
  a reference implementation adds risk and no value, and a reviewer would ask why — which the
  re-aim strengthens rather than weakens.
- **Build the alarm scorer inside rupture and never upstream it.** Rejected: an alarm scorer inside
  pyCSEP adjudicates the field's claims and the same code inside rupture adjudicates rupture's, and
  the first is the thing worth doing.
- **Wait for upstream to build the alarm class.** Rejected: the review's own reading is that CSEP
  was never built for alarm claims and that nobody is building it, which is what makes it a
  contribution rather than a duplication.
