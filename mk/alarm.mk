VALIDATE_GATES += validate-alarm

.PHONY: validate-alarm
validate-alarm: ## AlarmSet arm: registry refusals, Molchan/ASS calibration, power, reference effect
	$(RUN) rupture validate alarm
