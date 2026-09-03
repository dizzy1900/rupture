# Scheduler: daily issuance and rolling evaluation

This page describes how rupture's forecasts are issued and scored on a calendar. It is a
description, not an implementation: Prompt 1 ships the commands and the pseudo-prospective runner
(`rupture evaluate schedule`), and ADR-0016 fixes that the scheduler itself is platform glue
around portable job manifests in `infra/jobs/`. rupture does not predict earthquakes; the
schedule issues rate forecasts and records how they scored.

## Cadence

| Job | When (UTC) | Command |
|---|---|---|
| Catalogue refresh | daily, 02:00 | `rupture catalog build --region <r> --from <start> --to <today>` |
| Issue forecasts | daily, 03:00, per region and horizon (1 d, 7 d, 30 d) | `rupture forecast issue --model etas --region <r> --horizon <h> --issue <today>T00:00:00Z --n-simulations 1000 --seed <yyyymmdd>` |
| Score closed windows | daily, 03:30 | `rupture evaluate run --forecast <id>` for every archived forecast whose window closed before the catalogue end and has no result yet |
| Refit | 1 January, 01:00 (before that day's issuance), per region | `rupture forecast fit --model etas --region <r> --cutoff <year>-01-01T00:00:00Z` |
| Schedule report | after each scoring run | `rupture evaluate schedule --region <r> --model etas --from 2022-01-01T00:00:00Z --to <today> --step 30d` (re-uses archived fits and forecasts; re-scores nothing that has a result) |

The 365 d horizon is issued at refit boundaries only.

## Idempotence

Every job is safe to re-run:

- a forecast is keyed by `ForecastGrid.id = <model>-<region>-<issue>-<horizon>`; re-issuing the
  same id overwrites the zarr store and STAC item with an identical grid (same fit, same history,
  same seed);
- a fit is keyed by `(region, cutoff)` under `baselines/etas/<region>/`; the refit job skips when
  a converged fit with that cutoff exists;
- scoring writes `reports/eval/<forecast_id>/`; a window already holding `results.json` for the
  current catalogue build hash is skipped; a *new* catalogue build hash produces a new result set
  next to the old one (protocol § 9), never an overwrite;
- the run log (`data/forecasts/<region>/runs.jsonl`) is append-only; duplicates carry distinct
  `run_id`s and are harmless.

Cron-style triggers therefore need no locking beyond "one instance per region at a time".

## Inputs

- `data/regions/<region>/region.json` — polygon, thresholds, fitted Mc (catalog-engineer).
- `data/catalogs/<region>/` — `events.parquet`, `catalog.meta.json`, `homogenisation_log.jsonl`.
- `baselines/etas/<region>/` — the current fit (`fit_result.json`, `parameters.json`,
  `diagnostics.json`).
- The seed convention: `--seed` = the issue date as `yyyymmdd`, so a re-run reproduces the grid.

## Refit calendar

Refits happen only at declared boundaries — 1 January 00:00:00 UTC of each year (protocol § 6,
ADR-0015) — using events with `origin_time < boundary`. Each refit is logged as a `refit` run
record with the boundary, the new `parameter_snapshot_hash` and the training catalogue hash, and
`parameters.json` in `baselines/` is DVC-versioned so every past parameter set stays retrievable.
Between boundaries `parameter_snapshot_hash` is constant; the schedule runner fails otherwise. An
out-of-calendar refit (for example after a network change alters Mc) needs an ADR before it runs.

## What is archived

| Artefact | Location | Versioning |
|---|---|---|
| Forecast grids | `data/forecasts/<region>/<model>/<id>.zarr` + `<id>.stac.json`; `collection.json` per directory | DVC |
| Fits | `baselines/etas/<region>/` | DVC |
| Results | `reports/eval/<forecast_id>/{results.json,target.parquet,summary.json,*.png}` | not committed; schedule reports that inform `RELEASE_STATUS.md` are DVC-tracked |
| Schedule aggregates | `reports/eval/schedule-<region>-<model>.json` | DVC |
| Run log | `data/forecasts/<region>/runs.jsonl` | DVC |

Archiving the grid *before* its window opens is what turns the pseudo-prospective replay into a
prospective record; the STAC item's `datetime` is the issue time, and the file's mtime is the
proof.

## Failure handling

- **Catalogue refresh fails** (network, provider outage): issuance still runs on the last good
  catalogue and the run record notes the catalogue build hash used; scoring is deferred, never
  performed against a partial catalogue.
- **Fit does not converge**: the fit is persisted with `converged=false`, the refit record says
  so, issuance refuses to use it and keeps the previous converged fit; the on-call reviewer files
  an ADR if the previous fit is to be kept past the boundary.
- **Issuance fails** (for example the history contains an event at or after the issue time
  because of a clock or timezone error): `LeakageError`, non-zero exit, no grid written. Nothing
  downstream runs for that region that day.
- **Scoring fails** for one forecast: that forecast is left without a result and is retried on
  the next run; other forecasts are unaffected.
- **Plots cannot be produced** (headless, missing fonts): the result JSON is still written and
  `summary.json` lists the skipped plots with the reason.
- Every failure is a non-zero exit with the exception text in the job log; there is no silent
  skip.

## Job manifests (`infra/jobs/`, ADR-0016)

| Manifest | Purpose |
|---|---|
| `build-catalog.yaml` | daily catalogue refresh per region |
| `fit-etas.yaml` | yearly refit per region |
| `issue-forecast.yaml` | daily issuance per region and horizon |
| `evaluate-schedule.yaml` | scoring of closed windows and the schedule report |
| `oq-classical.yaml` | hazard runs (hazard-engineer) |

Each manifest carries `name`, `image`, `command`, `inputs`/`outputs` (DVC paths), `resources`,
an informational `schedule` and an `aws:` annotation block. The scheduler that fires them (cron,
AWS Batch/EventBridge, or a laptop `make`) is outside the repository.
