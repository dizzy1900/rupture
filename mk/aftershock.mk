# aftershock gate registers itself (see mk/README.md)
VALIDATE_GATES += validate-aftershock

validate-aftershock: ## aftershock service: both sequences scored offline, leakage refused, probabilities well formed
	$(RUN) rupture validate aftershock

.PHONY: validate-aftershock
