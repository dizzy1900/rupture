"""Normalisation statistics fitted on training data only, and carried with the model.

ADR-0022 decision 5. The failure mode this guards against is quiet: standardise a feature matrix
over the whole catalogue, then split it, and the training features already encode the validation
period's mean and spread. Nothing raises, the code looks tidy, and the score improves.

So a :class:`Standardiser` is fitted from an explicit set of rows and records what it saw. The
convenience constructor :meth:`Standardiser.fit_causal` takes a cut time and refuses any row at or
after it, exactly as the dataset builders do. The fitted statistics serialise to a plain dict and
travel inside the model's parameter snapshot, so a reloaded model normalises identically and its
snapshot hash changes if the statistics change.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import numpy.typing as npt

from rupture.adapters.forecasting.leakage import LeakageError

_F8 = npt.NDArray[np.float64]

MIN_SCALE = 1e-8


@dataclass(frozen=True)
class Standardiser:
    """Per-column ``(x - mean) / scale``, with the rows it was fitted on recorded."""

    names: tuple[str, ...]
    mean: _F8
    scale: _F8
    n_rows_fitted: int
    fitted_before: datetime | None = None

    def __post_init__(self) -> None:
        if self.mean.shape != (len(self.names),) or self.scale.shape != (len(self.names),):
            msg = "mean and scale must have one entry per column name"
            raise ValueError(msg)
        if bool(np.any(self.scale <= 0.0)):
            msg = "scale entries must be positive"
            raise ValueError(msg)

    @property
    def n_features(self) -> int:
        return len(self.names)

    def transform(self, x: npt.ArrayLike) -> _F8:
        a = np.asarray(x, dtype=np.float64)
        if a.ndim != 2 or a.shape[1] != self.n_features:
            msg = f"expected a (n, {self.n_features}) matrix, got {a.shape}"
            raise ValueError(msg)
        out: _F8 = (a - self.mean) / self.scale
        return out

    def inverse_transform(self, z: npt.ArrayLike) -> _F8:
        a = np.asarray(z, dtype=np.float64)
        out: _F8 = a * self.scale + self.mean
        return out

    # ------------------------------------------------------------------ fitting
    @classmethod
    def fit(
        cls,
        x: npt.ArrayLike,
        names: Sequence[str],
        *,
        fitted_before: datetime | None = None,
    ) -> Standardiser:
        """Fit on exactly the rows given. The caller is responsible for those being training rows.

        Prefer :meth:`fit_causal`, which proves it.
        """
        a = np.asarray(x, dtype=np.float64)
        if a.ndim != 2:
            msg = f"expected a 2-D feature matrix, got shape {a.shape}"
            raise ValueError(msg)
        if a.shape[1] != len(names):
            msg = f"{a.shape[1]} columns but {len(names)} names"
            raise ValueError(msg)
        if a.shape[0] == 0:
            msg = "cannot fit normalisation statistics on zero rows"
            raise ValueError(msg)
        mean = a.mean(axis=0)
        scale = a.std(axis=0)
        # A constant column has zero spread; leave it alone rather than dividing by ~0.
        scale = np.where(scale < MIN_SCALE, 1.0, scale)
        return cls(
            names=tuple(names),
            mean=mean,
            scale=scale,
            n_rows_fitted=int(a.shape[0]),
            fitted_before=fitted_before,
        )

    @classmethod
    def fit_causal(
        cls,
        x: npt.ArrayLike,
        names: Sequence[str],
        *,
        times: npt.ArrayLike,
        epoch: datetime,
        before: datetime,
    ) -> Standardiser:
        """Fit on rows whose event time is strictly before ``before``; **raise** if any is not.

        Like the dataset builders, this refuses rather than filters: if validation rows reached
        the normaliser, something upstream handed them over, and that is the bug worth surfacing.
        """
        t = np.asarray(times, dtype=np.float64)
        a = np.asarray(x, dtype=np.float64)
        if t.shape[0] != a.shape[0]:
            msg = f"{a.shape[0]} feature rows but {t.shape[0]} times"
            raise ValueError(msg)
        limit = (before - epoch).total_seconds() / 86400.0
        late = int(np.count_nonzero(t >= limit))
        if late:
            msg = (
                f"leakage: {late} row(s) handed to the normaliser are at or after "
                f"{before.isoformat()}; normalisation statistics must be fitted on training data "
                "only (ADR-0022 decision 5)"
            )
            raise LeakageError(msg)
        return cls.fit(a, names, fitted_before=before)

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict[str, Any]:
        return {
            "names": list(self.names),
            "mean": [float(v) for v in self.mean],
            "scale": [float(v) for v in self.scale],
            "n_rows_fitted": self.n_rows_fitted,
            "fitted_before": self.fitted_before.isoformat() if self.fitted_before else None,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Standardiser:
        before = raw.get("fitted_before")
        return cls(
            names=tuple(raw["names"]),
            mean=np.asarray(raw["mean"], dtype=np.float64),
            scale=np.asarray(raw["scale"], dtype=np.float64),
            n_rows_fitted=int(raw["n_rows_fitted"]),
            fitted_before=datetime.fromisoformat(before) if before else None,
        )

    def digest(self) -> str:
        """Compact, stable text form; folded into a model's parameter snapshot hash."""
        parts = [
            f"{n}:{m:.10g}:{s:.10g}"
            for n, m, s in zip(self.names, self.mean.tolist(), self.scale.tolist(), strict=True)
        ]
        return "|".join(parts)
