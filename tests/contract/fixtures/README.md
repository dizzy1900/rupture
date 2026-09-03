# Contract fixtures

Illustrative payloads that exercise the JSON Schemas in `contracts/`. They are **examples of the
contract shape, not data**: the portfolio values and probabilities are made up for schema testing
and are labelled as such inside each file. Real catalogue fixtures live in `data/fixtures/` with
`provenance.json`.

- `avoided-loss.request.example.json` — an `AvoidedLossRequest`; used by `rupture underwriting-check`.
- `serac/source-type-assessment.example.json` — a `SourceTypeAssessment` as the sibling `serac`
  repository would write it. The event id is real (ComCat `us7000tbwb`, type=landslide); the
  probabilities are not.
