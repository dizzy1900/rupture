# ADR-0053 — Rupture targets earthquake prediction

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Supersedes:** [ADR-0034](0034-cite-published-titles-verbatim.md) (the banned-language
  allowlist), by removing the gate it extended.
- **Related:** [ADR-0054](0054-latency-aware-observation-sources.md),
  [ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md),
  [ADR-0056](0056-preregistration-by-git-ancestry.md),
  [ADR-0057](0057-prospective-open-benchmark.md),
  [ADR-0059](0059-reference-baseline-set.md)

## Context

Rupture was built over two phases under a rule set whose first non-negotiable was "no prediction
claims". That rule had a mechanical enforcer: a `language` gate that scanned the tree for the verb
*predict* and its derivatives, with an allowlist that had to be extended by ADR before rupture
could cite two ground-motion papers by their published titles (ADR-0034). It also had a
positioning: rupture described itself as a probabilistic seismic *forecasting* and cascade-loss
system, and every document was written so that no sentence could be read as a claim about an
individual future earthquake.

On 2026-09-04 the owner removed both. Rupture is now an open research project on earthquake
prediction, and says so in its own voice.

The argument for the change is not that the field's caution was wrong. It is that the caution was
attached to the wrong object. "Nobody has demonstrated deterministic short-term prediction" is a
statement about a historical record made with far less data, far less compute and far worse methods
than exist now; it was never the same statement as "it cannot be done", and thirty years of
treating the two as interchangeable has produced a field where the interesting question cannot be
asked in a funding application. What made the old positioning defensible was never the word gate.
It was the leakage controls, the properly fitted baselines, the refusal to fabricate data and the
provenance machinery — and none of those depend on which word appears in the README.

There is a real objection, and it comes from the review this re-aim was assessed against rather
than from anywhere inside the repository. The review's own summary judgement is that "predict
earthquakes" as a *headline* repels the exact community whose tests confer legitimacy, and that the
framing which attracts geophysicists is "measurably raise forecast information gain toward the
predictability limit, and find out where that limit is". That is a disagreement about the sentence
on the front page, not about the target, and it is recorded here rather than smoothed over. The
decision below keeps the target and adopts the review's framing as the operational form of it,
because the two are compatible: a project asking "can earthquakes be predicted?" has no way to make
progress, and a project asking "does adding continuous GNSS strain move information gain at 7-day
lead in California, and by how much?" has a research programme, a null result worth publishing and
a positive result nobody can wave away.

## Decision

1. **Rupture's stated target is earthquake prediction**, in its own vocabulary, without euphemism.
   `predict`, `prediction` and `predictability` are ordinary words in this tree.

2. **The banned-language gate is removed.** The `language` gate, its scanner, its allowlist and the
   ADR-0034 mechanism for extending that allowlist are gone. Nothing replaces them at the level of
   words.

3. **What replaces it is an obligation on substance, not on vocabulary.** Every claim carries its
   number, the baseline it beat and the protocol it was scored under, in the same breath, or it is
   explicitly labelled untested. This is CLAUDE.md § How Rupture writes about results.

   It is *designed* to be enforced in three places a regex could never reach, and **only one of the
   three exists today** — which has to be said here, because a decision record that describes
   unbuilt machinery in the present tense is the same error the gate was removed for.

   | Enforcement | State on 2026-09-04 |
   |---|---|
   | The scorer registry refuses to emit a score without its arm's reference baseline computed on the same data ([ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md), [ADR-0059](0059-reference-baseline-set.md)) | **not built.** No scorer registry, no `Scorer` port, no mandatory-baseline check. `RELEASE_STATUS.md` § What the new architecture means for what is built |
   | The pre-registration runner refuses to score an experiment whose hypothesis was written after the fact ([ADR-0056](0056-preregistration-by-git-ancestry.md)) | **not built.** Pre-registration today is convention plus the challenger pipeline's `select`-before-`fit` hyperparameter freeze |
   | The qa-reviewer veto on any result published without its protocol and baseline | in force, and it is a person rather than a check |

   So between the gate's removal and those two modules landing, the substance rule rests on review
   alone. That is a real reduction in mechanical coverage and it is the cost side of this decision,
   recorded in Consequences below rather than left to be discovered.

4. **The leakage controls are kept, and are now load-bearing rather than merely prudent.** The
   repository holds its own evidence for why. The deliberately leaky ablation in
   `reports/CHALLENGER_EVALUATION.md` (ADR-0022 rule 6) manufactures **+0.31 to +2.16 nats per
   event** of apparent skill across the two challengers that were leaked at all, and on
   `nepal-himalaya` it turns the neural challenger's honest **−0.346** nats-per-event information-gain
   *loss* against ETAS into a **+0.429** apparent *win* — 181 % of the true figure, including its
   sign. Leakage does not produce small errors. It produces the result you were hoping for, which
   is why it is invisible from the inside, and the more interesting the claim the harder it will be
   attacked here first. A prediction project needs this machinery more than a forecasting project
   does, not less.

5. **Adversarial baselines are kept and strengthened.** Every claim is scored against the strongest
   available baseline for its task, properly fitted, published with its diagnostics, and computed
   on the same data and the same vintage. The reference set is [ADR-0059](0059-reference-baseline-set.md).
   Where a baseline wins, that is the published result — which is already rupture's own position:
   no challenger beat ETAS under the pseudo-prospective protocol (`RELEASE_STATUS.md`).

