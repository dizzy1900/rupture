# Model card — C3 triggered cascades

**Version:** 0.1.0 (Prompt 2, cascade layer)
**Date:** 2026-09-03
**Repository:** `github.com/dizzy1900/rupture`
**Full documentation:** [`docs/CASCADE.md`](../docs/CASCADE.md).
Decisions: [ADR-0026](../docs/adr/0026-usgs-ground-failure-models.md),
[ADR-0027](../docs/adr/0027-serac-slope-units.md).

---

## What this is

**These are susceptibility and exposure products.** They estimate, for a given earthquake's
shaking, where earthquake-triggered ground failure is more or less likely, and which terrain units
are shaken above a stated screening threshold. The estimates are empirical fits to inventories of
past earthquakes.

**They are not forecasts of individual slope failures.** Nothing in this layer states that a
particular slope, road, structure or parcel fails, or when. Every record carries that statement in
its own payload (`CascadeExposure.label`, `GroundFailureField.notes`) so it survives being passed
downstream.

## Out of scope

- **Forecasting individual earthquakes deterministically.** rupture does not do this anywhere, and
  this layer does not either. It is a *conditional* layer: it takes a scenario or observed event's
  shaking as an input and says something about ground failure given that shaking.
- Stating that a named slope, glacier or rock mass fails, or when it fails.
- Any warning, alerting or notification function. This is not an operational alerting system.
- Stability analysis of an individual slope. That is a site investigation, not a global model.
- Loss estimation. Losses are layer F2 and are not computed here.
- Aggregate hazard area or population exposure. The USGS publishes both per event; rupture
  computes neither, so its output cannot be compared to the product's alert levels.

## Components and their status

| Component | What it is | Status |
|---|---|---|
| Nowicki Jessee et al. (2018) landslide | published logistic model, coefficients from the USGS reference implementation | implemented; runs without its four static covariates |
| Zhu et al. (2017) general liquefaction | as above | implemented; runs without its three static covariates |
| Gorkha reproduction | comparison against the real published USGS `ground-failure` product | run; numbers below |
| Co-seismic ice/rock avalanche exposure | overlay of scenario shaking on serac slope units | implemented on a **fallback** inventory; one polygon per AOI, terrain null |
| `SourceTypeAssessment` client | reads serac's discriminator output, retags and accounts | implemented and tested; **has never seen a real serac assessment** |

## Inputs

**Sourced.** PGA, PGV and Vs30 from the published USGS ShakeMap grid (`grid.xml`, bands `PGA`,
`PGV`, `SVEL`). For the validation case this is the same ShakeMap version the USGS ground-failure
product was computed from.

**Not sourced — the declared gap.** None of the seven static conditioning rasters the two models
need is held by rupture: slope, GLiM lithology coefficients, GlobCover/MODIS land-cover
coefficients and HYDRO1k CTI (landslide); WorldClim precipitation, distance to coast/river and
Fan et al. (2013) water-table depth (liquefaction). Nothing was substituted for them. Their terms
are zero and every output names them.

## Coefficient provenance

Every coefficient is copied from the USGS `groundfailure` reference implementation
(`code.usgs.gov/ghsc/esi/groundfailure/groundfailure`; US public domain, CC0 1.0), whose relevant
source files are committed under `tests/fixtures/cascade/usgs_groundfailure/` with provenance and
licence. The `validate-cascade` gate and a unit test re-parse those files and fail on divergence;
a network test fails if the USGS changes them. **No coefficient in this layer was fitted, tuned or
invented by rupture.**

