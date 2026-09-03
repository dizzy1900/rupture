# ADR-0003 — Python 3.12, uv, ruff, mypy --strict, pytest with sockets disabled

- **Status:** accepted
- **Date:** 2026-09-03

## Context

The brief fixes the language and tooling. The `etas` baseline package requires Python ≥ 3.12;
pycsep 0.8.0 supports 3.12 with binary wheels (cartopy, rasterio) on Linux and macOS-arm64. The
offline test suite must be provably offline (non-negotiable 4).

## Decision

- **Python 3.12** only (`requires-python = ">=3.12,<3.13"`, `.python-version`), managed and locked
  with **uv** (`uv.lock` committed; CI uses `uv sync --locked`).
- **ruff** for linting and formatting (rule sets `E F W I UP B SIM RUF PL N ANN T20 DTZ PT`;
  `DTZ` makes naive datetimes a lint error, supporting the UTC-everywhere rule).
- **mypy --strict** with the pydantic plugin; third-party scientific packages without stubs are
  `ignore_missing_imports` at the adapter boundary only.
- **pytest** with **pytest-xdist** (`-n auto`), `--strict-markers`, and the marker `integration`
  for network/Docker tests, deselected by default (`addopts = -m 'not integration'`).
- **pytest-socket**: `make test` runs `pytest tests/unit tests/contract --disable-socket
  --allow-unix-socket`, so any network call in the offline suite raises immediately.
- **import-linter** enforces ADR-0002.

## Consequences

- One reproducible environment for developers, CI and the Docker image.
- A unit test cannot quietly depend on the network; a test that needs it must be marked
  `integration` and is opt-in (`make test-integration`).
- `mypy --strict` forces explicit typing at every adapter boundary, which is where most data
  bugs live.
- Python 3.13 is excluded until the `etas` and pycsep dependency trees support it.

## Alternatives considered

- **Poetry / pip-tools.** Rejected: uv is faster, locks the dev group, and installs Python.
- **Allow network in unit tests with cassettes (VCR).** Rejected: cassettes are a second source
  of possibly stale, possibly edited data; real committed slices with provenance are clearer.
- **mypy non-strict or pyright.** Rejected by the brief.
