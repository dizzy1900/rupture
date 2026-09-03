# ADR-0026 — USGS ground-failure models: which two, and where their coefficients come from

- **Status:** accepted
- **Date:** 2026-09-03

## Context

Layer C3 (F3 in the layer table) has to answer "what did a large event trigger, and where" for
landsliding and liquefaction. Two considerations settled the choice quickly.

First, rupture must not fit its own ground-failure model. There is no inventory in this repository
to fit one on, and a model fitted here could not be compared to anything. The USGS runs two
published empirical models operationally and publishes their output per event as a `ground-failure`
product, which means an implementation can be held against a real, independent answer.

Second, the coefficients must be traceable. The papers are the citation of record, but the
operational product differs from the papers in at least one documented way, and the object of the
exercise is to reproduce the product a downstream user would compare against.

The USGS reference implementation, `groundfailure`, moved from `github.com/usgs/groundfailure`
(now archived, README pointing onward) to
`code.usgs.gov/ghsc/esi/groundfailure/groundfailure`. It is US public domain with a worldwide
CC0 1.0 dedication, so its configuration and model modules can be committed here as fixtures.

## Decision

**The two models.**

- Landslide: **Nowicki Jessee et al. (2018)**, "A Global Empirical Model for Near Real-time
  Assessment of Seismically Induced Landslides", *JGR Earth Surface* 123, 1835-1859,
  doi:10.1029/2017JF004494. Logistic in `ln(PGV)`, slope, GLiM lithology, MODIS/GlobCover land
  cover and HYDRO1k compound topographic index, with a `ln(PGV) x slope` interaction; the reported
  quantity is areal coverage through a published cubic-exponential transform.
- Liquefaction: **Zhu et al. (2017)**, "An Updated Geospatial Liquefaction Model for Global
  Application", *BSSA* 107, 1365-1385, doi:10.1785/0120160198, **general (global) variant**.
  Logistic in magnitude-scaled `ln(PGV)`, `ln(Vs30)`, mean annual precipitation, distance to the
  nearer of coast and river, and water-table depth; areal coverage through a published saturating
  transform.

The general Zhu variant rather than the coastal one because rupture's regions are not all coastal
and because it is the variant the USGS marks `preferred` in the Gorkha product.

**Coefficient provenance.** The coefficients are taken from the USGS reference implementation, not
retyped from a paper, and the source files are committed:

```
tests/fixtures/cascade/usgs_groundfailure/
  jessee_2018.py.txt        gfail/models/jessee_2018.py   — COEFFS, CLIPS, COV_COEFFS
  zhu_2017.py.txt           gfail/models/zhu_2017.py      — COEFFS, CLIPS, COV_COEFFS
  jessee_2018.ini           model config — slope band, minpga, maxprob
  zhu_2017_general.ini      model config — slope band, minpgv, minpga, vs30max, maxprob
  LICENSE.md, provenance.json
```

`src/rupture/cascade/coefficients.py` restates them in rupture's own vocabulary;
`tests/unit/cascade/test_coefficients.py` and the `validate-cascade` gate **re-parse the committed
USGS files** and fail on any divergence, so the restatement cannot drift. A network test in
`tests/integration/cascade/` re-fetches the same files and fails if the USGS changes them.

**Two things are recorded as open, not resolved** (`coefficients.OPEN_QUESTIONS`):

1. *The interaction sign.* The operational code carries `b6 = 0.01` for `ln(PGV) x slope` and adds
   it (`X += term * coeff`), in both `jessee_2018.py` and the `jessee_2018_slim.py` variant.
   Secondary descriptions of the paper give the interaction as negative. rupture implements the
   operational value, because that is the coefficient the published Gorkha product it reproduces
   was computed with and the only value it could verify against a primary machine-readable source.
   This implementation has not read the paper's own table. The sign stays an open question.
2. *The per-class lithology and land-cover coefficients.* These are not scalars. The USGS
   pre-substitutes fitted per-class values into two global rasters (`GLIM_replace.tif`,
   `globcover_replace.tif`) which are not published at a fetchable URL, and the model coefficient
   for both terms is therefore `1.0`. rupture treats them as covariates and does not carry the
   per-class tables at all.

**Covariates are a declared gap, not a substitution.** Neither model can be run as published from
anything rupture holds. `src/rupture/cascade/covariates.py` makes that structural: a covariate is
either *sourced*, with provenance, or *absent*, and an absent one leaves its term at zero while
every output record names it. The default source is `UnsourcedCovariates`, which sources nothing.
The static covariates rupture could **not** obtain at a size worth committing are:

| Model | Not sourced | Upstream |
|---|---|---|
| Landslide | slope (gradient), lithology coefficient, land-cover coefficient, CTI | GMTED2010, GLiM, GlobCover/MODIS, HYDRO1k |
| Liquefaction | mean annual precipitation, distance to water, water-table depth | WorldClim, NASA Ocean Color + HydroSHEDS, Fan et al. (2013) |

Sourced, from the same published ShakeMap the USGS product used: PGA, PGV, Vs30 (the ShakeMap
`SVEL` band, which is close to but not the Wald and Allen (2007) raster the product uses).

**The reproduction is reported honestly.** `rupture cascade reproduce` runs three comparisons
against the published Gorkha rasters and reports all three: a link/coverage round trip, a shaking
comparison with the static term recovered from the product, and an *unconditioned* comparison that
measures what rupture can actually do today. The last one is poor. The numbers are in
`docs/CASCADE.md` and are asserted by tests so the documentation cannot drift from them.

## Consequences

- rupture can state a defensible claim: its implementation of the *published* models agrees with
  the operational product where it can be tested, and it cannot produce a conditioned
  susceptibility map because it lacks the conditioning rasters. Those are two different claims and
  the code keeps them apart.
- Adding a covariate source later is a `CovariateSource` implementation and a provenance record;
  nothing about the model code changes, and the "INCOMPLETE" flag disappears on its own.
- The gate asserts the link round trip exactly and the coefficient provenance exactly, and reports
  the unconditioned agreement without asserting it. A gate that asserted the poor number would
  make the poor number look intentional.
- rupture is pinned to the operational USGS behaviour, including its literal `2.71828` in place of
  `e` and its 4-decimal rounding. If the USGS revises a model, the integration test fails first.

## Alternatives considered

- **Retype the coefficients from the papers.** Rejected: no machine-readable primary source to
  check against, and the operational product differs from the papers in at least one place
  (the unconsolidated-sediment substitution to `-1.36`, recorded in the Gorkha `info.json`).
- **Ship plausible constants for the missing covariates** so the model "runs properly". Rejected
  outright: that is fabricated data presented as real, and it would have made the Gorkha agreement
  look better than rupture's actual capability.
- **Download the USGS global input layers.** They are not published at a fetchable URL from either
  the archived GitHub repository or the GitLab one, and their aggregate size is far beyond what
  belongs in this tree. Recorded as the gap it is.
- **Zhu (2015) or Nowicki (2014) instead.** Both are superseded and the USGS marks neither
  `preferred`; they exist in the product for continuity.
- **Godt et al. (2008) Newmark displacement.** A different model class (mechanical, not
  empirical-statistical) with its own input requirements; out of scope here.
