"""Learned challenger models and the dataset machinery they share.

rupture does not predict earthquakes. Everything under this package produces *rate* forecasts
scored against the ETAS baseline under the protocol in ``docs/EVALUATION_PROTOCOL.md``.

Layout:

- :mod:`rupture.models.data` — the shared, model-agnostic dataset, causal-window, blocked-CV and
  normalisation machinery required by ADR-0022. Every challenger builds its inputs through it.
- :mod:`rupture.models.challengers` — one sub-package per challenger.

The rule that shapes all of it: a builder is handed a hard ``cutoff`` and **raises** on any event
at or after it. Filtering is always an explicit, separately named act
(:func:`rupture.models.data.causal_slice`), never a side effect of building a tensor.
"""

from __future__ import annotations

__all__ = ["data"]
