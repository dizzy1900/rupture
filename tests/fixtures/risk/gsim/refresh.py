"""Re-fetch the OpenQuake GSIM verification tables and rewrite each ``provenance.json``.

Network. Run by hand, never from a test::

    uv run python tests/fixtures/risk/gsim/refresh.py

The tables are OpenQuake's own committed expected values
(``gem/oq-engine``, ``openquake/hazardlib/tests/gsim/data``) at the pinned tag. rupture's
``native_gsim`` adapter is verified against them (ADR-0020); a GSIM whose table cannot be
reproduced is not shipped. The files are upstream's, carried unmodified, under the engine's
licence (AGPL-3.0-or-later); rupture's own code is Apache-2.0 and does not link the engine.
"""

from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REF = "engine-3.26"
BASE = f"https://raw.githubusercontent.com/gem/oq-engine/{REF}/openquake/hazardlib/tests/gsim/data/"
LICENCE = "AGPL-3.0-or-later"
HERE = Path(__file__).parent

WANTED: dict[str, dict[str, str]] = {
    # rupture name -> {local file name: upstream path under .../tests/gsim/data/}
    "bssa14": {
        "BSSA_2014_MEAN.csv": "BSSA2014/BSSA_2014_MEAN.csv",
        "BSSA_2014_TOTAL_STD.csv": "BSSA2014/BSSA_2014_TOTAL_STD.csv",
        "BSSA_2014_INTER_STD.csv": "BSSA2014/BSSA_2014_INTER_STD.csv",
        "BSSA_2014_INTRA_STD.csv": "BSSA2014/BSSA_2014_INTRA_STD.csv",
        "BSSA_2014_NOSOF_MEAN.csv": "BSSA2014/BSSA_2014_NOSOF_MEAN.csv",
        "BSSA_2014_NOSOF_TOTAL_STD.csv": "BSSA2014/BSSA_2014_NOSOF_TOTAL_STD.csv",
        "BSSA_2014_NOSOF_INTER_STD.csv": "BSSA2014/BSSA_2014_NOSOF_INTER_STD.csv",
        "BSSA_2014_NOSOF_INTRA_STD.csv": "BSSA2014/BSSA_2014_NOSOF_INTRA_STD.csv",
        "BSSA_2014_HIGHQ_MEAN.csv": "BSSA2014/BSSA_2014_HIGHQ_MEAN.csv",
        "BSSA_2014_HIGHQ_TOTAL_STD.csv": "BSSA2014/BSSA_2014_HIGHQ_TOTAL_STD.csv",
        "BSSA_2014_HIGHQ_INTER_STD.csv": "BSSA2014/BSSA_2014_HIGHQ_INTER_STD.csv",
        "BSSA_2014_HIGHQ_INTRA_STD.csv": "BSSA2014/BSSA_2014_HIGHQ_INTRA_STD.csv",
        "BSSA_2014_LOWQ_MEAN.csv": "BSSA2014/BSSA_2014_LOWQ_MEAN.csv",
        "BSSA_2014_LOWQ_TOTAL_STD.csv": "BSSA2014/BSSA_2014_LOWQ_TOTAL_STD.csv",
        "BSSA_2014_LOWQ_INTER_STD.csv": "BSSA2014/BSSA_2014_LOWQ_INTER_STD.csv",
        "BSSA_2014_LOWQ_INTRA_STD.csv": "BSSA2014/BSSA_2014_LOWQ_INTRA_STD.csv",
    },
    "bchydro_sinter": {
        "BCHYDRO_SINTER_CENTRAL_MEAN.csv": "BCHYDRO/BCHYDRO_SINTER_CENTRAL_MEAN.csv",
        "BCHYDRO_SINTER_CENTRAL_STDDEV_TOTAL.csv": (
            "BCHYDRO/BCHYDRO_SINTER_CENTRAL_STDDEV_TOTAL.csv"
        ),
        "BCHYDRO_SINTER_CENTRAL_STDDEV_INTER.csv": (
            "BCHYDRO/BCHYDRO_SINTER_CENTRAL_STDDEV_INTER.csv"
        ),
        "BCHYDRO_SINTER_CENTRAL_STDDEV_INTRA.csv": (
            "BCHYDRO/BCHYDRO_SINTER_CENTRAL_STDDEV_INTRA.csv"
        ),
    },
}


def refresh() -> None:
    """Download every wanted table and write one ``provenance.json`` per GSIM directory."""
    now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    for name, files in WANTED.items():
        directory = HERE / name
        directory.mkdir(parents=True, exist_ok=True)
        records = []
        for local, remote in sorted(files.items()):
            url = BASE + remote
            with urllib.request.urlopen(url, timeout=120) as response:
                payload: bytes = response.read()
            (directory / local).write_bytes(payload)
            records.append(
                {
                    "file": local,
                    "url": url,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "bytes": len(payload),
                }
            )
            print(f"{name}/{local}: {len(payload)} bytes")  # noqa: T201
        provenance = {
            "source": "gem/oq-engine",
            "ref": REF,
            "retrieved_at": now,
            "licence": LICENCE,
            "notes": (
                "OpenQuake's own committed GSIM expected-value tables, carried unmodified as "
                "verification fixtures for rupture's native_gsim adapter (ADR-0020)."
            ),
            "files": records,
        }
        (directory / "provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    refresh()
