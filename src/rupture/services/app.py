"""The rupture HTTP service: both surfaces, one application (ADR-0045).

    uvicorn rupture.services.app:create_app --factory --host 0.0.0.0 --port 8000

Routes:

===========================================  ====  =========================================
``GET  /health``                             none  liveness, and what each surface is holding
``GET  /healthz``                            none  the same body (the aftershock app's old path)
``GET  /v1/scenarios``                       key   scenarios a request may name
``POST /v1/avoided-loss``                    key   expected loss, and what an intervention avoids
``POST /aftershock/forecast``                key   probability of a further event, for a sequence
``GET  /aftershock/grid/{grid_id}``          key   the gridded rate forecast behind a forecast
===========================================  ====  =========================================

The two surfaces used to be two applications on two ports with two health paths and two unrelated
key schemes, and the assembly was left to "whoever deploys it". They are one process here, with
one OpenAPI document at ``/docs`` and one key check (:mod:`rupture.services.auth`):
``RUPTURE_API_KEYS`` is accepted everywhere, and the older per-surface variables still work.

**A degraded surface is reported, not hidden.** The aftershock surface has to load catalogues at
start-up; a deployment that ships without them (or points ``RUPTURE_AFTERSHOCK_CATALOGS`` at a
directory that is not there) gets an application that still serves the risk surface, says so in
``/health`` -- ``surfaces.aftershock.status == "unavailable"`` with the reason -- and answers 503
with that reason on the aftershock routes. Silently serving half a service, or refusing to start
with a stack trace in a container log, are both worse.

Configuration is environment variables only:

``RUPTURE_API_KEYS``
    Comma-separated keys accepted by both surfaces. ``RUPTURE_RISK_API_KEYS``,
    ``RUPTURE_AFTERSHOCK_API_KEYS`` and ``RUPTURE_AFTERSHOCK_API_KEY`` still work per surface.
    With no key configured for a surface, its routes answer 503 rather than serving open.
``RUPTURE_REPO_ROOT``
    Where the committed scenarios, exposure and sequence catalogues live (``/app`` in the image).
``RUPTURE_AFTERSHOCK_CATALOGS``
    ``<name>=<catalog_dir>,<region_file>[,<fits_dir>];...`` -- catalogues to serve beyond the two
    committed validation sequences.
``RUPTURE_AFTERSHOCK_ALLOW_REFIT``
    ``1`` to let a request whose scheduled fit is missing refit inside the request. Off by
    default: an EM fit takes tens of seconds to minutes. The supported way to keep fits current is
    ``rupture aftershock refit`` on a schedule (``docs/AFTERSHOCK.md`` § 2).
``RUPTURE_AFTERSHOCK_GRID_DIR``
    Where issued grids are kept so ``GET /aftershock/grid/{id}`` can answer. Unset means an
    in-process cache, which is not shared between uvicorn workers.

rupture does not predict earthquakes: every number here is a rate, a probability or a loss.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, status

from rupture import __version__
from rupture.domain.avoided_loss_v1 import CONTRACT_VERSION
from rupture.risk import service as risk_service
from rupture.services.aftershock import service as aftershock_service
from rupture.services.auth import SHARED_KEYS_ENV

TITLE = "rupture"
DESCRIPTION = (
    "Probabilistic seismic forecasting and cascade-loss model. Two surfaces: avoided loss for a "
    "portfolio (F2) and operational aftershock forecasts for a sequence (F1). "
    "rupture does not predict earthquakes: every number is a rate, a probability or a loss."
)

__all__ = ["DESCRIPTION", "TITLE", "create_app", "repo_root"]


def repo_root(env: Mapping[str, str] | None = None) -> Path:
    """``RUPTURE_REPO_ROOT`` if set, else the checkout this package was installed from."""
    environ = os.environ if env is None else env
    raw = environ.get(risk_service.REPO_ROOT_ENV)
    return Path(raw).expanduser() if raw else Path(__file__).resolve().parents[3]


def _unavailable_aftershock_router(reason: str) -> APIRouter:
    """Routes that answer 503 with the reason the surface could not load."""
    router = APIRouter(tags=["aftershock"])

    def refuse() -> None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"the aftershock surface is not available in this deployment: {reason}",
        )

    @router.post("/aftershock/forecast", summary="Unavailable in this deployment")
    def forecast() -> None:
        refuse()

    @router.get("/aftershock/grid/{grid_id}", summary="Unavailable in this deployment")
    def grid(grid_id: str) -> None:
        refuse()

    return router


def create_app(
    *, root: Path | None = None, aftershock: aftershock_service.AftershockState | None = None
) -> FastAPI:
    """Build the combined application: the risk router and the aftershock router in one app.

    ``aftershock`` lets a caller supply an already-built state (a test with a crude forecaster, an
    embedder that loads its catalogues itself); by default it is built from the environment.
    """
    application = FastAPI(title=TITLE, version=__version__, description=DESCRIPTION)
    where = repo_root() if root is None else Path(root)

    aftershock_health: dict[str, object]
    try:
        state = (
            aftershock
            if aftershock is not None
            else aftershock_service.build_state(repo_root=where)
        )
    except (OSError, ValueError, RuntimeError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        aftershock_router = _unavailable_aftershock_router(reason)
        aftershock_health = {"status": "unavailable", "service": "aftershock", "reason": reason}
    else:
        aftershock_router = aftershock_service.build_router(state)
        aftershock_health = state.health()

    def body() -> dict[str, object]:
        return {
            "status": "ok",
            "version": __version__,
            "contract_version": CONTRACT_VERSION,
            "repo_root": str(where),
            "shared_key_env": SHARED_KEYS_ENV,
            "surfaces": {
                "risk": risk_service.health(),
                "aftershock": aftershock_health,
            },
        }

    @application.get("/health", summary="Liveness, and what each surface is holding")
    def health() -> dict[str, object]:
        """Liveness only. A surface reported ``unavailable`` still returns 200 here."""
        return body()

    @application.get("/healthz", summary="Alias of /health (the aftershock app's old path)")
    def healthz() -> dict[str, object]:
        return body()

    application.include_router(risk_service.build_router(root=lambda: where))
    application.include_router(aftershock_router)
    return application


# There is deliberately no module-level ``app``: building one at import time would read
# catalogues off disk during ``import rupture.services.app``. Serve it as
# ``uvicorn rupture.services.app:create_app --factory``, which is what the image's CMD does.
