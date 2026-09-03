"""Hyperparameter selection on a validation window strictly before the test window.

ADR-0022 decision 4. The rule is not "use a validation set"; it is that the validation window ends
**at or before the protocol's training cutoff**, so no configuration is ever chosen with knowledge
of a window it will later be scored on, and the chosen configuration is frozen and written down
with its hash before the first test window is scored.

:func:`select_config` enforces the first half and :func:`freeze` records the second. The record it
writes (``hyperparameters.json``) is the evidence: it carries the candidate grid, every trial's
validation score, the chosen configuration, its hash, and the window boundaries the choice was
made inside. If the schedule's forecasts do not carry that hash, they were not made by the
configuration that was frozen.

Folds come from :func:`rupture.models.data.blocked_splits`, so they are time-forward by
construction and there is no shuffle option to reach for.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np

from rupture.adapters.forecasting.leakage import LeakageError
from rupture.domain import Catalog, Region, utc_now
from rupture.models.challengers.ntpp.adapter import NeuralTPPForecaster
from rupture.models.challengers.ntpp.model import NTPPConfig, sequence_tensors
from rupture.models.data import BlockedSplit, blocked_splits, build_sequence, causal_slice

HYPERPARAMETERS_FILE = "hyperparameters.json"

#: The candidate grid. Small on purpose: with a few hundred training events, a wide search buys
#: variance, not skill, and every extra trial is another chance to launder a lucky fold into a
#: "chosen" configuration.
DEFAULT_GRID: dict[str, tuple[Any, ...]] = {
    "hidden": (8, 16),
    "n_time_basis": (4, 8),
    "background_sigma_km": (5.0, 15.0),
    "weight_decay": (0.0, 1e-3),
}


def candidate_configs(
    base: NTPPConfig | None = None, grid: dict[str, tuple[Any, ...]] | None = None
) -> list[NTPPConfig]:
    """Every combination of ``grid``, applied to ``base``. Deterministic order."""
    base = base or NTPPConfig()
    grid = DEFAULT_GRID if grid is None else grid
    keys = sorted(grid)
    return [
        base.with_(**dict(zip(keys, values, strict=True)))
        for values in product(*(grid[k] for k in keys))
    ]


@dataclass(frozen=True)
class FoldScore:
    """One configuration's out-of-sample score on one fold."""

    fold: int
    train_cutoff: datetime
    score_start: datetime
    score_end: datetime
    n_events: int
    total_log_likelihood: float
    tll: float
    sll: float
    converged: bool
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fold": self.fold,
            "train_cutoff": self.train_cutoff.isoformat(),
            "score_start": self.score_start.isoformat(),
            "score_end": self.score_end.isoformat(),
            "n_events": self.n_events,
            "total_log_likelihood": self.total_log_likelihood,
            "tll": self.tll,
            "sll": self.sll,
            "nll": -(self.tll + self.sll),
            "converged": self.converged,
            "note": self.note,
        }


@dataclass(frozen=True)
class Trial:
    """One configuration, scored across every fold."""

    config: NTPPConfig
    folds: tuple[FoldScore, ...]

    @property
    def n_events(self) -> int:
        return sum(f.n_events for f in self.folds)

    @property
    def mean_nll(self) -> float:
        """Event-weighted negative log-likelihood per validation event; lower is better.

        Weighting by events rather than by fold means a fold holding two events does not carry the
        same weight as one holding two hundred. With sequences this uneven, the alternative
        silently hands the choice to the quietest period in the catalogue.
        """
        n = self.n_events
        if n == 0:
            return float("inf")
        return -sum((f.tll + f.sll) * f.n_events for f in self.folds) / n

    @property
    def all_converged(self) -> bool:
        return all(f.converged for f in self.folds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "config": self.config.to_dict(),
            "config_hash": self.config.config_hash(),
            "mean_nll": self.mean_nll,
            "n_validation_events": self.n_events,
            "all_converged": self.all_converged,
            "folds": [f.to_dict() for f in self.folds],
        }


@dataclass(frozen=True)
class Selection:
    """The frozen record of a hyperparameter choice."""

    chosen: NTPPConfig
    trials: tuple[Trial, ...]
    splits: tuple[BlockedSplit, ...]
    region_id: str
    mc: float
    train_start: datetime
    validation_end: datetime
    hard_cutoff: datetime
    selected_at: datetime

    @property
    def chosen_hash(self) -> str:
        return self.chosen.config_hash()

    def to_dict(self) -> dict[str, Any]:
        return {
            "chosen": self.chosen.to_dict(),
            "chosen_config_hash": self.chosen_hash,
            "region_id": self.region_id,
            "mc": self.mc,
            "train_start": self.train_start.isoformat(),
            "validation_end": self.validation_end.isoformat(),
            "hard_cutoff": self.hard_cutoff.isoformat(),
            "selected_at": self.selected_at.isoformat(),
            "splits": [s.to_dict() for s in self.splits],
            "trials": [t.to_dict() for t in self.trials],
            "rule": (
                "hyperparameters chosen only on windows ending at or before the hard cutoff "
                "(ADR-0022 decision 4); the chosen configuration is frozen and its hash recorded "
                "before any test window is scored"
            ),
        }

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n", "utf-8")
        return path


