VALIDATE_GATES += validate-challengers

.PHONY: validate-challengers
validate-challengers: ## challenger leakage controls and fit honesty (promotion rule evidence)
	$(RUN) rupture validate challengers
