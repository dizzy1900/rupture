VALIDATE_GATES += validate-observe

.PHONY: validate-observe
validate-observe: ## observation fixtures parse; NGL as-of is half-open on available_time
	$(RUN) rupture validate observe
