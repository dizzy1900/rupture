"""Metrics the registry will not compute, and the published result each one produced.

ADR-0055 decision 6. These are functions rather than a documentation list because a rule that
lives only in prose gets rediscovered by the next person to reach for ``sklearn.metrics``. Calling
one raises and hands back the citation, which is cheaper than reviewing the paper that used it.
"""

from __future__ import annotations

from typing import Any, NoReturn

from rupture.scoring.errors import RefusedMetricError

REFUSED: dict[str, str] = {
    "auc": (
        "AUC or accuracy on imbalanced grid cells. Jover-Alfaro et al. (2026, `negative-result`) "
        "replicated a published Random Forest at 97.97 % accuracy and watched it fall to 21-24 % "
        "under walk-forward validation against a 27.69 % baseline, and to 16 % cross-region. "
        "DeVries et al. (2018, doi 10.1038/s41586-018-0438-y) reported AUC 0.849 on aftershock "
        "location and was matched by a two-parameter logistic regression at AUC 0.85 (Mignan & "
        "Broccardo 2019, doi 10.1038/s41586-019-1582-8; Meade et al. reply doi "
        "10.1038/s41586-019-1583-7) -- `rebutted`, and never cited here without that reply. "
        "For a spatial claim use the area skill score, which weights by events on one axis and "
        "by the reference measure on the other."
    ),
    "accuracy": "@auc (the same refusal, the same replication)",
    "rmse": (
        "RMSE or MAE on power-law targets. Magnitudes and moments are heavy-tailed, so a squared "
        "or absolute error is dominated by the few events anyone cares about predicting and is "
        "minimised by predicting the mean. Score a distribution, not a point."
    ),
    "mae": "@rmse (the same refusal)",
    "parimutuel": (
        "The parimutuel gambling score is improper: a forecaster can raise its expected score by "
        "stating something other than its true belief."
    ),
    "random_split": (
        "Any split that is not chronological (ADR-0022 rule 3). A random split over a clustered "
        "catalogue puts an aftershock in train and its mainshock in test."
    ),
}


def reason_for(metric: str) -> str:
    """The full reason ``metric`` is refused, with any cross-reference resolved in place.

    An entry may point at another with ``@name``, and the pointer is expanded here rather than
    left for the reader to follow: a refusal that says only "see the other one" is a refusal
    somebody will override, because the argument is not in front of them at the moment they are
    deciding.
    """
    key = metric.strip().lower()
    entry = REFUSED.get(key)
    if entry is None:
        return (
            f"{metric!r} is not a registered scorer. Register it with its mandatory reference and "
            "its power calculation, or use one that is."
        )
    if entry.startswith("@"):
        target, _, note = entry[1:].partition(" ")
        return f"{REFUSED[target]} {note}".strip()
    return entry


def refuse(metric: str, **_: Any) -> NoReturn:
    """Raise with the reason ``metric`` is refused. Unknown names are refused too, by default."""
    msg = f"refused metric {metric!r}: {reason_for(metric)}"
    raise RefusedMetricError(msg)


def auc(*_: Any, **__: Any) -> NoReturn:
    """Refused. Use :func:`rupture.scoring.molchan.area_skill_score`."""
    refuse("auc")


def accuracy(*_: Any, **__: Any) -> NoReturn:
    """Refused. See :func:`auc`."""
    refuse("accuracy")


def rmse(*_: Any, **__: Any) -> NoReturn:
    """Refused on power-law targets."""
    refuse("rmse")


def parimutuel(*_: Any, **__: Any) -> NoReturn:
    """Refused: improper scoring rule."""
    refuse("parimutuel")
