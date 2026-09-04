VALIDATE_GATES += validate-challengers

.PHONY: validate-challengers
validate-challengers: ## promotion rule recomputed from the committed evidence + leakage controls
	$(RUN) rupture validate challengers
