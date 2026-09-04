"""HTTP surface for the aftershock forecast service (FastAPI).

Three routes:

``GET /healthz``
    Liveness plus what the process is holding: the model id, the sequences whose catalogues are
    loaded, the fits on disk for each, where issued grids are kept, and whether an API key is
    configured. No authentication.

``POST /aftershock/forecast``
    Body names a mainshock -- either ``mainshock_id`` (a ComCat id present in the catalogue) or
    an explicit ``mainshock`` object (time, latitude, longitude, magnitude, optional depth) --
    an ``issue_time`` and a ``horizon``. Returns an
    :class:`~rupture.domain.AftershockForecast`. Requires the API key.

``GET /aftershock/grid/{grid_id}``
    The :class:`~rupture.domain.ForecastGrid` behind a forecast, by the ``forecast_grid_id`` the
    forecast reported. The ladder in the forecast is zone-wide -- a circle 218 km across for an
    M7.8 -- so anything that depends on *where* the rate is concentrated reads the grid. Requires
    the API key. See :mod:`rupture.services.aftershock.grids` for how long a grid is kept.

This module builds a router (:func:`build_router`) and a standalone application around it
(:func:`create_app`). The combined service in :mod:`rupture.services.app` includes the same
router next to the avoided-loss one, so the two surfaces are one process, one OpenAPI document
and one API-key scheme (ADR-0036).

Authentication is an API key in the ``X-API-Key`` header and nothing else, by design: this
service is meant to sit behind whatever the deployment already has. Keys come from
``RUPTURE_AFTERSHOCK_API_KEY`` / ``RUPTURE_AFTERSHOCK_API_KEYS`` or the service-wide
``RUPTURE_API_KEYS``, and are compared in constant time
(:mod:`rupture.services.auth`). With no key configured the authenticated routes answer ``503``
rather than serving open.

rupture does not predict earthquakes. A response is a rate and a probability for a sequence.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from pydantic import BaseModel, Field, model_validator

from rupture.domain import AftershockForecast, Catalog, ForecastGrid, Region, parse_horizon
from rupture.pipelines.io import load_catalog, load_region
from rupture.services.aftershock.forecaster import (
    POISSON_NOTE,
    AftershockForecaster,
    scheduled_fit_cutoff,
)
from rupture.services.aftershock.grids import GridStore, grid_store_from_env
from rupture.services.aftershock.refit import FitsStore
from rupture.services.aftershock.sequences import (
    SEQUENCES,
    Mainshock,
    fits_dir,
    load_parent_region,
    load_sequence_catalog,
    mainshock_from_catalog,
)
from rupture.services.auth import API_KEY_HEADER, SHARED_KEYS_ENV, ApiKeyGuard

API_KEY_ENV = "RUPTURE_AFTERSHOCK_API_KEY"
API_KEYS_ENV = "RUPTURE_AFTERSHOCK_API_KEYS"
API_KEY_ENV_VARS: tuple[str, ...] = (SHARED_KEYS_ENV, API_KEYS_ENV, API_KEY_ENV)
CATALOGS_ENV = "RUPTURE_AFTERSHOCK_CATALOGS"
ALLOW_REFIT_ENV = "RUPTURE_AFTERSHOCK_ALLOW_REFIT"
SURFACE = "aftershock"

__all__ = [
    "ALLOW_REFIT_ENV",
    "API_KEYS_ENV",
    "API_KEY_ENV",
    "API_KEY_HEADER",
    "CATALOGS_ENV",
    "AftershockState",
    "ForecastRequest",
    "LoadedSequence",
    "MainshockParameters",
    "SequenceSource",
    "build_router",
    "build_state",
    "create_app",
    "load_default_sequences",
    "load_sequences",
    "parse_catalog_specs",
]


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
    """A catalogue and its parent region, with the persisted fits for the sequence.

    ``fits`` is a snapshot passed in by a caller (a test, mostly). ``fits_store`` is a directory
    the service re-reads, so a fit written by ``rupture aftershock refit`` while the service is up
    becomes servable on the next request instead of after a restart. Where both have a cutoff the
    directory wins: it is the live one.
    """

    id: str
    catalog: Catalog
    parent_region: Region
    fits: Mapping[str, Any] = field(default_factory=dict)
    fits_store: FitsStore | None = None

    def current_fits(self) -> Mapping[str, Any]:
        if self.fits_store is None:
            return self.fits
        return {**self.fits, **self.fits_store.fits()}


@dataclass(frozen=True, slots=True)
class SequenceSource:
    """A catalogue directory and parent region file to serve, named on the command line or env."""

    id: str
    catalog_dir: Path
    region_path: Path
    fits_dir: Path | None = None

    def load(self) -> LoadedSequence:
        return LoadedSequence(
            id=self.id,
            catalog=load_catalog(self.catalog_dir),
            parent_region=load_region(self.region_path),
            fits_store=FitsStore(self.fits_dir) if self.fits_dir is not None else None,
        )


def parse_catalog_specs(text: str | None) -> tuple[SequenceSource, ...]:
    """Parse ``RUPTURE_AFTERSHOCK_CATALOGS``.

    Grammar, one entry per sequence, entries separated by ``;``::

        <name>=<catalog_dir>,<region_file>[,<fits_dir>]

    So a deployment serves its own built catalogues without editing code::

        RUPTURE_AFTERSHOCK_CATALOGS="ridgecrest=/data/catalogs/socal,/data/regions/socal,/fits/rc"

    A malformed entry raises ``ValueError`` at start-up rather than being skipped: a service that
    silently serves fewer sequences than it was configured with is worse than one that refuses to
    start.
    """
    if not text or not text.strip():
        return ()
    out: list[SequenceSource] = []
    for raw in text.split(";"):
        entry = raw.strip()
        if not entry:
            continue
        name, sep, rest = entry.partition("=")
        if not sep or not name.strip():
            msg = f"{CATALOGS_ENV} entry {entry!r} is not '<name>=<catalog_dir>,<region_file>'"
            raise ValueError(msg)
        parts = [p.strip() for p in rest.split(",") if p.strip()]
        if len(parts) not in (2, 3):
            msg = (
                f"{CATALOGS_ENV} entry {entry!r} needs a catalogue directory and a region file "
                "(and optionally a fits directory)"
            )
            raise ValueError(msg)
        out.append(
            SequenceSource(
                id=name.strip(),
                catalog_dir=Path(parts[0]).expanduser(),
                region_path=Path(parts[1]).expanduser(),
                fits_dir=Path(parts[2]).expanduser() if len(parts) == 3 else None,
            )
        )
    return tuple(out)


def load_default_sequences(repo_root: Path) -> dict[str, LoadedSequence]:
    """The two committed validation sequences, catalogues and fits, read once at start-up."""
    out: dict[str, LoadedSequence] = {}
    for name, spec in SEQUENCES.items():
        out[name] = LoadedSequence(
            id=name,
            catalog=load_sequence_catalog(spec, repo_root),
            parent_region=load_parent_region(spec, repo_root),
            fits_store=FitsStore(fits_dir(spec, repo_root)),
        )
    return out


def load_sequences(
    repo_root: Path,
    *,
    defaults: bool = True,
    sources: tuple[SequenceSource, ...] = (),
    env: Mapping[str, str] | None = None,
) -> dict[str, LoadedSequence]:
    """Committed sequences (unless ``defaults`` is off) plus anything configured.

    Configured sources come from ``sources`` and from ``RUPTURE_AFTERSHOCK_CATALOGS``; a
    configured source with the same name as a committed one replaces it.
    """
    environ = os.environ if env is None else env
    out: dict[str, LoadedSequence] = load_default_sequences(repo_root) if defaults else {}
    for source in (*parse_catalog_specs(environ.get(CATALOGS_ENV)), *sources):
        out[source.id] = source.load()
    return out


def _env_flag(env: Mapping[str, str], name: str, *, default: bool = False) -> bool:
    raw = env.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AftershockState:
    """Everything the aftershock routes need: catalogues, the engine, keys and the grid store."""

    sequences: dict[str, LoadedSequence]
    engine: AftershockForecaster
    guard: ApiKeyGuard
    grids: GridStore
    allow_refit: bool = False

    def health(self) -> dict[str, object]:
        return {
            "status": "ok",
            "service": SURFACE,
            "model_id": "etas-mizrahi",
            "sequences": sorted(self.sequences),
            "fits_loaded": {
                name: sorted(entry.current_fits()) for name, entry in sorted(self.sequences.items())
            },
            "allow_refit": self.allow_refit,
            "api_key_configured": self.guard.is_configured(),
            "grid_store": self.grids.describe(),
            "poisson_assumption": POISSON_NOTE,
        }


def build_state(
    *,
    repo_root: Path | None = None,
    api_key: str | None = None,
    forecaster: AftershockForecaster | None = None,
    sequences: dict[str, LoadedSequence] | None = None,
    loader: Callable[[Path], dict[str, LoadedSequence]] | None = None,
    sources: tuple[SequenceSource, ...] = (),
    defaults: bool = True,
    allow_refit: bool | None = None,
    grids: GridStore | None = None,
    env: Mapping[str, str] | None = None,
) -> AftershockState:
    """Load the catalogues and assemble the state the router closes over."""
    environ = os.environ if env is None else env
    root = Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[4]
    if sequences is not None:
        loaded = sequences
    elif loader is not None:
        loaded = loader(root)
    else:
        loaded = load_sequences(root, defaults=defaults, sources=sources, env=environ)
    return AftershockState(
        sequences=loaded,
        engine=forecaster or AftershockForecaster(),
        guard=ApiKeyGuard(
            surface=SURFACE,
            env_vars=API_KEY_ENV_VARS,
            static_keys=frozenset({api_key}) if api_key is not None else frozenset(),
        ),
        grids=grids if grids is not None else grid_store_from_env(dict(environ)),
        allow_refit=(
            _env_flag(environ, ALLOW_REFIT_ENV) if allow_refit is None else bool(allow_refit)
        ),
    )


def build_router(state: AftershockState) -> APIRouter:
    """The aftershock routes, for a standalone app or for the combined service."""
    router = APIRouter(tags=["aftershock"])

    @router.post(
        "/aftershock/forecast",
        response_model=AftershockForecast,
        summary="Issue an aftershock forecast for a mainshock sequence",
        dependencies=[Depends(state.guard)],
    )
    def forecast(request: ForecastRequest) -> AftershockForecast:
        entry = _resolve_sequence(state.sequences, request)
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
        region = state.engine.zone(mainshock, entry.parent_region)
        cutoff = scheduled_fit_cutoff(mainshock.origin_time, request.issue_time)
        fit = entry.current_fits().get(cutoff.isoformat())
        if fit is None and not state.allow_refit:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    f"no persisted fit for region {region.id} at cutoff {cutoff.isoformat()}; "
                    "fitting takes minutes and is not done inside a request. Run "
                    f"`rupture aftershock refit --sequence {entry.id}` (it writes the fits this "
                    "service re-reads), or start the service with allow_refit=True."
                ),
            )
        try:
            issuance = state.engine.forecast(
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
        state.grids.put(issuance.grid)
        return issuance.forecast

    @router.get(
        "/aftershock/grid/{grid_id}",
        response_model=ForecastGrid,
        summary="The gridded rate forecast behind an issued forecast",
        dependencies=[Depends(state.guard)],
    )
    def grid(grid_id: str) -> ForecastGrid:
        found = state.grids.get(grid_id)
        if found is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=(
                    f"no grid {grid_id!r} is held; grids are kept as they are issued "
                    f"({state.grids.describe()}). POST /aftershock/forecast first and read "
                    "forecast_grid_id from the response."
                ),
            )
        return found

    return router


def create_app(
    *,
    repo_root: Path | None = None,
    api_key: str | None = None,
    forecaster: AftershockForecaster | None = None,
    sequences: dict[str, LoadedSequence] | None = None,
    loader: Callable[[Path], dict[str, LoadedSequence]] | None = None,
    sources: tuple[SequenceSource, ...] = (),
    defaults: bool = True,
    allow_refit: bool | None = None,
    grids: GridStore | None = None,
) -> FastAPI:
    """Build the standalone aftershock application.

    ``sequences`` (or ``loader``, or ``sources`` / ``RUPTURE_AFTERSHOCK_CATALOGS``) decides which
    catalogues it serves. ``allow_refit`` is off by default: an EM fit takes minutes, which is not
    something to do inside an HTTP request, so a request whose scheduled fit cutoff has no
    persisted fit is refused with 503 naming the cutoff and the command that produces it.

    The combined service (``rupture.services.app``) is the deployment target; this one exists for
    a deployment that wants the aftershock surface alone.
    """
    state = build_state(
        repo_root=repo_root,
        api_key=api_key,
        forecaster=forecaster,
        sequences=sequences,
        loader=loader,
        sources=sources,
        defaults=defaults,
        allow_refit=allow_refit,
        grids=grids,
    )
    app = FastAPI(
        title="rupture aftershock forecast",
        version="0",
        description=(
            "Operational aftershock forecasts: the probability of at least one further event of "
            "magnitude at least m within a horizon, and the gridded rate forecast behind it. "
            "rupture does not predict earthquakes. " + POISSON_NOTE
        ),
    )

    @app.get("/healthz", summary="Liveness and what this process is holding")
    def healthz() -> dict[str, object]:
        return state.health()

    app.include_router(build_router(state))
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


# There is no module-level ``app``: the application is built by :func:`create_app`, so serving the
# aftershock surface alone is
# ``uvicorn rupture.services.aftershock.service:create_app --factory``. The deployment target is
# the combined service, ``uvicorn rupture.services.app:create_app --factory``.
