# ADR-0029: The C1a challenger is a neural-kernel Hawkes process, on a shared dataset layer

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)
- **Relates to:** ADR-0009 (ETAS baseline), ADR-0018 (issuance without refit), ADR-0022 (leakage
  engineering), ADR-0023 (tracker adapters), `docs/EVALUATION_PROTOCOL.md`

## Context

Prompt 2 asks for a learned challenger to the ETAS baseline, and expects it to lose. Two decisions
had to be made before any code: what the model is, and where the machinery that feeds it lives.

The second matters more. rupture is building two learned models in parallel — a point process and
a gridded one — and ADR-0022's rules (refuse post-cutoff events, causal windows, blocked
time-forward folds, training-only normalisation) are exactly the kind of rule that gets
reimplemented slightly differently in each model until one of the copies is wrong. The copy that
is wrong will not announce itself; it will announce a good score.

On the first question, the published state of the art is unambiguous and recent. The EarthquakeNPP
benchmark (Stockman, Lawson & Werner, *TMLR*, March 2026; `ss15859/EarthquakeNPP`, MIT) evaluates
five neural point processes — NSTPP, DeepSTPP, AutoSTPP, DSTPP and SMASH — against the same `etas`
package rupture uses as its baseline, on seven California catalogues, and reports that **none of
them outperforms ETAS**. The gap is almost entirely spatial: on the temporal component the neural
models are competitive and occasionally marginally better; on the spatial component ETAS wins
consistently. The paper's own framing is that the previously standard neural benchmark for
earthquakes contained data leakage and omitted the region's largest sequence.

Reproducing one of those five architectures would mean reproducing a result that has already been
established, at the cost of vendoring four forks with incompatible conditioning conventions (their
burn-in handling differs per model: twenty prior events for some, none for others, the full
history for ETAS). rupture would inherit that inconsistency and would have to explain it.

## Decision

### 1. The shared dataset layer is `rupture.models.data`, and every learned model uses it

Four modules, one ADR-0022 rule each: `dataset` (builders take a hard cutoff and **raise** on any
event at or after it), `windows` (closed-left, open-right feature windows), `splits` (blocked
time-forward folds, with no shuffle parameter in the API), `normalise` (statistics fitted on
training rows only and carried with the model). A fifth, `geo`, holds the projection to
kilometres. Two views of a catalogue are built: `EventSequence` for point processes and
`GridCounts` for gridded models, the latter on exactly the protocol lattice and magnitude bins.

The layer is not an adapter and not a pipeline; it sits in its own top-level package that may
import adapters (for `build_lattice`, `LeakageError`, the magnitude binning) but is imported by no
adapter. That keeps the existing import-linter contracts untouched.

### 2. The C1a challenger is a marked Hawkes process with neural kernel *shapes*

The conditional intensity is

    lambda(t, x, y) = mu b(x, y) + sum_{t_i < t} A_i h_i(t - t_i) g_i(r_i)

with the mark drawn from a Gutenberg-Richter law. `h_i` and `g_i` are convex mixtures over fixed
Omori and power-law bases, and a small MLP maps each event's own magnitude and depth to the mixture
weights. Productivity `A_i = k0 exp(alpha (m_i - mc))` keeps the ETAS form, constrained
subcritical (decision 3b); the background `b` is a Gaussian kernel density over the training
epicentres.

Three properties drove this shape over a recurrent or attention-based intensity:

- **The compensator is exact.** Every basis element is a normalised density, so `int lambda` is a
  sum of closed forms rather than a quadrature. A model whose normalisation is itself approximated
  can improve its likelihood by getting the approximation wrong, and there is no way to tell from
  the score which happened.
- **It runs on a CPU in seconds** on the few hundred events actually available, which is the size
  of the training set, not a convenience.
- **It degenerates towards ETAS.** A negative result is then interpretable: it says the extra
  flexibility did not pay, not that the optimiser failed.

An earlier version let the MLP add a bounded offset to productivity as well. On a few hundred
scored training events that produced a productivity curve oscillating by a factor of fifty between
neighbouring half-magnitude steps, and it made `alpha` non-identifiable, because the offset was
itself a function of magnitude. Restricting the neural part to the kernel *shape* — a softmax over
densities, so any output is still a proper density — costs about 0.25 nats per event on the
training likelihood and buys a model whose extrapolation to a magnitude larger than anything in
training is bounded. Standardised features are additionally clipped, for the same reason.

### 3. The parameter snapshot carries a digest of the weights

`FitResult.parameters` is `dict[str, float]`, and a neural model has hundreds of weights that must
all be covered by the protocol's snapshot-constancy check (§ 7 rule 4). The fit publishes its
interpretable scalars as numbers and the SHA-256 of *(configuration, weights, normalisation
statistics)* as eight exactly-representable 32-bit chunks. Any retrain, any retuned hyperparameter
and any refitted standardiser changes `parameter_snapshot_hash`, so a schedule that quietly
retrained between windows fails the existing check without that check being modified.

### 3b. The fitted process is subcritical by construction

