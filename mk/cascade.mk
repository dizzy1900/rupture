# cascade gate (C3: triggered cascades) registers itself; see mk/README.md.
# The target is defined here rather than in the Makefile so no two worktrees edit that file.
VALIDATE_GATES += validate-cascade

.PHONY: validate-cascade
validate-cascade: ## Gorkha ground-failure reproduction, discriminator accounting, cascade contracts
	$(RUN) rupture validate cascade
