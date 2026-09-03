"""A small HTTP surface for the avoided-loss contract.

One endpoint that matters: ``POST /v1/avoided-loss`` takes an ``AvoidedLossRequestV1`` (serac's
field names included, per ADR-0021) and returns an ``AvoidedLossResponseV1``. The service does no
modelling of its own; it is a thin shell over :func:`rupture.risk.avoided_loss.respond`, so an
answer over HTTP and an answer from the CLI are the same answer.

**Authentication is an API key header and nothing else.** ``X-API-Key`` must match one of the keys
in ``RUPTURE_RISK_API_KEYS`` (comma-separated). With no keys configured the service refuses every
request rather than running open: an unauthenticated loss service is not a default anyone should
get by forgetting to set a variable. There is no user model, no session, no rate limiting and no
audit log; ``docs/RISK.md`` says so under Deployment, and this is not a public-internet service.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status

from rupture import __version__
from rupture.domain.avoided_loss_v1 import (
    CONTRACT_VERSION,
    AvoidedLossRequestV1,
    AvoidedLossResponseV1,
    ResponseStatus,
)
from rupture.risk import avoided_loss, scenarios

API_KEY_ENV = "RUPTURE_RISK_API_KEYS"
API_KEY_HEADER = "X-API-Key"
REPO_ROOT_ENV = "RUPTURE_REPO_ROOT"
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[3]
MAX_REALISATIONS = 5000
"""A request cannot ask for an unbounded calculation; the cap is refused, not silently reduced."""


def configured_keys() -> frozenset[str]:
    raw = os.environ.get(API_KEY_ENV, "")
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


def repo_root() -> Path:
    raw = os.environ.get(REPO_ROOT_ENV)
    return Path(raw).expanduser() if raw else DEFAULT_REPO_ROOT


def require_api_key(
    x_api_key: Annotated[str | None, Header(alias=API_KEY_HEADER)] = None,
) -> str:
    """Constant-time comparison against the configured keys. No keys means no service."""
    keys = configured_keys()
    if not keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"no API keys configured; set {API_KEY_ENV}",
        )
    if x_api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"missing {API_KEY_HEADER}"
        )
    if not any(secrets.compare_digest(x_api_key, key) for key in keys):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid {API_KEY_HEADER}"
        )
    return x_api_key


def create_app() -> FastAPI:
    """Build the application. A factory, so tests can construct it with their own environment."""
    application = FastAPI(
        title="rupture risk",
        version=__version__,
        description=(
            "Ground motion to loss to avoided loss for a portfolio. "
            "rupture does not predict earthquakes."
        ),
    )

    @application.get("/health")
    def health() -> dict[str, str]:
        """Liveness only. Says nothing about whether a calculation would succeed."""
        return {
            "status": "ok",
            "version": __version__,
            "contract_version": CONTRACT_VERSION,
        }

    @application.get("/v1/scenarios")
    def list_scenarios(_: Annotated[str, Depends(require_api_key)]) -> list[dict[str, object]]:
        """The scenarios a request may name as its ``trigger_id``."""
        return [
            {
                "id": name,
                "magnitude": rupture.magnitude,
                "hypothetical": rupture.hypothetical,
                "source_refs": list(rupture.source_refs),
                "notes": rupture.notes,
            }
            for name, rupture in scenarios.builtin(repo_root()).items()
        ]

    @application.post("/v1/avoided-loss", response_model=AvoidedLossResponseV1)
    def avoided_loss_endpoint(
        request: AvoidedLossRequestV1,
        _: Annotated[str, Depends(require_api_key)],
    ) -> AvoidedLossResponseV1:
        """Expected loss with and without interventions, with intervals and provenance."""
        response = avoided_loss.respond(request, repo_root=repo_root())
        if response.status is ResponseStatus.ERROR:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=response.message or "bad request"
            )
        return response

    return application


app = create_app()
