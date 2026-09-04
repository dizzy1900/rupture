"""Re-extract the GSIM coefficient tables that ``native_gsim`` evaluates. Network; run by hand::

    uv run python tests/fixtures/risk/gsim/refresh_coefficients.py

The coefficients are the published tables of the GSIM papers (Boore, Stewart, Seyhan & Atkinson
2014, Earthquake Spectra 30(3), tables 3-5, doi:10.1193/070113EQS184M; Abrahamson, Gregor & Addo
2016, Earthquake Spectra 32(1), tables 2-4, doi:10.1193/051712EQS188MR). rupture does not re-type
them by hand — a hand-typed coefficient is a
fabrication risk — it extracts the machine-readable transcription that ``gem/oq-engine`` carries,
at the pinned tag, and stores it verbatim under ``src/rupture/adapters/groundmotion/data/`` with a
``provenance.json``.

Licence note, recorded rather than resolved here: oq-engine is AGPL-3.0-or-later and rupture is
Apache-2.0. The extracted tables are numeric coefficients first published in the journal articles
above; the transcription is upstream's. ``docs/RISK.md`` flags this for the architect.
"""

from __future__ import annotations

import ast
import hashlib
import json
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

REF = "engine-3.26"
BASE = f"https://raw.githubusercontent.com/gem/oq-engine/{REF}/openquake/hazardlib/"
OUT = Path(__file__).resolve().parents[4] / "src" / "rupture" / "adapters" / "groundmotion" / "data"

# local file name -> (module path under hazardlib/, class name, attribute name)
WANTED: dict[str, tuple[str, str, str]] = {
    "bssa14_coeffs.txt": ("gsim/boore_2014.py", "BooreEtAl2014", "COEFFS"),
    # The two regional anelastic-attenuation branches of the same model: identical equations,
    # a different Dc3 column. They are the branches of the GSIM logic tree of ADR-0037.
    "bssa14_highq_coeffs.txt": ("gsim/boore_2014.py", "BooreEtAl2014HighQ", "COEFFS"),
    "bssa14_lowq_coeffs.txt": ("gsim/boore_2014.py", "BooreEtAl2014LowQ", "COEFFS"),
    "bchydro_sinter_coeffs.txt": (
        "gsim/abrahamson_2015.py",
        "AbrahamsonEtAl2015SInter",
        "COEFFS",
    ),
    "bchydro_sinter_dc1.txt": (
        "gsim/abrahamson_2015.py",
        "AbrahamsonEtAl2015SInter",
        "COEFFS_MAG_SCALE",
    ),
}


def _table_literal(source: str, class_name: str, attribute: str) -> str:
    """The ``table=`` string literal of ``<class_name>.<attribute> = CoeffsTable(...)``."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        for stmt in node.body:
            if not isinstance(stmt, ast.Assign) or not isinstance(stmt.value, ast.Call):
                continue
            names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if attribute not in names:
                continue
            for kw in stmt.value.keywords:
                if kw.arg == "table" and isinstance(kw.value, ast.Constant):
                    return str(kw.value.value)
    msg = f"{class_name}.{attribute} table literal not found"
    raise LookupError(msg)


def refresh() -> None:
    """Fetch each module, extract the table, write it out, record provenance."""
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    cache: dict[str, str] = {}
    records = []
    for local, (module, class_name, attribute) in sorted(WANTED.items()):
        if module not in cache:
            with urllib.request.urlopen(BASE + module, timeout=120) as response:
                cache[module] = response.read().decode("utf-8")
        text = _table_literal(cache[module], class_name, attribute).strip() + "\n"
        (OUT / local).write_text(text, encoding="utf-8")
        records.append(
            {
                "file": local,
                "url": BASE + module,
                "extracted_from": f"{class_name}.{attribute}",
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "rows": len(text.strip().splitlines()) - 1,
            }
        )
        print(f"{local}: {records[-1]['rows']} rows")  # noqa: T201
    (OUT / "provenance.json").write_text(
        json.dumps(
            {
                "source": "gem/oq-engine",
                "ref": REF,
                "retrieved_at": now,
                "licence": "AGPL-3.0-or-later (oq-engine transcription)",
                "primary_sources": [
                    "Boore, D.M., Stewart, J.P., Seyhan, E. & Atkinson, G.M. (2014). "
                    "NGA-West2 equations for PGA, PGV and 5%-damped PSA for shallow crustal "
                    "earthquakes. Earthquake Spectra 30(3), 1057-1085. "
                    "doi:10.1193/070113EQS184M [title abbreviated; see docs/RISK.md]",
                    "Abrahamson, N., Gregor, N. & Addo, K. (2016). BC Hydro ground motion "
                    "model for subduction earthquakes. Earthquake Spectra 32(1), 23-44. "
                    "doi:10.1193/051712EQS188MR [title abbreviated; see docs/RISK.md]",
                ],
                "notes": (
                    "Coefficient tables extracted verbatim from the oq-engine source at the "
                    "pinned tag; never hand-typed. See docs/RISK.md for the licence note."
                ),
                "files": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    refresh()
