"""Port: CSEP-style forecast evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from rupture.domain import Catalog, EvaluationResult, ForecastGrid, TestName


@runtime_checkable
class Evaluator(Protocol):
    evaluator_version: str

    def evaluate(
        self,
        forecast: ForecastGrid,
        target: Catalog,
        tests: Sequence[TestName],
        *,
        n_simulations: int = 1000,
        alpha: float = 0.05,
        seed: int | None = None,
    ) -> list[EvaluationResult]: ...

    def compare(
        self,
        forecast: ForecastGrid,
        benchmark: ForecastGrid,
        target: Catalog,
        *,
        alpha: float = 0.05,
    ) -> list[EvaluationResult]:
        """Paired T- and W-tests of ``forecast`` against ``benchmark``."""
        ...

    def plot_bundle(
        self,
        forecast: ForecastGrid,
        target: Catalog,
        results: Sequence[EvaluationResult],
        out_dir: Path,
    ) -> list[Path]: ...
