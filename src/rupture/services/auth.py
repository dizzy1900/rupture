"""One API-key check for every HTTP surface rupture serves.

Both surfaces (avoided loss, aftershock forecast) authenticate the same way and nothing else:
an ``X-API-Key`` header, compared in constant time against the keys the process was configured
with. There is no user model, no session, no rate limiting and no audit log; ``docs/RISK.md`` and
``docs/AFTERSHOCK.md`` say so, and neither surface is meant for the public internet.

Two rules that are not negotiable per surface:

* **No keys configured means no service**, not an open one. A route whose guard finds no key
  answers ``503`` naming the variables that would configure it, so forgetting to set a variable
  cannot silently publish a loss model.
* **Constant-time comparison.** ``secrets.compare_digest`` on every candidate, so a wrong key
  leaks nothing about how much of it was right.

Keys come from ``RUPTURE_API_KEYS`` (the whole service) plus whatever surface-specific variable a
surface has always honoured, so a deployment that already sets ``RUPTURE_RISK_API_KEYS`` or
``RUPTURE_AFTERSHOCK_API_KEY`` keeps working when the two apps become one.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Header, HTTPException, status

API_KEY_HEADER = "X-API-Key"
SHARED_KEYS_ENV = "RUPTURE_API_KEYS"
"""Comma-separated keys accepted by every surface of the combined service."""


def split_keys(raw: str | None) -> frozenset[str]:
    """Comma-separated keys, whitespace-trimmed, empties dropped."""
    if not raw:
        return frozenset()
    return frozenset(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class ApiKeyGuard:
    """A FastAPI dependency: accept a request only if it carries a configured key.

    ``env_vars`` are read at *request* time, not at import time, so a key rotated in the process
    environment takes effect without rebuilding the application. ``static_keys`` are keys passed
    straight to a factory (tests, and ``create_app(api_key=...)``).
    """

    surface: str = "rupture"
    env_vars: tuple[str, ...] = (SHARED_KEYS_ENV,)
    static_keys: frozenset[str] = field(default_factory=frozenset)

    def configured(self) -> frozenset[str]:
        """Every key this guard would accept right now."""
        keys = set(self.static_keys)
        for name in self.env_vars:
            keys |= split_keys(os.environ.get(name))
        return frozenset(keys)

    def is_configured(self) -> bool:
        return bool(self.configured())

    def unconfigured_detail(self) -> str:
        return (
            f"no API key configured for the {self.surface} surface; set "
            f"{' or '.join(self.env_vars)}"
        )

    def __call__(
        self, x_api_key: Annotated[str | None, Header(alias=API_KEY_HEADER)] = None
    ) -> str:
        keys = self.configured()
        if not keys:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=self.unconfigured_detail(),
            )
        if x_api_key is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=f"missing {API_KEY_HEADER}"
            )
        # compare_digest against every candidate: no early exit on a prefix match.
        if not any(secrets.compare_digest(x_api_key, key) for key in sorted(keys)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid {API_KEY_HEADER}"
            )
        return x_api_key
