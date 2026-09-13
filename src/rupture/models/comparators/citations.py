"""Citations this comparator exists to keep in the same breath.

DeVries et al. (2018, doi 10.1038/s41586-018-0438-y) reported AUC 0.849 on aftershock location —
`rebutted`; Mignan & Broccardo (2019, doi 10.1038/s41586-019-1582-8) matched it with a
two-parameter logistic at AUC 0.85 — `contested`, and Meade et al. Reply (Nature 574 E4-E5, doi
10.1038/s41586-019-1583-7) is on the record in that same sentence. Independently, a
three-parameter logistic on log distance-to-rupture and log mean slip reached 0.86. Those AUC
figures are historical; this repository will not recompute them (see
:mod:`rupture.scoring.refusals`).
"""

from __future__ import annotations

DOI_DEVRIES_2018 = "10.1038/s41586-018-0438-y"
DOI_MIGNAN_BROCCARDO_2019 = "10.1038/s41586-019-1582-8"
DOI_MEADE_REPLY_2019 = "10.1038/s41586-019-1583-7"

EVIDENCE_STATUS_DEVRIES = "rebutted"
EVIDENCE_STATUS_MIGNAN = "contested"

# One sentence, both papers, the Reply, and the independent three-parameter figure. Copied into
# notes and the model card so a citation cannot travel without its status tag.
EVIDENCE_SENTENCE = (
    "DeVries et al. 2018 Nature doi 10.1038/s41586-018-0438-y reported AUC 0.849 on aftershock "
    "location — `rebutted`; Mignan & Broccardo 2019 Nature 574 E1-E3 doi "
    "10.1038/s41586-019-1582-8 matched it with two-parameter logistic AUC 0.85 — `contested`, "
    "and Meade et al. Reply Nature 574 E4-E5 doi 10.1038/s41586-019-1583-7 is on the record; "
    "independently, a three-parameter logistic on log distance-to-rupture and log mean slip "
    "reached 0.86. Those numbers are not a win for DeVries and are not recomputed here."
)

COUNT_CONVERSION_NOTE = (
    "ForecastGrid cells are expected COUNTS, not occupancy probabilities. Conversion, training "
    "window only: mean_events_per_positive_cell = n_training_events / n_positive_cells; "
    "expected_count_i = P_i * mean_events_per_positive_cell * (horizon_days / training_days). "
    "P_i is the fitted logistic occupancy of cell i. Do not read P as a count."
)
