# Experiments

A pre-registration is a committed file at `experiments/<id>/preregistration.yaml`. Git
ancestry is the timestamp (ADR-0056). The `validate-prereg` gate reads every such file,
checks the schema, records the file's sha256, and classifies each declared test-data
path against the registration's add-commit.

There are no scored experiments in this directory yet. Zero registrations is a **pass**,
not a skip: the gate reports `no experiments registered`.

Names starting with `_` are ignored (templates, notes). `README.md` is not an experiment.
Do not put a fake experiment here to "have an example" — the YAML below is a template
in a fenced block, not a registration the gate will score.

## File format

Every field is required except `alarm_rate` (required only when `arm` is `alarm_set`)
and `preregistration_commit` (filled when the gate checks the file; leave it off when
writing the registration). Extra keys are forbidden. The document is frozen after its
add-commit: later edits to the same path invalidate it. Amendments are a **new** file.

| Field | What it is |
|---|---|
| `experiment_id` | Must match the directory name |
| `hypothesis` | One sentence, written before any result exists |
| `arm` | `rate_forecast` / `simulated_catalogues` / `alarm_set` / `hazard_function` / `state_estimate` |
| `region_id` | Test region id |
| `magnitude_min`, `magnitude_max`, `magnitude_scale` | Closed range and the named scale (e.g. `Mw (ANSS preferred)`) |
| `lead_time`, `horizon` | Durations as `7d` / `12h` / `1w` / `1y`, or ISO-8601 (`P7D`) |
| `alarm_rate` | Declared alarm fraction in `(0, 1]`; required for `alarm_set` |
| `scoring_rule` | How the arm will be scored |
| `reference_baseline` | The adversary the claim must beat (ADR-0059) |
| `as_of` | UTC instant for the evaluation vintage (quote it, e.g. `"2026-01-01T00:00:00Z"`) |
| `data_vintage` | Prose description of that vintage |
| `statistical_power` | `alpha`, `target_power`, and `effect` (the named alternative) |
| `failure_criterion` | What result would count as the hypothesis being wrong |
| `test_data_paths` | Repository-relative paths whose *add* commits are C_D. Use the DVC pointer, not the remote bytes. `[]` if the test data does not exist yet (prospective): ancestry is then vacuous |
| `preregistration_commit` | Optional. When set, must equal the file's unique add-commit |

Ancestry:

- **strong** — the registration commit is an ancestor of the data commit.
- **weak (data predates registration)** — the data was already in the tree. Most of what
  rupture can do under the pseudo-prospective protocol is this, and the label says so.
- **fail** — in-place amendment, a re-add with more than one add-commit, or a claim of
  the strong form when the data predates the registration.
- **error** — git failed, the clone is shallow, or an object is missing (exit 128). A
  shallow clone is an error, not a skip. CI must use `fetch-depth: 0`.

## Template (not a registered experiment)

```yaml
experiment_id: example-template
hypothesis: >
  An ETAS-matched random alarm set has area skill consistent with one half at 7-day
  lead for M ≥ 6 in California.
arm: alarm_set
region_id: california
magnitude_min: 6.0
magnitude_max: 9.0
magnitude_scale: Mw (ANSS preferred)
lead_time: 7d
horizon: 30d
alarm_rate: 0.05
scoring_rule: molchan_area_skill
reference_baseline: >
  ETAS-derived alarms and a random alarm set matched on alarm rate and spatial footprint
as_of: "2026-01-01T00:00:00Z"
data_vintage: >
  ComCat California fixture as of the as_of instant; C_D is the DVC pointer, not the
  remote catalogue bytes.
statistical_power:
  alpha: 0.05
  target_power: 0.8
  effect: probability gain G=2 against the clustering-aware reference
failure_criterion: >
  Area skill score consistent with 0.5, or a minimum detectable G greater than 2 at
  the declared alarm rate.
test_data_paths:
  - data/fixtures/catalogs/california/provenance.json
# preregistration_commit: filled by the gate; omit when writing
```
