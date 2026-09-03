"""Re-cut the committed ComCat slices behind the aftershock validation (network).

Run from the repository root::

    uv run python -m tests.fixtures.aftershock.make_fixtures

Each slice is a byte-exact ComCat FDSN GeoJSON response covering (a) about a decade of
pre-mainshock seismicity in the box around the sequence, which is what gives the ETAS fit an
auxiliary window and a background rate, and (b) the sequence itself out to 38 days after the
mainshock, which is the longest window any issue time in ``docs/AFTERSHOCK.md`` closes
(issue at +7 d, horizon 30 d). Nothing here is edited by hand; ``provenance.json`` records the
exact query, the retrieval time, the digest and the licence.

The query floor is reported magnitude 3.8 rather than 4.0 because most entries in both boxes are
teleseismic ``mb``: Scordilis (2006) maps mb 3.8 to Mw 4.26, so a 3.8 floor covers the published
Mc of both regions (4.4 for nepal-himalaya, 4.3 for turkiye-eaf) with a margin. It does not make
the catalogue complete below those values; it only removes the query itself as the binding cut.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from rupture.domain import sha256_hex, utc_now

BASE_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"
FIXTURE_DIR = Path(__file__).resolve().parent
PROVENANCE_FILE = FIXTURE_DIR / "provenance.json"
TIMEOUT_S = 300

QUERIES: dict[str, dict[str, Any]] = {
    "comcat-nepal-2005-2015-m3.8.geojson": {
        "starttime": "2005-01-01T00:00:00",
        "endtime": "2015-06-10T00:00:00",
        "minmagnitude": 3.8,
        "minlongitude": 80.0,
        "maxlongitude": 89.0,
        "minlatitude": 26.0,
        "maxlatitude": 31.0,
        "notes": (
            "Nepal/Himalaya box: 10 years of pre-mainshock seismicity plus the 2015 Gorkha "
            "sequence (mainshock us20002926, 2015-04-25T06:11:26Z) out to +46 days"
        ),
    },
    "comcat-turkiye-2013-2023-m3.8.geojson": {
        "starttime": "2013-01-01T00:00:00",
        "endtime": "2023-03-20T00:00:00",
        "minmagnitude": 3.8,
        "minlongitude": 35.0,
        "maxlongitude": 42.0,
        "minlatitude": 35.5,
        "maxlatitude": 40.0,
        "notes": (
            "East Anatolian box: 10 years of pre-mainshock seismicity plus the 2023 "
            "Kahramanmaras sequence (mainshock us6000jllz, 2023-02-06T01:17:35Z) out to +42 days"
        ),
    },
}


def _url(params: dict[str, Any]) -> str:
    query = {k: v for k, v in params.items() if k != "notes"}
    return f"{BASE_URL}?{urlencode({'format': 'geojson', **query, 'orderby': 'time-asc'})}"


def main() -> None:
    files: dict[str, Any] = {}
    for name, params in QUERIES.items():
        url = _url(params)
        with urlopen(url, timeout=TIMEOUT_S) as response:  # fixed https host
            payload: bytes = response.read()
        doc = json.loads(payload)
        if doc.get("type") != "FeatureCollection":
            msg = f"{name}: response is not a FeatureCollection"
            raise RuntimeError(msg)
        (FIXTURE_DIR / name).write_bytes(payload)
        files[name] = {
            "source_url": url,
            "retrieved_at": utc_now().isoformat(),
            "sha256": sha256_hex(payload),
            "size": len(payload),
            "n_events": len(doc["features"]),
            "query": {k: v for k, v in params.items() if k != "notes"},
            "notes": params["notes"],
        }
        print(f"wrote {name}: {len(doc['features'])} features, {len(payload)} bytes")  # noqa: T201
    PROVENANCE_FILE.write_text(
        json.dumps(
            {
                "source": "usgs-comcat",
                "licence": "public-domain (USGS)",
                "adapter_version": "rupture.services.aftershock.fixtures",
                "command": "uv run python -m tests.fixtures.aftershock.make_fixtures",
                "rule": "never edited by hand; regenerate with this script and re-record",
                "files": files,
                "notes": (
                    "byte-exact ComCat FDSN GeoJSON responses; eventtype unrestricted. "
                    "Magnitudes are homogenised to Mw at load time by "
                    "rupture.pipelines.magnitudes.preferred_mw under the STRICT policy."
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {PROVENANCE_FILE}")  # noqa: T201


if __name__ == "__main__":
    main()
