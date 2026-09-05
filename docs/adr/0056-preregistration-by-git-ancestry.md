# ADR-0056 — Pre-registration is enforced mechanically, by git ancestry

- **Status:** accepted
- **Date:** 2026-09-04 (UTC)
- **Amends:** [ADR-0022](0022-leakage-engineering-for-learned-models.md) (rule 4, frozen
  hyperparameters), by putting a machine behind the freeze
- **Related:** [ADR-0015](0015-pseudo-prospective-evaluation.md),
  [ADR-0053](0053-rupture-targets-earthquake-prediction.md),
  [ADR-0054](0054-latency-aware-observation-sources.md),
  [ADR-0057](0057-prospective-open-benchmark.md)

## Context

CLAUDE.md principle 4 says an experiment declares its hypothesis, region, magnitude range, lead
time, alarm rate and scoring rule in a committed file before it touches the test data, and that git
is the timestamp. As written that is an intention. The qa-reviewer holds a veto on "an experiment
scored against a pre-registration written after the fact", and a veto exercised by a reader is the
weakest control in this repository: the artefact under review is a file whose content and date the
author chose.

Pre-registration is the one thing an open repository can do that a closed laboratory cannot easily
do, and it is only worth anything if a stranger can verify it. So it has to be a check that runs,
not a promise that is made. This ADR records the check, and — because the check is easy to
overstate — the six ways it can be defeated or can fail to apply.

## Decision

1. **A pre-registration is a committed file** under `experiments/<id>/preregistration.yaml`,
   declaring at minimum: the hypothesis in one sentence; the hypothesis arm
   ([ADR-0055](0055-hypothesis-sum-type-and-scorer-registry.md)); region; magnitude range and the
   named magnitude scale; lead time and horizon; alarm rate where the arm is `AlarmSet`; the
   scoring rule; the reference baseline ([ADR-0059](0059-reference-baseline-set.md)); the as-of
   instant and the data vintage ([ADR-0054](0054-latency-aware-observation-sources.md)); the
   statistical power the design achieves against a named alternative; and the **failure criterion**
   — what result would count as the hypothesis being wrong — written before any result exists.

2. **The check.** For a pre-registration at commit `C_P` and test data introduced at commit `C_D`,
   the runner refuses to score unless

   ```
   git merge-base --is-ancestor <C_P> <C_D>
   ```

   exits 0. `C_D` is the earliest commit that added the test-data file or its DVC pointer, found
   with `git log --diff-filter=A --reverse --format=%H -- <path>`.

3. **Exit codes are distinguished, and only one of them means pass.** `0` is an ancestor; `1` is
   not an ancestor and fails; anything else — `128` when the object is not in the local repository —
   is an *error*, and the gate fails on it rather than treating it as a negative. Verified
   behaviour, not assumed: on a `--depth 1` clone the pre-registration commit is absent entirely and
   `git merge-base --is-ancestor` exits 128 with `fatal: Not a valid commit name`.

4. **The pre-registration is frozen after `C_P`.** The scoring run records the file's sha256, and
   any later commit touching that path invalidates the registration. Amendments are made by adding
   a new registration file with its own commit; the superseded one stays in the tree, because the
   record of what was originally predicted is the whole point.

5. **A shallow clone fails the gate; it does not skip it.** CLAUDE.md permits a `SKIPPED` gate only
   with a printed reason, and a skip here would be the exact failure the gate exists to prevent —
   an unverifiable registration passing because verification was unavailable. The gate calls
   `git rev-parse --is-shallow-repository` first and fails with the remedy printed. **This affects
   this repository today**: `.github/workflows/ci.yml` uses `actions/checkout@v4` with no
   `fetch-depth`, which defaults to a depth-1 clone, so every CI job in the tree currently has
   exactly one commit of history and could not run this check at all. Adding the gate therefore
   requires `fetch-depth: 0` on the offline job. Partial clones are fine: a blobless or treeless
   clone (`--filter=blob:none`) keeps the full commit graph, which is all ancestry needs.

6. **Where ancestry cannot apply, the registration is labelled weak rather than claimed strong.**
   For a replay on data already in the tree — which is most of what rupture can do today under the
   pseudo-prospective protocol (ADR-0015) — the data commit predates every possible registration
   and the ancestry check can never pass. Those results are labelled
   `preregistration: weak (data predates registration)`, and the only thing the record then asserts
   is that the registration preceded the *scoring run*. That is worth having and it is not worth
   much, and the label says which.

7. **Merges stay real merges.** CLAUDE.md's worktree rule already requires this; it is restated
   here because squash-merging would rewrite `C_P` into a commit the registration's own recorded
   hash no longer resolves to, while the ancestry check would still pass. The check would go on
   being green while the artefact it points at ceased to exist.

