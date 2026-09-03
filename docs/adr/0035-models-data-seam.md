# ADR-0035: The `models/data` seam between the two challengers

- **Status:** accepted (records a known, bounded debt)
- **Date:** 2026-09-03 (UTC)

## Context

Two challengers were built concurrently in separate worktrees. `npp-researcher` owned the shared
dataset and cross-validation machinery at `rupture.models.data`; `deep-grid` needed the same
guarantees before that module existed on its branch, so it was told to work behind a thin seam it
owned (`models/challengers/gridded/_data.py`) that binds the shared names when they are present
and keeps a local implementation otherwise.

Both merged. The seam did **not** dissolve on contact, and the reason is worth recording rather
than papering over: the two implementations obey the same rules but have genuinely different
shapes.

| Seam function | Shared equivalent | Why it does not simply bind |
|---|---|---|
| `assert_before_cutoff(times, cutoff)` | `dataset.causal_slice` filters; `leakage.assert_all_before` takes a `Catalog` | the seam guards sample **window ends** (datetimes), not a catalogue |
| `causal_window(end, k, span, n)` | `windows.causal_bounds`, `dataset.time_edges` | the shared one indexes an event array; the seam returns frame bounds in epoch seconds |
| `blocked_time_forward_split(times, train_end, validation_end)` | `splits.blocked_splits` + `split_indices` | the shared one is calendar-fold CV; the seam is a single blocked cut at a named boundary |
| `TrainOnlyScaler` | `normalise.Standardiser` | the shared one is 2-D `(n, features)`; the seam is per-channel over a 5-D raster stack |

The seam self-checks each binding behaviourally and records which side it used in
`SEAM_SOURCE`/`SEAM_NOTES`, written into every persisted fit's diagnostics. So the state is
visible in the artefacts, not hidden: a fit produced through the fallback says so.

## Decision

Keep the seam, and record the reconciliation as bounded work rather than pretending it is done:

1. Replace `TrainOnlyScaler` with `normalise.Standardiser`, reshaping the stack to
   `(n·frames·cells, channels)`.
2. Add `blocked_cut(times, train_end, validation_end)` to `models/data/splits` — a single named cut
   is a legitimate second shape alongside calendar folds, not a duplicate.
3. Move `assert_before_cutoff` and `causal_window` into `models/data` as the datetime-domain
   counterparts of the event-index ones, or leave them local and say so.
4. Decide whether `dataset.build_grid_counts` should replace the seam's own rasteriser.
5. Then delete `_data.py` and import directly.

Until that is done, `seam_source` reads `gridded._data (pre-merge fallback)` in every persisted
gridded fit, and a reader can tell exactly which machinery produced a number.

## Consequences

- Two implementations of the same guarantees exist. That is duplication, and it is a real cost.
- It is **not** a correctness risk in the sense that matters: both raise on post-cutoff data, both
  are strictly causal, neither can express a shuffled split, and `validate-challengers` audits the
  resulting fits regardless of which produced them.
- The debt is visible in the artefacts rather than only in this document.

## Alternatives considered

- **Force the bind before merging.** Rejected: it would have meant one agent rewriting another's
  API blind, mid-flight, to make a shape fit that does not fit.
- **Say the seam dissolved.** Rejected: it did not, and every fit's diagnostics would contradict it.
