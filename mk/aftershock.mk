# The aftershock gate registers itself (see mk/README.md). Unlike the six Prompt-1 gates it also
# has to define its own target: `aftershock` is a new gate name, so the Makefile has no rule for
# it, and the Makefile is not edited by a worktree. The recipe is the same one line every gate
# uses. No `## ` help comment: `make help` greps every file in MAKEFILE_LIST and would print the
# fragment's filename instead of the target name.
VALIDATE_GATES += validate-aftershock

.PHONY: validate-aftershock
validate-aftershock:
	$(RUN) rupture validate aftershock
