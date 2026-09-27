VALIDATE_GATES += validate-prereg

.PHONY: validate-prereg
validate-prereg: ## pre-registration: schema plus git ancestry (ADR-0056); errors on a shallow clone
	$(RUN) rupture validate prereg
