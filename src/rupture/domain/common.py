"""Shared building blocks for domain models: base model, UTC datetimes, provenance, hashing."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _require_utc(value: datetime) -> datetime:
    """All rupture timestamps are timezone-aware and normalised to UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        msg = "timestamps must be timezone-aware (UTC)"
        raise ValueError(msg)
    return value.astimezone(UTC)


UTCDatetime = Annotated[datetime, AfterValidator(_require_utc)]
"""A timezone-aware datetime, normalised to UTC on validation."""


def utc_now() -> datetime:
    """Current time, UTC, tz-aware."""
    return datetime.now(tz=UTC)


class RuptureModel(BaseModel):
    """Base for every domain model: strict fields, frozen, deterministic JSON."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        ser_json_timedelta="iso8601",
        str_strip_whitespace=True,
    )

    def canonical_json(self) -> str:
        """Stable JSON used for hashing: sorted keys, no whitespace, ISO timestamps."""
        payload: Any = self.model_dump(mode="json")
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    def content_hash(self) -> str:
        """sha256 of :meth:`canonical_json`, hex."""
        return sha256_hex(self.canonical_json())


def sha256_hex(data: str | bytes) -> str:
    """Hex sha256 of a string (utf-8) or bytes."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


class Provenance(RuptureModel):
    """Where a record came from. Required on every ingested row and every derived product.

    ``licence`` is the upstream licence identifier (SPDX where one exists, otherwise the
    provider's own terms label). ``sha256`` is the digest of the raw payload the record was
    parsed from, so a re-fetch can be compared byte-for-byte. Unknowns are ``None``, never guessed.
    """

    source: str = Field(
        description="Provider/catalogue identifier, e.g. 'usgs-comcat', 'isc', 'gcmt'."
    )
    source_url: str | None = Field(
        default=None, description="Exact URL or file path the payload came from."
    )
    retrieved_at: UTCDatetime = Field(description="When the payload was fetched (UTC).")
    sha256: str | None = Field(default=None, description="Digest of the raw payload, hex.")
    licence: str | None = Field(
        default=None, description="Upstream licence (SPDX id or provider terms label)."
    )
    adapter_version: str = Field(
        description="Version of the rupture adapter that parsed the payload."
    )
    notes: str | None = None
