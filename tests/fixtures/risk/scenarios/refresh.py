"""Re-fetch the published rupture models rupture's scenarios are built from. Run by hand::

    uv run python tests/fixtures/risk/scenarios/refresh.py

Network. Currently one model: the USGS finite-fault solution for the 2015 Gorkha earthquake
(event ``us20002926``), in SRCMOD's ``.fsp`` format. It is committed verbatim with a
``provenance.json`` so the Gorkha-repeat scenario is reproducible offline and its geometry can be
traced back to a published inversion rather than to a number someone chose.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import requests

HERE = Path(__file__).parent
EVENT_ID = "us20002926"
DETAIL_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
LICENCE = "US Government work (USGS); public domain"
WANTED = "complete_inversion.fsp"
PRODUCT = "finite-fault"


def refresh() -> None:
    detail = requests.get(
        DETAIL_URL, params={"format": "geojson", "eventid": EVENT_ID}, timeout=120
    )
    detail.raise_for_status()
    payload = detail.json()
    products = payload["properties"]["products"][PRODUCT]
    product = products[0]
    content = product["contents"][WANTED]
    body = requests.get(content["url"], timeout=300)
    body.raise_for_status()

    directory = HERE / "gorkha2015"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / WANTED).write_bytes(body.content)
    (directory / "provenance.json").write_text(
        json.dumps(
            {
                "source": "usgs-comcat",
                "event_id": EVENT_ID,
                "product": PRODUCT,
                "product_code": product.get("code"),
                "product_source": product.get("source"),
                "source_url": content["url"],
                "detail_url": f"{DETAIL_URL}?format=geojson&eventid={EVENT_ID}",
                "retrieved_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
                "sha256": hashlib.sha256(body.content).hexdigest(),
                "bytes": len(body.content),
                "licence": LICENCE,
                "magnitude": payload["properties"]["mag"],
                "place": payload["properties"]["place"],
                "notes": (
                    "USGS NEIC finite-fault inversion for the 2015 Gorkha earthquake, in SRCMOD "
                    "FSP format. rupture builds the Gorkha-repeat scenario's rupture plane from "
                    "this file; see rupture.risk.scenarios for the trimming rule."
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"{WANTED}: {len(body.content)} bytes")  # noqa: T201


if __name__ == "__main__":
    refresh()
