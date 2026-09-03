# rupture — make targets are the gates. See CLAUDE.md.
# Every validate-* target must be runnable offline from a fresh clone after `uv sync`.

UV ?= uv
RUN := $(UV) run
PYTEST_ARGS ?= -n auto

.DEFAULT_GOAL := help

.PHONY: help setup lint typecheck test test-integration \
        validate-language validate-catalog validate-etas validate-eval validate-hazard \
        validate-rupture promote underwriting-check schema-export schema-check clean

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-22s %s\n", $$1, $$2}'

setup: ## install the locked environment (dev group included)
	$(UV) sync

# ------------------------------------------------------------------ static
lint: ## ruff check + format check + import-linter
	$(RUN) ruff check src tests
	$(RUN) ruff format --check src tests
	$(RUN) lint-imports

typecheck: ## mypy --strict
	$(RUN) mypy

# ------------------------------------------------------------------ tests
test: ## offline unit + contract suite (sockets disabled)
	$(RUN) pytest tests/unit tests/contract $(PYTEST_ARGS) --disable-socket --allow-unix-socket

test-integration: ## opt-in: network / Docker tests
	$(RUN) pytest tests/integration -m integration -ra

# ------------------------------------------------------------------ gates
validate-language: ## banned-phrase scan (rupture does not predict earthquakes)
	$(RUN) rupture validate language

validate-catalog: ## catalogue schema, provenance, Mc present, no duplicates, landslide events retained
	$(RUN) rupture validate catalog

validate-etas: ## ETAS fit diagnostics present, parameters plausible, forecast sums finite
	$(RUN) rupture validate etas

validate-eval: ## CSEP harness runs on fixtures; leakage assertion passes
	$(RUN) rupture validate eval

validate-hazard: ## OpenQuake demo runs in the pinned Docker image (skips with reason if Docker absent)
	$(RUN) rupture validate hazard

schema-export: ## regenerate contracts/*.json from the domain models
	$(RUN) rupture schema export

schema-check: ## fail if contracts/*.json drift from the domain models
	$(RUN) rupture schema export --check

# The aggregate. Phase-2 targets are appended here as they land (append-only section).
validate-rupture: lint typecheck test validate-language ## everything, offline (schema-check joins in Phase 1)
	@echo "validate-rupture: green"

promote: ## refuse unless validate-rupture is green; then print the promotion record
	@$(MAKE) --no-print-directory validate-rupture || { echo "promote: REFUSED (validate-rupture not green)"; exit 1; }
	$(RUN) rupture promote

underwriting-check: ## AvoidedLossRequest round-trip; exits non-zero: not implemented (Prompt 2)
	$(RUN) rupture underwriting-check

clean: ## remove caches
	rm -rf .mypy_cache .ruff_cache .pytest_cache .import_linter_cache reports
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
