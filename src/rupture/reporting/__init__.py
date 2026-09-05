"""Figures rendered from committed evidence, for the reports under ``reports/``.

Nothing in this package fits, issues or scores anything: it
reads JSON that a scoring run already wrote and committed, and draws it. That separation is the
point — a figure here can never disagree with the evidence, because the evidence is its only
input, and it can be regenerated from a fresh clone with no model, no network and no fit.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