## Failure modes, stated plainly

The check proves ordering within a history. It does not prove that the history is the one the world
saw, and a project that advertises pre-registration while glossing over that is doing the thing
pre-registration exists to prevent.

1. **History rewriting.** `git commit --amend`, an interactive rebase or `git filter-repo` can
   place a pre-registration wherever the author likes, and the ancestry check will agree. There is
   no defence inside git. The defence is **public witness**: the registration commit must be
   reachable from a ref on the public remote, pushed before the window opens, and the scoring
   record names the commit so that anyone who cloned earlier can contradict it. Branch protection
   refuses a force-push to `main`; a force-push to any other branch is detectable but not
   prevented. A determined author who controls the remote and whose repository nobody has cloned
   can defeat this, and the honest statement is that pre-registration in a repository nobody
   watches is worth approximately nothing.
2. **Commit dates are not evidence.** Author and committer dates are supplied by the client and are
   trivially forgeable. The check deliberately uses ancestry rather than dates, and no rupture
   result may cite a commit date as a timestamp.
3. **Shallow clones.** As in decision 5. The failure is loud, which is the only acceptable
   behaviour, but it means the gate cannot run in the default CI configuration and a maintainer who
   "fixes" a red gate by re-adding `fetch-depth: 1` disables it.
4. **Data that does not live in git.** rupture's data is DVC-versioned; the bytes sit in a remote
   and the history holds a pointer. Ancestry over the pointer proves when the pointer was added,
   not when the bytes were produced or when the author first read them. A contributor who had the
   data locally before writing the registration is not caught by anything here. This is the
   fundamental limit of the retrospective form, and it is why the prospective benchmark
   ([ADR-0057](0057-prospective-open-benchmark.md)) is the strong version of this control: data
   that does not exist yet cannot have been read.
5. **Ambiguous introduction commits.** `git log --diff-filter=A` can return more than one commit
   for a path that was deleted and re-added, and returns nothing useful for some paths introduced
   through a merge. The gate takes the earliest, requires exactly one candidate, and fails with the
   candidate list printed when there is more than one — rather than picking, which would let a
   re-add launder a late registration.
6. **Everything upstream of the file.** A registration can be written honestly and still be
   post-hoc in substance, because the author has read the literature, seen the sequence on the news
   and formed the hypothesis before writing anything down. No mechanism in this repository
   addresses that. It is what the review board on nulls, and the requirement that the failure
   criterion be written first, are for.

## Consequences

- An experiment that was scored before it was registered is mechanically unpublishable in this
  tree, and the qa-reviewer's veto acquires a machine that runs before the reviewer does.
- Contributors must commit and push before they look at data. That is the intended cost and it is
  the same cost every pre-registration regime imposes.
- A new gate, `prereg`, joins the `GATES` tuple with its `mk/prereg.mk` fragment and its CI step,
  and the CI job's checkout gains `fetch-depth: 0`. Under ADR-0048's gate-coverage ratchet, a gate
  added without a CI step breaks the build.
- Most existing rupture results will be labelled `preregistration: weak`, including the whole
  challenger evaluation. That is accurate and it should be visible.

## Alternatives considered

- **A trusted third-party timestamp** (OpenTimestamps, a notary, or a commit anchored into a public
  chain). Not rejected — deferred, and recorded as the obvious answer to failure mode 1. It costs a
  dependency and a network call in a repository whose gates must run offline from a fresh clone, so
  it would have to be an opt-in step at registration time rather than part of the gate. An open
  question below.
- **Signed commits.** Kept as a complement, rejected as a substitute: a signature proves who made a
  commit, not when it entered the history.
- **External registration on OSF or AsPredicted.** Rejected as the primary mechanism because it
  cannot gate CI and it moves the record out of the repository a reader is already holding. Welcome
  as a second witness, and it does answer failure mode 1 in a way git cannot.
- **Trust the reviewer.** Rejected; that is the status quo this ADR replaces, and the reason is the
  same one ADR-0022 gives about leakage: the artefact looks correct, and it arrives as good news.
- **Compare commit dates instead of ancestry.** Rejected outright — see failure mode 2.

## Open questions

- Whether to require an external timestamp for any experiment whose result would be a positive
  claim, while leaving nulls on ancestry alone. Asymmetric, defensible, and unresolved.
- What `C_D` means for a prospective experiment, where the test data has no commit at registration
  time. The intended reading is that the check is vacuous there and the benchmark's own issue log
  is the control; that needs writing down in [ADR-0057](0057-prospective-open-benchmark.md)'s
  operational protocol rather than being inferred.
