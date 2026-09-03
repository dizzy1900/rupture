"""Learned challenger models and their ensembles.

``rupture.models`` holds everything that is fitted by optimisation rather than by the ETAS
inversion: the shared dataset/CV machinery (``rupture.models.data``), the challengers under
``rupture.models.challengers`` and the log-linear ensemble under ``rupture.models.ensemble``.

Every model here is bound by ADR-0022 (leakage engineering) and scored by the same protocol as
the ETAS baseline. rupture does not predict earthquakes; these models issue expected counts per
cell and magnitude bin over a horizon.
"""
