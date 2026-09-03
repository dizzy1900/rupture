# ADR-0023: Experiment tracking adapters

- **Status:** accepted
- **Date:** 2026-09-03 (UTC)

## Context

Prompt 2 trains models and needs experiment tracking. The brief names Weights & Biases, and also
requires that the repository be usable with no external account and that tests run offline.

## Decision

Tracking goes through the existing `Tracker` port. Two adapters:

- **`JsonlTracker`** (already shipped) — the default and the only one used in tests and gates.
  Writes run records to a local JSONL file. No account, no network.
- **`WandbTracker`** — optional, behind the `wandb` extra, selected only when `WANDB_API_KEY` is
  set and the extra is installed. It never becomes a hard dependency, and its absence is not an
  error.

Selection is by a factory that falls back to the local adapter with a printed reason. No test may
require the remote adapter, and no gate may fail because it is absent.

## Consequences

- A contributor with no account gets the full workflow.
- Runs tracked locally are the record of truth for anything a report cites; a W&B run is a
  convenience, not a citation.

## Alternatives considered

- **W&B as the primary tracker.** Rejected: it makes the repository unusable offline and puts a
  vendor account between a reviewer and the evidence.
