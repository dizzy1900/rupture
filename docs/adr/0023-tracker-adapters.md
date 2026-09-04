# ADR-0023: Experiment tracking adapters

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)
- **Amended:** 2026-09-03 (UTC) — the W&B adapter and the factory now exist; the first version of
  this ADR described them in the present tense before either was written. What follows names the
  files, and § Not done yet says plainly what is still missing.

## Context

Prompt 2 trains models and needs experiment tracking. The brief names Weights & Biases, and also
requires that the repository be usable with no external account and that tests run offline.

## Decision

Tracking goes through the existing `Tracker` port (`src/rupture/ports/tracker.py`). Two adapters:

- **`JsonlTracker`** (`src/rupture/adapters/storage/run_log.py`) — the default and the only one
  used in tests and gates. Writes run records to a local JSONL file. No account, no network.
- **`WandbTracker`** (`src/rupture/adapters/storage/wandb_tracker.py`) — optional, behind the
  `wandb` extra, selected only when `WANDB_API_KEY` is set **and** the extra is installed. It never
  becomes a hard dependency, its absence is not an error, and `import wandb` happens lazily inside
  `log()`, so the offline path never touches the vendor SDK.

**The remote adapter is a mirror, not a replacement.** `WandbTracker` wraps a `JsonlTracker` and
writes to it *first*; only then does it send the same record onward. `records()` reads the local
file. So a W&B outage cannot lose a run, cannot fail a job (failures are logged at WARNING and
collected on `mirror_errors`), and cannot become the only copy of anything a report cites.

Selection is by `make_tracker(path)` in `src/rupture/adapters/storage/__init__.py`, which returns
a `Tracker` and prints the reason it chose one — `WANDB_API_KEY not set`, or the key is set but
the extra is missing, or the mirror is on and in which mode. `tracker_reason(path)` is the same
choice without the printing. Mode is `offline` unless an API key is present; `RUPTURE_WANDB_MODE`
overrides. No test may require the remote adapter, and no gate may fail because it is absent:
`tests/unit/storage/test_tracker_adapters.py` exercises the mirror against a stub module injected
through the adapter's `wandb_module` seam, so `tests/unit` stays offline and `wandb` need not be
installed to run it.

## Consequences

- A contributor with no account gets the full workflow, and is told which tracker they got.
- Runs tracked locally are the record of truth for anything a report cites; a W&B run is a
  convenience, not a citation. That is now enforced by construction rather than by convention:
  `records()` cannot read from W&B.

## Not done yet

Recorded here rather than left for a reader to discover:

- **No W&B run has ever been created.** No Prompt 2 experiment was tracked remotely; the adapter
  is exercised only against the stub. The first real run will find whatever the stub does not.
- **The four call sites still instantiate `JsonlTracker` directly** —
  `src/rupture/commands/challenger.py`, `src/rupture/commands/evaluate.py`,
  `src/rupture/commands/forecast.py`, `src/rupture/pipelines/schedule.py`,
  `src/rupture/models/challengers/ntpp/schedule.py` and
  `src/rupture/models/ensemble/protocol_runner.py`. Until they call `make_tracker`, setting
  `WANDB_API_KEY` changes nothing. Those files belong to other slices.
- **`WANDB_API_KEY` is not in `.env.example`**, so no job manifest may list it in `env` (the
  manifest test requires every name to come from that file). Adding it there is the enabling step.
- **No tracked run log survives a run.** `protocol_runner.py` writes its records to
  `reports/challenger/<region>/runs.jsonl`, which `.gitignore` excludes; the NTPP and ETAS paths
  write to `data/forecasts/<region>/runs.jsonl`, which `.gitignore` also excludes. `git ls-files`
  matches no `runs.jsonl` at all. So for every Prompt 2 challenger the tracked record of truth
  this ADR relies on was written and then lost, and the committed JSON reports are the only
  surviving evidence. Closing this needs a `.gitignore` negation for the run logs, or a
  `JsonlTracker` path that is already committed; both are shared-file changes.

## Alternatives considered

- **W&B as the primary tracker.** Rejected: it makes the repository unusable offline and puts a
  vendor account between a reviewer and the evidence.
- **A W&B-backed `records()`.** Rejected for the same reason: a reviewer would need an account to
  check a citation, and the port's read path would depend on a network call.
