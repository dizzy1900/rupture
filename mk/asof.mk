VALIDATE_GATES += validate-asof

.PHONY: validate-asof
validate-asof: ## data vintage: exposure of fits and targets to records revised after the cut
	$(RUN) rupture validate asof
