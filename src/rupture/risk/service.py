"""A small HTTP surface for the avoided-loss contract.

One endpoint that matters: ``POST /v1/avoided-loss`` takes an ``AvoidedLossRequestV1`` (serac's
field names included, per ADR-0021) and returns an ``AvoidedLossResponseV1``. The service does no
modelling of its own; it is a thin shell over :func:`rupture.risk.avoided_loss.respond`, so an
answer over HTTP and an answer from the CLI are the same answer.

**Authentication is an API key header and nothing else.** ``X-API-Key`` must match one of the keys
in ``RUPTURE_RISK_API_KEYS`` (comma-separated) or in the service-wide ``RUPTURE_API_KEYS``,
compared in constant time (:mod:`rupture.services.auth`). With no keys configured the service
refuses every request rather than running open: an unauthenticated loss service is not a default
anyone should get by forgetting to set a variable. There is no user model, no session, no rate
limiting and no audit log; ``docs/RISK.md`` says so under Deployment, and this is not a
public-internet service.

The routes live on a router (:func:`build_router`) so the combined service in
:mod:`rupture.services.app` can serve them alongside the aftershock forecast in one process, one
OpenAPI document and one key scheme (ADR-0036). ``create_app()`` and the module-level ``app``
remain for a deployment that wants the risk surface alone.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status

from rupture import __version__
from rupture.domain.avoided_loss_v1 import (
    CONTRACT_VERSION,
    AvoidedLossRequestV1,
    AvoidedLossResponseV1,
    ResponseStatus,
)
from rupture.risk import avoided_loss, scenarios
from rupture.services.auth import API_KEY_HEADER, SHARED_KEYS_ENV, ApiKeyGuard

API_KEY_ENV = "RUPTURE_RISK_API_KEYS"
API_KEY_ENV_VARS: tuple[str, ...] = (SHARED_KEYS_ENV, API_KEY_ENV)
REPO_ROOT_ENV = "RUPTURE_REPO_ROOT"
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
SURFACE = "risk"
MAX_REALISATIONS = 5000
"""A request cannot ask for an unbounded calculation; the cap is refused, not silently reduced."""

GUARD = ApiKeyGuard(surface=SURFACE, env_vars=API_KEY_ENV_VARS)
"""The shared guard for this surface. Keys are read from the environment on every request."""

__all__ = [
    "API_KEY_ENV",
    "API_KEY_HEADER",
    "GUARD",
    "MAX_REALISATIONS",
    "REPO_ROOT_ENV",
    "app",
    "build_router",
    "configured_keys",
    "create_app",
    "health",
    "repo_root",
    "require_api_key",
]


def configured_keys() -> frozenset[str]:
    """Every key this surface accepts right now (``RUPTURE_API_KEYS`` included)."""
    return GUARD.configured()


def repo_root() -> Path:
    raw = os.environ.get(REPO_ROOT_ENV)
    return Path(raw).expanduser() if raw else DEFAULT_REPO_ROOT


def require_api_key(
    x_api_key: Annotated[str, Depends(GUARD)],
) -> str:
    """Constant-time comparison against the configured keys. No keys means no service."""
    return x_api_key


def health() -> dict[str, str]:
    """Liveness only. Says nothing about whether a calculation would succeed."""
    return {
        "status": "ok",
        "version": __version__,
        "contract_version": CONTRACT_VERSION,
    }


def build_router(*, root: Callable[[], Path] | None = None) -> APIRouter:
    """The avoided-loss routes, for a standalone app or for the combined service.

    ``root`` overrides where the committed scenario and exposure inputs are read from; by default
    it is :func:`repo_root` (``RUPTURE_REPO_ROOT``), read per request so a redeploy that moves the
    volume does not need a code change. The combined service passes its own, so both surfaces read
    the same tree.
    """
    where = repo_root if root is None else root
    router = APIRouter(tags=["risk"])

    @router.get("/v1/scenarios", summary="Scenarios a request may name as its trigger_id")
    def list_scenarios(_: Annotated[str, Depends(GUARD)]) -> list[dict[str, object]]:
        """The scenarios a request may name as its ``trigger_id``."""
        return [
            {
                "id": name,
                "magnitude": rupture.magnitude,
                "hypothetical": rupture.hypothetical,
                "source_refs": list(rupture.source_refs),
                "notes": rupture.notes,
            }
            for name, rupture in scenarios.builtin(where()).items()
        ]

    @router.post(
        "/v1/avoided-loss",
        response_model=AvoidedLossResponseV1,
        summary="Expected loss with and without interventions",
    )
    def avoided_loss_endpoint(
        request: AvoidedLossRequestV1,
        _: Annotated[str, Depends(GUARD)],
    ) -> AvoidedLossResponseV1:
        """Expected loss with and without interventions, with intervals and provenance."""
        response = avoided_loss.respond(request, repo_root=where())
        if response.status is ResponseStatus.ERROR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=response.message or "bad request"
            )
        return response

    return router


def create_app() -> FastAPI:
    """Build the standalone risk application. A factory, so tests bring their own environment."""
    application = FastAPI(
        title="rupture risk",
        version=__version__,
        description=(
            "Ground motion to loss to avoided loss for a portfolio. "
            "rupture does not predict earthquakes."
        ),
    )

    @application.get("/health", summary="Liveness")
    def health_endpoint() -> dict[str, str]:
        return health()

    application.include_router(build_router())
    return application


app = create_app()
