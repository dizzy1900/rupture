# Model card — rupture risk (F2: ground motion → loss → avoided loss)

- **Component:** C2, `rupture.risk` and the `groundmotion` / `exposure` / `vulnerability` adapters
- **Version:** rupture 0.1.0
- **Date:** 2026-09-03 (UTC)
- **Contract:** `contracts/avoided-loss.v1.json` (ADR-0021)
- **Full detail:** `docs/RISK.md`; decisions in ADR-0020, ADR-0024, ADR-0025

## What it does

Given a rupture, a portfolio and a set of interventions, it computes expected loss with an interval
and the loss each intervention avoids, decomposed by asset, by plant component and by hazard
component, with the provenance of every figure attached.

## Out of scope

- **Forecasting individual earthquakes deterministically.** rupture does not predict earthquakes.
  Nothing in this component estimates when, where or how large the next earthquake will be. A
  scenario is a what-if; the Gorkha repeat is a published rupture model re-priced, and the MHT case
  is labelled hypothetical in the data, in the API and in every printed line.
- Loss from a time-dependent forecast (`TriggerKind.FORECAST`) or from long-term hazard
  (`TriggerKind.HAZARD`). Both return `status = not_implemented` with a message saying what is
  missing.
- Cascade loss: landslide, liquefaction, ice-rock avalanche. Reported as an explicit `0.0` in every
  decomposition so the zero cannot be read as "modelled and small". Delivered by C3.
- Loss types other than `structural`. No business interruption, contents or casualties.
- Spectral-acceleration loss. The GSIMs support `SA(T)`; every shipped fragility function is defined
  on PGA.
- Investment or insurance advice. The `insurance_layer` measure computes what a stated layer cedes;
  it does not recommend one.

## Inputs

| Input | Source | Provenance tier |
|---|---|---|
| Exposure (Trishuli corridor, 14 assets) | sibling `serac`, read by file contract; committed fallback from serac commit `7af421e0` | real slice, digest recorded |
| Replacement value | IRENA (2024), *Renewable power generation costs in 2023*, USD 2 806/kW (2023 USD) | published central value, **assumed ±40 % interval** |
| Site conditions | none available | **assumed** Vs30 = 760 m/s everywhere |
| Rupture (Gorkha) | USGS NEIC finite-fault inversion, event `us20002926` | published |
| Rupture (MHT) | published constraints on the great central-Himalayan earthquakes; magnitude computed from geometry via Hanks & Kanamori (1979) | **hypothetical** |
| Fragility, powerhouse / switchyard / tunnel | FEMA HAZUS 5.1 Tables 8-29, 8-31, 8-32, 7-9 | published |
| Fragility, intake / penstock | none found | **assumed**, parameterised in ADR-0024 |
| Consequence functions | HAZUS 5.1 Tables 11-10, 11-18 | published (intake and penstock **assumed**) |
| Component value shares | none found | **assumed**, ADR-0024 |
| GSIM coefficients | extracted from `gem/oq-engine` at tag `engine-3.26`; primary sources Boore et al. (2014) and Abrahamson et al. (2016) | published |

## Verification

Every shipped GSIM reproduces OpenQuake's own committed expected values (ADR-0020). Achieved:

| GSIM | Values | Worst mean | Worst stddev |
|---|---|---|---|
| `AbrahamsonEtAl2015SInter` | 22 400 | 4.9e-07 % | 0 % (exact) |
| `BooreEtAl2014` | 70 200 | 1.759 % overall; **0.00067 %** at tabulated periods | 0.0167 % |
| `BooreEtAl2014(sof=False)` | 23 400 | 1.759 % overall | 0.0167 % |

The BSSA14 1.759 % occurs only at SA(0.21), SA(0.23) and SA(4.5), whose coefficients must be
interpolated in log period because the committed coefficient table does not list them. OpenQuake
carries the same discrepancy and sets its own tolerance at 2 %.

Distance metrics are tested against analytic plane geometry. HAZUS parameters are tested against
verbatim committed extracts of the published tables. The engine cross-check
(`native_gsim` versus the OpenQuake container on the same rupture and sites) is implemented and runs
in CI on amd64; **it has never run on this project's development machine**, because the container is
`linux/amd64`-only and the machine is arm64.

## Results as computed

`native_gsim`, PGA, 2 000 realisations, seed 20260903, 90 % intervals. Portfolio value USD 1 519.2 M
(9 of 14 assets priced).

| Scenario | GSIM | Expected loss | 90 % interval |
|---|---|---|---|
| Gorkha 2015 repeat | `BooreEtAl2014` | USD 631.4 M | 303.8 – 962.5 |
| Gorkha 2015 repeat | `AbrahamsonEtAl2015SInter` | USD 620.3 M | 249.0 – 994.7 |
| MHT M8.5 hypothetical | `BooreEtAl2014` | USD 670.2 M | 336.9 – 991.7 |
| MHT M8.5 hypothetical | `AbrahamsonEtAl2015SInter` | USD 813.9 M | 430.7 – 1 114.5 |

Avoided loss, Gorkha repeat, `BooreEtAl2014`, baseline USD 631.4 M:

| Intervention | Avoided | 90 % interval |
|---|---|---|
| structural retrofit, all plants | USD 44.8 M | 31.3 – 54.6 |
| automated shutdown (15 %, assumed) | USD 52.6 M | 28.7 – 75.3 |
| land-use exclusion, Upper Trishuli-1 | USD 244.9 M | 62.2 – 432.7 |
| insurance layer, 400 M xs 200 M | USD 331.4 M | 103.8 – 400.0 |

## Intended use, and the use it is not ready for

**Intended:** relative comparison of interventions on one portfolio under one rupture; identifying
which assets and which plant components drive a portfolio's exposure; a reproducible, auditable
starting point for a discussion with an engineer or an underwriter.

**Not ready for:** pricing, capital adequacy, reinsurance placement, or any decision where the
absolute loss figure is the thing being relied on. Three reasons, in order of size:

1. 27 % of the loss rests on fragility functions rupture assumed, and all of it on component value
   shares rupture assumed.
2. The replacement-cost basis is a global weighted average with an assumed interval, not a
   Nepal-specific valuation.
3. The corridor sits above a shallowly dipping thrust, so Rjb is zero everywhere and an Rjb-only
   GSIM cannot discriminate between sites at all. Ground motion at the Gorkha repeat comes out near
   0.49 g on rock, whereas the single Kathmandu-valley strong-motion station recorded about 0.16 g in
   2015 — the model captures none of that event's well-documented high-frequency deficiency.

## Reproducing it

```bash
uv sync
make validate-risk
uv run python -m rupture.commands.risk run --scenario gorkha-2015-repeat --realisations 2000
```

Offline, no Docker, no network. Everything the numbers depend on — the exposure, the rupture model,
the reference tables — is committed with a recorded digest, and the gate checks those digests before
it computes anything.

## Known gaps

`docs/RISK.md` §8 lists fourteen. The ones that would change a number most: the assumed fragility
functions and value shares; the absence of any cascade contribution in a Himalayan gorge; the
absence of spatial correlation, which makes the intervals narrower than they should be; and the five
unpriced assets, which mean the portfolio total is not the corridor's exposure.