6. **No fabricated data, and provenance on every record, are kept unchanged.** Adapters fetch or
   fail loudly; unknowns are null; synthetic data from a physics simulator is permitted as training
   input and is labelled synthetic everywhere it appears.

7. **The operational firewall is kept and is now more important, not less.** Rupture is a research
   repository. Nothing in it is an alert system, and artefacts say so in their metadata. The
   institutional vocabulary is not negotiable and rupture uses it exactly: the ICEF (2011) line
   between a deterministic *prediction* and a probabilistic *forecast* is the line agencies work
   to, and a research forecast escaping into an operational channel is measured in lives rather
   than in reputations. Aiming at prediction as a research target and broadcasting an alarm are
   different acts, and rupture does the first and not the second.

8. **Negative results are deliverables.** A line pursued properly and published with its evidence
   is a contribution. Under the re-aim this becomes the most likely output rather than a
   consolation: the review's cleanest and most trustworthy entries are all null results, and a
   roadmap built on the field's nulls stands on firmer ground than one built on its positive
   claims.

## Consequences

- The repository can cite its sources by their published titles without an allowlist, which is the
  minimum a reviewer expects and was the immediate cost ADR-0034 was written to pay.
- The `language` gate is no longer in the `GATES` tuple in `src/rupture/validation/registry.py`,
  which now holds nine names. **CLAUDE.md § Make targets is stale on this point**: it still says the
  tuple holds ten and names `language` first, while the same file's CI paragraph correctly says
  nine. The tuple is the authority; the prose needs correcting, and it is recorded here rather than
  left for a reader to discover.
- Removing a gate removes a check, and honesty requires saying what is no longer caught. The gate
  did catch things — its own ADR-0034 correction records four working bypasses a reviewer
  constructed, and the fix caught a live violation in CLAUDE.md the same day. What is lost is a
  mechanical floor on over-claiming in prose. What is *meant* to replace it is review plus the two
  substantive checks in decision 3 — strictly harder to satisfy, and **neither of them built** — so
  for the moment the replacement is review alone, and the mechanical coverage of over-claiming is
  lower than it was on 2026-09-03. That is an honest cost, not a wash. It is the strongest argument
  for building ADR-0055's registry and ADR-0056's runner before the first new claim rather than
  after it, and it is why falsification condition 4 below is the one to watch first: if the
  qa-reviewer veto has to be exercised on a published claim in the interim, the interim was too
  long.
- The audience cost in the Context is real and unresolved. Rupture mitigates it by leading with the
  measurable form ("how much probability gain, at what lead time, for what magnitude range, from
  what observations") and by seeking third-party adjudication rather than self-certification
  ([ADR-0057](0057-prospective-open-benchmark.md)). Whether that is sufficient is an empirical
  question about people, and it will be answered by whether external groups submit.

## What would have to be true for this to have been the wrong call

Recorded now, before the results exist, because a re-aim without a falsification condition is a
mood rather than a decision. Any one of these is sufficient:

1. **The latency programme finds nothing.** If the as-of layer
   ([ADR-0054](0054-latency-aware-observation-sources.md)) shows that skill on final data minus
   skill on as-of data is within bootstrap noise for every model and every sequence tested, then
   the leakage class the re-aim was built around is not a practical one, and the honest verdict is
   that prediction framing bought a data-engineering convenience.
2. **ETAS-I absorbs everything.** If every claimed machine-learning gain over plain ETAS disappears
   against an incompleteness-aware ETAS on every dataset
   ([ADR-0059](0059-reference-baseline-set.md)), the small-event result is an artefact of baseline
   choice, catalogue-only forecasting is closed, and the prediction target reduces to the below-catalogue
   observables — which are largely instrumentation problems rupture cannot fund.
3. **The adjudicators decline.** If, after twelve months of operating the prospective benchmark, no
   external group submits a model and no testing centre adopts the as-of API, the credential the
   project needs is unobtainable in this framing, and the review's warning about the headline was
   right.
4. **Over-claiming appears in the tree.** If the qa-reviewer's veto has to be exercised on a
   published claim missing its protocol or baseline, the word gate was doing work that review is
   not doing, and something mechanical has to come back — though not the same regex.

None of these is "an earthquake was not predicted". Failing to predict an earthquake is the
expected outcome of almost every experiment in this repository and is not evidence about the
framing.

## Alternatives considered

- **Keep the no-prediction positioning and the word gate.** Rejected by the owner. The reasoning
  recorded here: the gate protected the project's reputation and cost it the ability to state its
  own question; and a project that cannot state its question cannot recruit people to work on it.
- **Keep the target and keep the gate, with a wider allowlist.** Rejected: ADR-0034's own
  correction shows the allowlist is an attack surface, and a gate that must be widened every time
  rupture says what it does has stopped serving a purpose.
- **Adopt the review's framing as the target itself** — "measure how much predictability remains"
  rather than "predict earthquakes". Rejected as the *target*, adopted as the *method*. The
  measurement framing is what makes the work tractable; it is not what makes it worth doing, and a
  project that will not say what it is aiming at ends up optimising the measurement.
- **Announce nothing and change the code first.** Rejected: the re-aim changes what evidence is
  required of every future claim, and that has to be written down before the claims exist, not
  after.