Two items are recorded as open rather than resolved: the sign of the landslide model's
`ln(PGV) x slope` interaction (operational code `+0.01`; secondary descriptions of the paper say
negative; the paper's own table has not been read by this implementation), and the per-class
lithology and land-cover coefficients, which live inside USGS rasters rupture could not obtain.

## Performance — 2015 Gorkha (ComCat `us20002926`, Mw 7.8)

Against the real published USGS `ground-failure` rasters, offline on committed slices.

**What rupture can actually compute today**, with no static covariate sourced:

| Model | cells | Pearson r | MAD | published mean | bias |
|---|---|---|---|---|---|
| Zhu (2017) general liquefaction | 6 636 | **0.4534** | **0.10170** | 0.15933 | −0.08639 |
| Nowicki Jessee (2018) landslide | 5 246 | **0.1624** | **0.03310** | 0.03694 | −0.03280 |

That is poor. It is what the covariate gap costs and it is the number that describes this layer's
present capability.

**What can be checked exactly.** The link function, the published coverage transforms, the masks
and the four-decimal rounding round-trip against the published rasters with a maximum absolute
difference of **0.0** for both models. With the static term recovered from the product, the
liquefaction model's shaking response, magnitude scaling, clips and masks agree at r = **0.9956**,
MAD **0.00064** (not exact: the ShakeMap `SVEL` band is not the Wald and Allen (2007) Vs30 raster
the product uses). The landslide equivalent scores perfectly for a degenerate reason and is
reported as such, not as validation.

**A check that could have failed.** The static term recovered from the published liquefaction
raster must lie inside the range the published coefficients and clips permit
(`5.408e-4 x 2500 = 1.352`). Observed: **98.87 %** of well-conditioned cells inside the band,
median 0.393. A wrong coefficient or a units error would have pushed it outside. No equivalent
bound exists for the landslide model.

## Ethical and operational considerations

- **Misuse risk.** A gridded ground-failure map is easy to read as a statement about a specific
  place. It is not one. The models are calibrated on aggregate inventories; a single cell's value
  carries no site-specific meaning. Every record says so; consumers must not strip the label.
- **Under-conditioning is not conservatism.** With the static covariates at zero, this layer
  under-calls ground failure almost everywhere (bias negative in both models above). It must not be
  used as a screening tool where a missed area matters.
- **The screening threshold is not a failure criterion.** The 0.02 g default is the floor below
  which a published *landslide* model declines to evaluate, applied to an *ice/rock avalanche*
  mechanism for want of anything better. No established shaking threshold exists for co-seismic
  ice/rock avalanche release and rupture does not invent one.
- **Do not use for evacuation, warning or life-safety decisions.** No part of this layer is
  validated for operational use.
- **The discriminator is one-way by design.** rupture removes an event from tectonic fitting on
  serac's evidence and never adds one back, because a false negative would put a mass movement
  into an earthquake rate model.

## Data, licences and attribution

| Source | Use | Licence |
|---|---|---|
| USGS `groundfailure` reference implementation | coefficient tables and model configuration | US public domain + CC0 1.0 |
| USGS ShakeMap and `ground-failure` products (`us20002926`) | shaking input and validation target | public domain (USGS) |
| USGS ComCat (`us7000tbwb`) | discriminator fixture case | public domain (USGS) |
| `serac` AOI source zones and exposed assets | slope-unit fallback and settlements | Apache-2.0, commit `8eee940`, copied verbatim with attribution; **serac's data, not rupture's** |

## Reproducing

```bash
uv run rupture validate cascade
uv run python -m rupture.commands.cascade reproduce
uv run pytest tests/unit/cascade -q
uv run pytest tests/integration/cascade -m integration   # network: checks upstream is unchanged
```

## Known limitations

The full list is §8 of [`docs/CASCADE.md`](../docs/CASCADE.md). The four that matter most:

1. None of the seven static conditioning covariates is sourced, so no conditioned susceptibility
   map can be produced and the reproduction of the published product is poor.
2. The slope-band masks never fire, so the large fraction of published cells that are exactly zero
   for that reason is not reproducible.
3. The exposure layer is one source-zone polygon per AOI with null terrain, because serac has not
   exported `slope-unit.v0` records yet.
4. No uncertainty is propagated. The USGS publishes a standard-deviation raster per model; rupture
   computes none and makes no interval claim.
