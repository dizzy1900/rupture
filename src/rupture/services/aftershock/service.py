"""HTTP surface for the aftershock forecast service (FastAPI).

Two routes:

``GET /healthz``
    Liveness plus what the process is holding: the model id and version, the sequences whose
    catalogues are loaded, and whether an API key is configured. No authentication.

``POST /aftershock/forecast``
    Body names a mainshock -- either ``mainshock_id`` (a ComCat id present in the catalogue) or
    an explicit ``mainshock`` object (time, latitude, longitude, magnitude, optional depth) --
    an ``issue_time`` and a ``horizon``. Returns an
    :class:`~rupture.domain.AftershockForecast`. Requires the API key.

Authentication is an API key in the ``X-API-Key`` header and nothing else, by design: this
service is meant to sit behind whatever the deployment already has. The key comes from
``RUPTURE_AFTERSHOCK_API_KEY`` (or is passed to :func:`create_app`). With no key configured the
service answers ``503`` on the forecast route rather than serving it open.

This module is self-contained: it defines its own ``FastAPI`` application and mounts nothing.
Another component's app (for example the avoided-loss service) can be mounted alongside it by
whoever assembles the deployment.

rupture does not predict earthquakes. A response is a rate and a probability for a sequence.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from rupture.domain import AftershockForecast, Catalog, Region, parse_horizon
from rupture.services.aftershock.forecaster import (
    POISSON_NOTE,
    AftershockForecaster,
    scheduled_fit_cutoff,
)
from rupture.services.aftershock.sequences import (
    SEQUENCES,
    Mainshock,
    load_committed_fits,
    load_parent_region,
    load_sequence_catalog,
    mainshock_from_catalog,
)

API_KEY_ENV = "RUPTURE_AFTERSHOCK_API_KEY"
API_KEY_HEADER = "X-API-Key"


class MainshockParameters(BaseModel):
    """An explicitly supplied mainshock, for an event that is not in the catalogue by id."""

    event_id: str = Field(default="explicit", min_length=1)
    origin_time: datetime
    latitude: float = Field(ge=-90.0, le=90.0)
    longitude: float = Field(ge=-180.0, le=180.0)
    magnitude: float = Field(ge=0.0, le=10.0)
    depth_km: float | None = None

    def to_mainshock(self) -> Mainshock:
        return Mainshock(
            event_id=self.event_id,
            origin_time=self.origin_time,
            latitude=self.latitude,
            longitude=self.longitude,
            magnitude=self.magnitude,
            depth_km=self.depth_km,
        )


class ForecastRequest(BaseModel):
    """One forecast request. Exactly one of ``mainshock_id`` / ``mainshock``."""

    mainshock_id: str | None = None
    mainshock: MainshockParameters | None = None
    sequence: str | None = Field(
        default=None,
        description=(
            "Which loaded sequence catalogue to condition on. Optional when mainshock_id "
            "identifies one of them."
        ),
    )
    issue_time: datetime
    horizon: str = Field(default="7d", description="One of <n>[h|d|w|y], e.g. '1d', '7d', '30d'.")
    n_simulations: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def _one_mainshock(self) -> ForecastRequest:
        if (self.mainshock_id is None) == (self.mainshock is None):
            msg = "give exactly one of mainshock_id or mainshock"
            raise ValueError(msg)
        if self.issue_time.tzinfo is None:
            msg = "issue_time must be timezone-aware (UTC)"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class LoadedSequence:
    """A catalogue and its parent region, with any persisted fits for the sequence."""

    id: str
    catalog: Catalog
    parent_region: Region
    fits: dict[str, Any]


def load_default_sequences(repo_root: Path) -> dict[str, LoadedSequence]:
    """The two committed validation sequences, catalogues and fits, read once at start-up."""
    out: dict[str, LoadedSequence] = {}
    for name, spec in SEQUENCES.items():
        out[name] = LoadedSequence(
            id=name,
            catalog=load_sequence_catalog(spec, repo_root),
            parent_region=load_parent_region(spec, repo_root),
            fits=dict(load_committed_fits(spec, repo_root)),
        )
    return out


def create_app(
    *,
    repo_root: Path | None = None,
    api_key: str | None = None,
    forecaster: AftershockForecaster | None = None,
    sequences: dict[str, LoadedSequence] | None = None,
    loader: Callable[[Path], dict[str, LoadedSequence]] = load_default_sequences,
) -> FastAPI:
    """Build the application. ``sequences`` (or ``loader``) decides which catalogues it serves."""
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[4]
    key = api_key if api_key is not None else os.environ.get(API_KEY_ENV)
    loaded = sequences if sequences is not None else loader(root)
    engine = forecaster or AftershockForecaster()

    app = FastAPI(
        title="rupture aftershock forecast",
        version="0",
        description=(
            "Operational aftershock forecasts: the probability of at least one further event of "
            "magnitude at least m within a horizon, and the gridded rate forecast behind it. "
            "rupture does not predict earthquakes. " + POISSON_NOTE
        ),
    )

    def require_key(
        x_api_key: Annotated[str | None, Header(alias=API_KEY_HEADER)] = None,
    ) -> None:
        if key is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"no API key configured; set {API_KEY_ENV}",
            )
        if x_api_key != key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"missing or wrong {API_KEY_HEADER}",
            )

    @app.get("/healthz")
    def healthz() -> dict[str, object]:
        return {
            "status": "ok",
            "service": "aftershock",
            "model_id": "etas-mizrahi",
            "sequences": sorted(loaded),
            "api_key_configured": key is not None,
            "poisson_assumption": POISSON_NOTE,
        }

    @app.post(
        "/aftershock/forecast",
        response_model=AftershockForecast,
        dependencies=[Depends(require_key)],
    )
    def forecast(request: ForecastRequest) -> AftershockForecast:
        entry = _resolve_sequence(loaded, request)
        mainshock = _resolve_mainshock(entry, request)
        try:
            horizon = parse_horizon(request.horizon)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc
        if request.issue_time < mainshock.origin_time:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="issue_time cannot precede the mainshock",
            )
        region = engine.zone(mainshock, entry.parent_region)
        cutoff = scheduled_fit_cutoff(mainshock.origin_time, request.issue_time)
        fit = entry.fits.get(cutoff.isoformat())
        try:
            issuance = engine.forecast(
                catalog=entry.catalog,
                parent_region=entry.parent_region,
                mainshock=mainshock,
                issue_time=request.issue_time,
                horizon=horizon,
                fit=fit,
                n_simulations=request.n_simulations,
            )
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"cannot issue for region {region.id}: {exc}",
            ) from exc
        return issuance.forecast

    return app


def _resolve_sequence(
    loaded: dict[str, LoadedSequence], request: ForecastRequest
) -> LoadedSequence:
    if request.sequence is not None:
        entry = loaded.get(request.sequence)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"unknown sequence {request.sequence!r}; loaded: {sorted(loaded)}",
            )
        return entry
    if request.mainshock_id is not None:
        for name, spec in SEQUENCES.items():
            if spec.mainshock.event_id == request.mainshock_id and name in loaded:
                return loaded[name]
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=(f"give 'sequence' naming the catalogue to condition on; loaded: {sorted(loaded)}"),
    )


def _resolve_mainshock(entry: LoadedSequence, request: ForecastRequest) -> Mainshock:
    if request.mainshock is not None:
        return request.mainshock.to_mainshock()
    if request.mainshock_id is None:  # pragma: no cover - the request validator forbids it
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="give exactly one of mainshock_id or mainshock",
        )
    try:
        return mainshock_from_catalog(entry.catalog, request.mainshock_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"mainshock {request.mainshock_id!r}: {exc}",
        ) from exc


# There is no module-level ``app``: the application is built by :func:`create_app`, so serving it
# is ``uvicorn rupture.services.aftershock.service:create_app --factory``.