The productivity law is parameterised by *(branching ratio, magnitude sensitivity)* rather than by
`(k0, alpha)`: `alpha` is a sigmoid fraction of `beta` and the branching ratio is a sigmoid below a
ceiling, with `k0` derived. Both constraints hold identically rather than by hope, and the
diagnostics recompute the ratio from the published scalars so the constraint is checked.

Unconstrained, maximum likelihood drove the model supercritical on every catalogue tried — 1.00 on
a two-year California fixture, 0.96 on Nepal, 1.83 on Türkiye, where `alpha` had climbed to within
nine percent of `beta`. A supercritical Hawkes process has cascades that never terminate and
forecasts that are unstable rather than merely wrong. Every operational ETAS implementation
constrains its parameters for this reason. The decision was taken on the *training-set* branching
ratio, before any test window was scored, and it makes the model more conservative, never less.

Recorded alongside it because it matters for how both models are read: the ETAS baseline's own
`turkiye-eaf` fit has a branching ratio of **1.044** with `a > beta`, inside the package's own
inversion bounds. Near-critical fits are a property of these catalogues and of maximum likelihood
on them, not a defect peculiar to the challenger.

### 4. Forecasts are Monte Carlo continuations with an analytic background

The branching representation is simulated exactly (Poisson offspring counts from the closed-form
kernel mass, inverse-CDF delays and displacements), and the background component is placed
analytically, adopting ADR-0018's convention for ETAS verbatim. Sampling the background instead
leaves cells with exactly zero expected count, and an observed event in a zero-rate cell sends the
log-likelihood to negative infinity — which makes the S-, L-, CL- and paired tests *undefined*
rather than merely bad. This was changed after a two-window smoke run showed undefined paired
tests; it is a numerical-definedness fix and matches what the baseline already does, not a choice
made to improve a score.

### 5. EarthquakeNPP conventions are adopted where they apply, and departures are listed

Adopted: time in float days; locations projected to kilometres (their `Datasets/README.md` directs
models to `x, y` because ETAS works in great-circle kilometres); a hard magnitude cut with no
censored likelihood; calendar-date split boundaries rather than fractions; an explicit auxiliary
window; and the reporting split of log-likelihood per test event into temporal (`tll`) and spatial
(`sll`) components with `nll = -(tll + sll)`.

Departed from, each for a stated reason: magnitude is modelled as a **mark**, because rupture's
protocol scores magnitude bins and the benchmark's neural models discard magnitude entirely; a
**single global time origin** rather than the benchmark's per-split re-zeroing, because rupture's
leakage assertions compare absolute times; **full-history conditioning** rather than a
twenty-event lookback, matching what the benchmark gives ETAS; **fitting on training only**, where
the benchmark fits its ETAS baseline on training plus validation; and the **30-day protocol
horizon** rather than their rolling 24-hour forecasts. `docs/CHALLENGER_NTPP.md` carries the full
table.

## Consequences

- The gridded challenger inherits the leakage machinery rather than reimplementing it, and any
  future model that does reimplement it is visibly not using the shared layer.
- The negative result this model produces is comparable to a published benchmark's, because the
  conventions are the published ones and the departures are enumerated. It is also the same
  result: not promoted in either region run, losing on the spatial component, which is where
  EarthquakeNPP finds every neural point process losing.
- The likelihood is O(targets × sources) per epoch, so `california` (55 828 training events at
  Mc 2.7) could not be fitted and the protocol's two-of-three-regions condition is unreachable
  from this implementation. A sparse or windowed source set is the obvious fix and is not done.
- The model cannot express aftershock anisotropy, finite-fault geometry, time-varying
  completeness, or magnitude dependence in the mark distribution. Those are real limitations of
  this architecture, not of neural point processes in general, and a reader should not generalise
  from this negative result to the class.
- Fixing the basis exponents (`p`, `s`) rather than learning them is a modelling restriction taken
  because they are badly non-identifiable alongside the mixture weights on a few hundred events.
  On a catalogue an order of magnitude larger that trade would be worth revisiting.

## Alternatives considered

- **Port one of the five EarthquakeNPP models.** Rejected: it reproduces a published negative
  result at the cost of vendoring four forks with mutually inconsistent conditioning conventions,
  and rupture would have to explain an asymmetry it did not choose. The benchmark's *conventions*
  are adopted instead, which is what makes the numbers comparable.
- **A fully neural intensity (monotone network on the compensator, or an attention-based
  history encoder).** Rejected for this iteration: the compensator becomes approximate or
  expensive, and with a few hundred training events the extra capacity is variance. Recorded here
  as the obvious next step if a full regional catalogue becomes available.
- **Put the dataset machinery inside each model.** Rejected: ADR-0022's rules would then exist in
  as many copies as there are models, and the copy that is wrong would announce itself as a good
  score.
- **Store the trained weights with `torch.save`.** Rejected: it is a pickle. Weights are written
  as plain JSON lists, so a persisted fit stays inspectable, diffable and portable, and loading
  one never executes code.
