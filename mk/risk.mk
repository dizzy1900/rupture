# The risk gate (C2: ground motion -> loss -> avoided loss).
#
# `rupture validate risk` would be the conventional entry point, but the gate registry
# (src/rupture/validation/registry.py) and the typer application (src/rupture/cli.py) belong to
# the architect, and this worktree does not edit them. The gate module is the conventional one -
# src/rupture/validation/risk.py exposing run(repo_root) -> GateResult - so registering it is one
# line in GATES plus one line in cli.py; until then it is invoked directly and behaves the same.
VALIDATE_GATES += validate-risk

.PHONY: validate-risk
validate-risk: ## ground motion -> loss -> avoided loss, offline (GSIM vectors, intervals, contract)
	$(RUN) python -m rupture.validation.risk
