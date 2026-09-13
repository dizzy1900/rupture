"""Mignan & Broccardo (2019) two-parameter logistic / "one-neuron" spatial aftershock comparator.

This is the mandatory straw-man for any spatial aftershock or static-stress classification claim
(ADR-0059). It implements :class:`~rupture.ports.forecast_model.ForecastModel`.

Features, documented, no target leakage:

* ``x = log10(distance_km)`` to the nearest training event with ``mw >= m_main``, clipped to
  ``distance_floor_km`` (default 0.1 km). That is the two-parameter Mignan & Broccardo shape.
* Optional ``z = log10(mean slip proxy)`` only when a finite-fault / :class:`SlipField` is
  supplied. Without it the model is the single-feature distance logistic and says so in notes.

``P = 1 / (1 + exp(-(a + b x [+ c z])))``. ``fit`` estimates coefficients by Bernoulli maximum
likelihood on the region's lattice: positives are cells that hosted an event with
``origin_time < cutoff`` and ``mw >=`` the target threshold; negatives are the rest. Only events
with ``origin_time < cutoff`` enter, asserted by
:func:`rupture.adapters.forecasting.leakage.assert_all_before`.

A :class:`~rupture.domain.forecast.ForecastGrid` holds expected COUNTS, not probabilities.
Conversion, training window only:

    expected_count_i = P_i * (n_events / n_positive_cells) * (horizon_days / training_days)

There is no ``auc`` method. Area skill / Molchan on an :class:`~rupture.domain.alarm.AlarmSet`
is the scoring path this repository allows; see :mod:`rupture.scoring.refusals`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import numpy.typing as npt

from rupture.adapters.forecasting.grid import Lattice, build_lattice
from rupture.adapters.forecasting.leakage import assert_all_before, assert_issue_after_fit
from rupture.domain import Catalog, Event, FitResult, ForecastGrid, Region, snapshot_hash, utc_now
from rupture.models.comparators import _fit as lf
from rupture.models.comparators.citations import (
    COUNT_CONVERSION_NOTE,
    DOI_DEVRIES_2018,
    DOI_MEADE_REPLY_2019,
    DOI_MIGNAN_BROCCARDO_2019,
    EVIDENCE_SENTENCE,
    EVIDENCE_STATUS_DEVRIES,
    EVIDENCE_STATUS_MIGNAN,
)
from rupture.models.comparators.errors import MissingSlipFieldError
from rupture.models.comparators.slip import SlipField
from rupture.models.data.geo import Projection

# No `auc` method on this class. AUC on grid cells is refused; score AlarmSet + area skill /
# Molchan (see rupture.scoring.refusals). Accuracy is refused on the same grounds.

MODEL_ID = "one-neuron-logistic"
MODEL_VERSION = "0.1.0"
_F8 = npt.NDArray[np.float64]


class OneNeuronAftershockModel:
    """Two-parameter (optionally three-parameter) logistic occupancy, issued as expected counts."""

    model_id: str = MODEL_ID
    model_version: str = MODEL_VERSION

    def __init__(
        self,
        *,
        m_main: float = 6.0,
        distance_floor_km: float = lf.DISTANCE_FLOOR_KM,
        slip_field: SlipField | None = None,
        mc: float | None = None,
        require_slip: bool = False,
    ) -> None:
        if m_main <= 0.0:
            msg = "m_main must be positive"
            raise ValueError(msg)
        if distance_floor_km <= 0.0:
            msg = "distance_floor_km must be positive"
            raise ValueError(msg)
        self.m_main = m_main
        self.distance_floor_km = distance_floor_km
        self.slip_field = slip_field
        self._mc_override = mc
        self.require_slip = require_slip
        self._fit: FitResult | None = None
        self._logistic: lf.LogisticFit | None = None
        self._region: Region | None = None
        self._lattice: Lattice | None = None
        self._projection: Projection | None = None
        self._anchors: tuple[Event, ...] = ()
        self._log_slip: _F8 | None = None
        self._mc: float | None = None

    @property
    def fit_result(self) -> FitResult | None:
        return self._fit

    @property
    def cell_origins(self) -> tuple[tuple[float, float], ...]:
        """Lattice origins the next ``forecast`` / alarm will be issued on."""
        _fit, _region, lattice, _projection = self._require_state()
        return lattice.origins

    def parameter_snapshot(self) -> dict[str, Any]:
        """Numeric coefficients plus the citation DOIs the next ``forecast`` is issued under."""
        logistic = self._logistic
        if logistic is None:
            return {}
        snapshot: dict[str, Any] = {
            "a": logistic.a,
            "b": logistic.b,
            "distance_floor_km": self.distance_floor_km,
            "m_main": self.m_main,
            "mean_events_per_positive_cell": logistic.mean_events_per_positive_cell,
            "training_days": logistic.training_days,
            "n_positive_cells": float(logistic.n_positive_cells),
            "n_training_events": float(logistic.n_training_events),
            "used_slip": 1.0 if logistic.used_slip else 0.0,
            "citation_devries_doi": DOI_DEVRIES_2018,
            "citation_mignan_doi": DOI_MIGNAN_BROCCARDO_2019,
            "citation_meade_reply_doi": DOI_MEADE_REPLY_2019,
            "evidence_status_devries": EVIDENCE_STATUS_DEVRIES,
            "evidence_status_mignan": EVIDENCE_STATUS_MIGNAN,
        }
        if logistic.c is not None:
            snapshot["c"] = logistic.c
        return snapshot

    def _numeric_parameters(self) -> dict[str, float]:
        logistic = self._require_logistic()
        parameters: dict[str, float] = {
            "a": logistic.a,
            "b": logistic.b,
            "distance_floor_km": self.distance_floor_km,
            "m_main": self.m_main,
            "mean_events_per_positive_cell": logistic.mean_events_per_positive_cell,
            "training_days": logistic.training_days,
            "n_positive_cells": float(logistic.n_positive_cells),
            "n_training_events": float(logistic.n_training_events),
            "used_slip": 1.0 if logistic.used_slip else 0.0,
        }
        if logistic.c is not None:
            parameters["c"] = logistic.c
        return parameters

    def fit(self, catalog: Catalog, region: Region, cutoff: datetime) -> FitResult:
        """Estimate ``a``, ``b`` (and ``c`` if slip is present) on ``origin_time < cutoff``."""
        training = catalog.earthquakes().before(cutoff)
        assert_all_before(training, cutoff, what="one-neuron fit training catalogue")
        mc_value = lf.resolve_mc(region, training, self._mc_override)
        lattice = build_lattice(region)
        projection = Projection.for_region(region)
        anchors = lf.mainshock_anchors(training, m_main=self.m_main)
        if not anchors:
            msg = (
                f"no training earthquakes with mw >= m_main={self.m_main} and origin_time < "
                f"{cutoff.isoformat()}; distance-to-mainshock is undefined"
            )
            raise ValueError(msg)
        targets = lf.target_events(training, min_mw=mc_value)
        in_grid = lf.events_on_lattice(lattice, targets)
        if not in_grid:
            msg = (
                f"no training earthquakes with mw >= {mc_value} and origin_time < "
                f"{cutoff.isoformat()} landed in region {region.id!r}; refusing to fit"
            )
            raise ValueError(msg)
        log_distance = lf.log10_distance_to_anchors(
            lattice, projection, anchors, distance_floor_km=self.distance_floor_km
        )
        used_slip = self.slip_field is not None
        if self.require_slip and self.slip_field is None:
            msg = (
                f"{self.model_id} requires a finite-fault / slip field (SlipField with "
                "mean_slip_m per lattice cell); none was supplied"
            )
            raise MissingSlipFieldError(msg)
        log_slip = lf.log10_slip(self.slip_field, lattice) if self.slip_field is not None else None
        y, event_counts = lf.occupancy_labels(lattice, in_grid)
        design = lf.design_matrix(log_distance, log_slip)
        theta, loglik = lf.fit_logistic_mle(design, y)
        span = lf.training_span_days(
            training, cutoff, start=min(event.origin_time for event in in_grid)
        )
        magnitudes = np.asarray([e.mw for e in in_grid if e.mw is not None], dtype=np.float64)
        edges = region.magnitude_bin_edges()
        logistic = lf.assemble_fit(
            theta=theta,
            log_likelihood=loglik,
            y=y,
            event_counts=event_counts,
            training_days=span,
            used_slip=used_slip,
            magnitudes=magnitudes,
            mc=mc_value,
            edges=edges,
            width=region.magnitude_bin_width,
        )
        self._logistic = logistic
        self._region = region
        self._lattice = lattice
        self._projection = projection
        self._anchors = anchors
        self._log_slip = log_slip
        self._mc = mc_value
        start = min(event.origin_time for event in in_grid)
        parameters = self._numeric_parameters()
        shape = (
            "three-parameter logistic on log-distance and log mean slip"
            if used_slip
            else (
                "single-feature distance logistic; no finite-fault / slip field was supplied, "
                "so log mean slip was not used"
            )
        )
        notes = (
            f"{shape}. {COUNT_CONVERSION_NOTE} {EVIDENCE_SENTENCE} "
            f"n_positive_cells={logistic.n_positive_cells}, "
            f"n_training_events={logistic.n_training_events}, "
            f"mean_events_per_positive_cell="
            f"{logistic.mean_events_per_positive_cell:.6g}."
        )
        result = FitResult(
            model_id=self.model_id,
            model_version=self.model_version,
            region_id=region.id,
            fit_cutoff=cutoff,
            training_start=start,
            training_catalog_hash=training.event_hash(),
            n_events=len(in_grid),
            mc=mc_value,
            parameters=parameters,
            parameter_snapshot_hash=snapshot_hash(parameters),
            log_likelihood=logistic.log_likelihood,
            diagnostics={
                "n_cells": lattice.n_cells,
                "n_positive_cells": logistic.n_positive_cells,
                "n_training_events": logistic.n_training_events,
                "n_mainshock_anchors": len(anchors),
                "mean_events_per_positive_cell": logistic.mean_events_per_positive_cell,
                "training_days": logistic.training_days,
                "used_slip": used_slip,
                "distance_floor_km": self.distance_floor_km,
                "m_main": self.m_main,
                "b_value": logistic.b_value,
                "mag_pmf": list(logistic.mag_pmf),
                "count_conversion": COUNT_CONVERSION_NOTE,
                "citation_devries_doi": DOI_DEVRIES_2018,
                "citation_mignan_doi": DOI_MIGNAN_BROCCARDO_2019,
                "citation_meade_reply_doi": DOI_MEADE_REPLY_2019,
                "evidence_status_devries": EVIDENCE_STATUS_DEVRIES,
                "evidence_status_mignan": EVIDENCE_STATUS_MIGNAN,
                "evidence_sentence": EVIDENCE_SENTENCE,
                "training_max_origin_time": (
                    latest.isoformat() if (latest := training.max_origin_time()) else None
                ),
            },
            converged=True,
            fitted_at=utc_now(),
            notes=notes,
        )
        self._fit = result
        return result

    def occupancy_map(self, history: Catalog, issue_time: datetime) -> _F8:
        """Occupancy P per lattice cell from history strictly before ``issue_time``."""
        _fit, _region, lattice, projection = self._require_state()
        logistic = self._require_logistic()
        assert_all_before(history, issue_time, what="one-neuron occupancy history")
        anchors = lf.mainshock_anchors(history, m_main=self.m_main) or self._anchors
        log_distance = lf.log10_distance_to_anchors(
            lattice, projection, anchors, distance_floor_km=self.distance_floor_km
        )
        return lf.occupancy_probability(
            logistic.a, logistic.b, log_distance, logistic.c, self._log_slip
        )

    def forecast(
        self,
        history: Catalog,
        issue_time: datetime,
        horizon: timedelta,
        *,
        rate_scale: float | None = None,
    ) -> ForecastGrid:
        """Issue expected counts for ``[issue_time, issue_time + horizon)``.

        ``history`` must contain only events with ``origin_time < issue_time``. Distances are
        recomputed from that history's ``mw >= m_main`` events (falling back to the training
        anchors if the history has none). Productivity is never refit from the issue window.
        """
        fit, region, lattice, _projection = self._require_state()
        logistic = self._require_logistic()
        if horizon <= timedelta(0):
            msg = "horizon must be positive"
            raise ValueError(msg)
        assert_issue_after_fit(issue_time, fit.fit_cutoff)
        assert_all_before(history, issue_time, what="one-neuron forecast history")
        probability = self.occupancy_map(history, issue_time)
        horizon_days = horizon.total_seconds() / 86400.0
        spatial = lf.expected_counts_from_occupancy(
            probability, logistic, horizon_days, rate_scale=rate_scale
        )
        expected = lf.split_across_magnitude_bins(spatial, logistic.mag_pmf)
        scale_note = (
            f"rate_scale={rate_scale}"
            if rate_scale is not None
            else (
                "rate_scale = mean_events_per_positive_cell * "
                f"(horizon_days / training_days) = "
                f"{logistic.mean_events_per_positive_cell:.6g} * "
                f"({horizon_days:.6g} / {logistic.training_days:.6g})"
            )
        )
        shape = (
            "three-parameter logistic (log-distance and log mean slip)"
            if logistic.used_slip
            else "single-feature distance logistic (no slip field)"
        )
        notes = (
            f"{shape}. {COUNT_CONVERSION_NOTE} {scale_note}. {EVIDENCE_SENTENCE} "
            f"history anchors: mw >= {self.m_main}."
        )
        return ForecastGrid(
            id=ForecastGrid.make_id(self.model_id, region.id, issue_time, horizon),
            region_id=region.id,
            model_id=self.model_id,
            model_version=self.model_version,
            parameter_snapshot_hash=fit.parameter_snapshot_hash,
            fit_cutoff=fit.fit_cutoff,
            training_catalog_hash=fit.training_catalog_hash,
            issue_time=issue_time,
            horizon=horizon,
            cell_size_deg=region.cell_size_deg,
            cell_origins=lattice.origins,
            magnitude_bin_edges=region.magnitude_bin_edges(),
            magnitude_bin_width=region.magnitude_bin_width,
            expected_counts=expected,
            n_simulations=None,
            created_at=utc_now(),
            notes=notes,
        )

    def load_fit(
        self,
        fit: FitResult,
        region: Region,
        *,
        anchors: tuple[Event, ...] = (),
        slip_field: SlipField | None = None,
    ) -> None:
        """Restore a persisted fit so the next ``forecast`` can run without refitting."""
        if fit.model_id != self.model_id:
            msg = f"fit belongs to model {fit.model_id!r}, not {self.model_id!r}"
            raise ValueError(msg)
        if fit.region_id != region.id:
            msg = f"fit is for region {fit.region_id!r}, not {region.id!r}"
            raise ValueError(msg)
        used_slip = bool(fit.parameters.get("used_slip", 0.0))
        field = slip_field if slip_field is not None else self.slip_field
        lattice = build_lattice(region)
        log_slip = lf.log10_slip(field, lattice) if used_slip and field is not None else None
        if used_slip and log_slip is None:
            msg = f"{self.model_id} fit used a slip field and load_fit was not given one"
            raise MissingSlipFieldError(msg)
        mag_pmf = tuple(float(v) for v in fit.diagnostics["mag_pmf"])
        self._logistic = lf.LogisticFit(
            a=float(fit.parameters["a"]),
            b=float(fit.parameters["b"]),
            c=float(fit.parameters["c"]) if "c" in fit.parameters else None,
            log_likelihood=float(fit.log_likelihood or 0.0),
            n_positive_cells=int(fit.parameters["n_positive_cells"]),
            n_training_events=int(fit.parameters["n_training_events"]),
            mean_events_per_positive_cell=float(fit.parameters["mean_events_per_positive_cell"]),
            training_days=float(fit.parameters["training_days"]),
            n_cells=int(fit.diagnostics.get("n_cells", len(lattice.origins))),
            used_slip=used_slip,
            b_value=(
                float(fit.diagnostics["b_value"])
                if fit.diagnostics.get("b_value") is not None
                else None
            ),
            mag_pmf=mag_pmf,
        )
        self._fit = fit
        self._region = region
        self._lattice = lattice
        self._projection = Projection.for_region(region)
        self._anchors = anchors
        self._log_slip = log_slip
        self._mc = fit.mc
        self.m_main = float(fit.parameters["m_main"])
        self.distance_floor_km = float(fit.parameters["distance_floor_km"])
        if field is not None:
            self.slip_field = field

    def _require_logistic(self) -> lf.LogisticFit:
        if self._logistic is None:
            msg = f"{self.model_id} has not been fitted"
            raise ValueError(msg)
        return self._logistic

    def _require_state(self) -> tuple[FitResult, Region, Lattice, Projection]:
        if (
            self._fit is None
            or self._region is None
            or self._lattice is None
            or self._projection is None
        ):
            msg = f"{self.model_id} has not been fitted"
            raise ValueError(msg)
        return self._fit, self._region, self._lattice, self._projection
