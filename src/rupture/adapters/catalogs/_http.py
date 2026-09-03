"""HTTP fetch with provenance for the catalogue adapters.

Every fetch returns the raw bytes together with ``retrieved_at`` and the ``sha256`` of the
payload, so the caller can build :class:`~rupture.domain.Provenance` without re-hashing. An
optional on-disk cache (``data/raw/...``) keyed by the exact URL makes long paged pulls (ISC
by year) resumable; a cached page carries the ``retrieved_at`` of the original fetch, never the
time it was re-read.

Requests carry ``RUPTURE_CONTACT_EMAIL`` in the ``User-Agent`` when set (ADR-0004).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from rupture import __version__
from rupture.domain import sha256_hex, utc_now

DEFAULT_TIMEOUT_S = 300.0
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class FetchError(RuntimeError):
    """A request failed after retries, or returned something the adapter cannot use."""


@dataclass(frozen=True, slots=True)
class RawPayload:
    """Bytes as received, plus what is needed for provenance."""

    url: str
    content: bytes
    retrieved_at: datetime
    status_code: int

    @property
    def sha256(self) -> str:
        return sha256_hex(self.content)


def user_agent() -> str:
    contact = os.environ.get("RUPTURE_CONTACT_EMAIL", "").strip()
    base = f"rupture/{__version__} (+https://github.com/dizzy1900/rupture)"
    return f"{base} {contact}" if contact else base


def _cache_paths(cache_dir: Path, url: str) -> tuple[Path, Path]:
    key = hashlib.sha1(url.encode("utf-8"), usedforsecurity=False).hexdigest()
    return cache_dir / f"{key}.bin", cache_dir / f"{key}.json"


def fetch_bytes(
    url: str,
    *,
    cache_dir: Path | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    retries: int = 4,
    backoff_s: float = 5.0,
    ok_statuses: frozenset[int] = frozenset({200, 204, 404}),
    session: requests.Session | None = None,
) -> RawPayload:
    """GET ``url`` and return the payload; raise :class:`FetchError` on persistent failure.

    204/404 are returned (not raised) because FDSN services use them for "no data"; the caller
    decides. Anything in ``RETRY_STATUSES`` is retried with linear back-off; other statuses
    raise immediately.
    """
    if cache_dir is not None:
        blob, meta = _cache_paths(cache_dir, url)
        if blob.exists() and meta.exists():
            info = json.loads(meta.read_text(encoding="utf-8"))
            content = blob.read_bytes()
            if sha256_hex(content) != info["sha256"]:
                msg = f"cache corrupt for {url}: sha256 mismatch"
                raise FetchError(msg)
            return RawPayload(
                url=url,
                content=content,
                retrieved_at=datetime.fromisoformat(info["retrieved_at"]),
                status_code=int(info["status_code"]),
            )

    sess = session or requests.Session()
    headers = {"User-Agent": user_agent()}
    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            resp = sess.get(url, headers=headers, timeout=timeout_s)
        except requests.RequestException as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status_code in ok_statuses:
                payload = RawPayload(
                    url=url,
                    content=resp.content,
                    retrieved_at=utc_now(),
                    status_code=resp.status_code,
                )
                if cache_dir is not None:
                    _write_cache(cache_dir, payload)
                return payload
            if resp.status_code not in RETRY_STATUSES:
                msg = f"GET {url} -> HTTP {resp.status_code}: {resp.text[:300]}"
                raise FetchError(msg)
            last_error = f"HTTP {resp.status_code}"
        if attempt < retries:
            time.sleep(backoff_s * (attempt + 1))
    msg = f"GET {url} failed after {retries + 1} attempts: {last_error}"
    raise FetchError(msg)


def _write_cache(cache_dir: Path, payload: RawPayload) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    blob, meta = _cache_paths(cache_dir, payload.url)
    blob.write_bytes(payload.content)
    meta.write_text(
        json.dumps(
            {
                "url": payload.url,
                "retrieved_at": payload.retrieved_at.isoformat(),
                "sha256": payload.sha256,
                "status_code": payload.status_code,
                "size": len(payload.content),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