def score_config(
    catalog: Catalog,
    region: Region,
    config: NTPPConfig,
    *,
    mc: float,
    train_cutoff: datetime,
    score_start: datetime,
    score_end: datetime,
    auxiliary_years: float = 0.5,
    convergence_tol: float = 1e-2,
    patience: int = 50,
    fold: int = 0,
) -> FoldScore:
    """Fit on ``origin_time < train_cutoff``, then score the log-likelihood on the score window.

    The score is the point-process log-likelihood of the events in ``[score_start, score_end)``
    under the fitted parameters, conditioned on every earlier event. It is out of sample in the
    only sense that matters for a point process: the parameters never saw those events.

    This function makes no judgement about *where* the score window sits. :func:`select_config` is
    what refuses a window after the hard cutoff; the deliberately leaky ablation calls this
    directly, which is exactly why the refusal lives one level up and is spelled out there.
    """
    if not (train_cutoff <= score_start < score_end):
        msg = "need train_cutoff <= score_start < score_end"
        raise ValueError(msg)
    model = NeuralTPPForecaster(
        config,
        auxiliary_years=auxiliary_years,
        convergence_tol=convergence_tol,
        patience=patience,
    )
    try:
        fit = model.fit(catalog, region, train_cutoff, mc=mc)
    except (ValueError, LeakageError) as exc:
        return FoldScore(
            fold=fold,
            train_cutoff=train_cutoff,
            score_start=score_start,
            score_end=score_end,
            n_events=0,
            total_log_likelihood=float("-inf"),
            tll=float("-inf"),
            sll=float("-inf"),
            converged=False,
            note=f"fit failed: {exc}",
        )
    net, features = model.net, model.features
    if net is None or features is None:  # pragma: no cover - set by a successful fit
        msg = "fit returned without a network"
        raise RuntimeError(msg)

    scored = causal_slice(catalog, region, score_end, mc)
    sequence = build_sequence(
        scored,
        region,
        score_end,
        mc=mc,
        epoch=datetime.fromisoformat(fit.diagnostics["epoch"]),
        projection=model.projection,
    )
    n_in_window = int(
        np.count_nonzero(
            (sequence.t >= sequence.days_of(score_start))
            & (sequence.t < sequence.days_of(score_end))
        )
    )
    if n_in_window == 0:
        return FoldScore(
            fold=fold,
            train_cutoff=train_cutoff,
            score_start=score_start,
            score_end=score_end,
            n_events=0,
            total_log_likelihood=0.0,
            tll=0.0,
            sll=0.0,
            converged=bool(fit.converged),
            note="no events in the score window",
        )
    ll = net.log_likelihood(
        **sequence_tensors(sequence, features),
        window_start=sequence.days_of(score_start),
        window_end=sequence.days_of(score_end),
    )
    return FoldScore(
        fold=fold,
        train_cutoff=train_cutoff,
        score_start=score_start,
        score_end=score_end,
        n_events=ll.n_events,
        total_log_likelihood=ll.total,
        tll=ll.tll,
        sll=ll.sll,
        converged=bool(fit.converged),
    )


def select_config(
    catalog: Catalog,
    region: Region,
    *,
    mc: float,
    train_start: datetime,
    validation_end: datetime,
    hard_cutoff: datetime,
    candidates: Sequence[NTPPConfig] | None = None,
    n_folds: int = 2,
    gap: timedelta = timedelta(0),
    auxiliary_years: float = 0.5,
    min_train: timedelta | None = None,
) -> Selection:
    """Choose a configuration on blocked time-forward folds ending at or before ``hard_cutoff``.

    Raises :class:`~rupture.adapters.forecasting.leakage.LeakageError` if ``validation_end`` is
    after ``hard_cutoff`` — that is the whole point of the function, and it refuses rather than
    trimming, so a mis-specified window is a failure and not a quietly different experiment.
    """
    if validation_end > hard_cutoff:
        msg = (
            f"leakage: the validation window ends {validation_end.isoformat()}, after the hard "
            f"cutoff {hard_cutoff.isoformat()}; hyperparameters would be chosen with knowledge of "
            "the test period (ADR-0022 decision 4)"
        )
        raise LeakageError(msg)
    configs = list(candidates) if candidates is not None else candidate_configs()
    if not configs:
        msg = "no candidate configurations"
        raise ValueError(msg)
    splits = blocked_splits(
        train_start, validation_end, n_folds, gap=gap, expanding=True, min_train=min_train
    )
    trials: list[Trial] = []
    for config in configs:
        folds = tuple(
            score_config(
                catalog,
                region,
                config,
                mc=mc,
                train_cutoff=split.train_end,
                score_start=split.val_start,
                score_end=split.val_end,
                auxiliary_years=auxiliary_years,
                fold=split.fold,
            )
            for split in splits
        )
        trials.append(Trial(config=config, folds=folds))

    usable = [t for t in trials if t.n_events > 0 and np.isfinite(t.mean_nll)]
    if not usable:
        msg = "every candidate failed to score; check the validation window and the catalogue"
        raise ValueError(msg)
    converged = [t for t in usable if t.all_converged]
    pool = converged or usable
    chosen = min(pool, key=lambda t: t.mean_nll)
    return Selection(
        chosen=chosen.config,
        trials=tuple(trials),
        splits=tuple(splits),
        region_id=region.id,
        mc=mc,
        train_start=train_start,
        validation_end=validation_end,
        hard_cutoff=hard_cutoff,
        selected_at=utc_now(),
    )


def freeze(selection: Selection, out_dir: Path) -> Path:
    """Write the frozen record. Do this **before** scoring any test window, not after."""
    return selection.write(Path(out_dir) / HYPERPARAMETERS_FILE)


def load_frozen(path: Path) -> tuple[NTPPConfig, dict[str, Any]]:
    """Read back a frozen record and check the stored hash still matches the stored config."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    config = NTPPConfig.from_dict(raw["chosen"])
    if config.config_hash() != raw["chosen_config_hash"]:
        msg = (
            f"the frozen record at {path} has been edited: its configuration hashes to "
            f"{config.config_hash()[:12]} but records {raw['chosen_config_hash'][:12]}"
        )
        raise ValueError(msg)
    return config, raw
