"""OpenQuake source models per region (ADR-0008).

* ``turkiye-eaf``: ESHM20 (Danciu et al. 2021), OpenQuake input files from the EFEHR GitLab
  project ``efehr/eshm20``, directory
  ``oq_computational/oq_configuration_eshm20_v12e_region_main`` (the mainland model that covers
  Türkiye). The whole directory is 55 files, about 40 MB (measured through the GitLab files API
  on 2026-09-03), so ``fetch_eshm20`` downloads all of it at a pinned commit into
  ``data/raw/eshm20/`` and writes ``manifest.json`` (paths, sizes, sha256, blob ids, commit,
  licence text as found in the repository ``LICENSE`` file: CC-BY 4.0 with the citation
  requirement).

  **What a fresh clone has, exactly:** ``manifest.json`` only. It is committed (the ``.gitignore``
  whitelists manifest sidecars under ``data/raw/``); the 40 MB of model files are neither
  committed nor DVC-tracked, so ``dvc pull`` does not bring them and nothing on disk matches the
  manifest until :func:`fetch_eshm20` is re-run against EFEHR GitLab at the recorded ``commit``.
  The manifest is therefore the *recovery instruction and the integrity check*, not a pointer to
  a cached copy: re-fetch, then :func:`verify_manifest` confirms every sha256 matches what was
  first retrieved. :func:`model_present` answers "are the files here" without reading them all,
  which is what callers and gates should branch on rather than the manifest's existence.
* ``california`` and ``nepal-himalaya``: no openly licensed NRML model verified;
  :func:`available_models` returns ``[]`` with the gap reason referencing ADR-0008.

``parse_nrml_header`` is the pure step exercised offline on a committed real excerpt (the head
of the ESHM20 source-model logic tree).
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

from rupture import __version__
from rupture.domain import sha256_hex, utc_now

SOURCE_ID = "eshm20"
ADAPTER_VERSION = "0.1.0"
GITLAB_API = "https://gitlab.seismo.ethz.ch/api/v4/projects/efehr%2Feshm20"
PROJECT_URL = "https://gitlab.seismo.ethz.ch/efehr/eshm20"
MAIN_REGION_DIR = "oq_computational/oq_configuration_eshm20_v12e_region_main"
SOURCE_MODEL_LOGIC_TREE = f"{MAIN_REGION_DIR}/source_model_logic_tree_eshm20_model_v12e.xml"
GSIM_LOGIC_TREE = f"{MAIN_REGION_DIR}/gmpe_complete_logic_tree_5br.xml"
LICENCE_FILE = "LICENSE"
LICENCE_SPDX = "CC-BY-4.0"
CITATION = (
    "Danciu, L., Nandan, S., Reyes, C., Wiemer, S., & Giardini, D. (2021). OpenQuake Input "
    "Files for the 2020 Update of the European Seismic Hazard Model (ESHM20) [Data set]. EFEHR. "
    "https://doi.org/10.12686/ESHM20-OQ-INPUT"
)
DEFAULT_RAW_DIR = Path("data") / "raw" / "eshm20"
ASK_BEFORE_BYTES = 5 * 1024**3

NRML_NS = "http://openquake.org/xmlns/nrml/0.5"
NRML_NS_04 = "http://openquake.org/xmlns/nrml/0.4"

GAP_REASON: dict[str, str] = {
    "california": (
        "no openly licensed OpenQuake (NRML) source model verified for California; the USGS "
        "NSHM is public domain but in nshmp format (ADR-0008: gap, conversion planned)"
    ),
    "nepal-himalaya": (
        "no openly licensed OpenQuake source model found for the Nepal Himalaya (ADR-0008: gap; "
        "plan: GEM mosaic licensing or a GAF+catalogue model in a new ADR)"
    ),
}


@dataclass(frozen=True, slots=True)
class ModelRef:
    """One available source model for a region."""

    model_id: str
    region_id: str
    repository: str
    path: str
    licence: str
    citation: str


def available_models(region_id: str) -> tuple[list[ModelRef], str | None]:
    """``(models, gap_reason)``: models is empty for regions with a documented gap."""
    if region_id == "turkiye-eaf":
        return (
            [
                ModelRef(
                    model_id="eshm20-v12e-main",
                    region_id=region_id,
                    repository=PROJECT_URL,
                    path=MAIN_REGION_DIR,
                    licence=LICENCE_SPDX,
                    citation=CITATION,
                )
            ],
            None,
        )
    return [], GAP_REASON.get(region_id, f"no source model registered for {region_id!r} (ADR-0008)")


@dataclass(frozen=True, slots=True)
class NrmlHeader:
    """What the first element of an NRML document says."""

    namespace: str
    root_tag: str
    child_tag: str | None
    child_id: str | None


def parse_nrml_header(payload: bytes | str) -> NrmlHeader:
    """Pure: read the root element and its first child from an NRML document **or a byte prefix**.

    Uses a streaming parser and stops after the first two start tags, so a truncated file (the
    committed fixture is the byte-exact head of the ESHM20 source-model logic tree) parses as
    long as the prefix reaches the first child element.
    """
    data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
    starts: list[ET.Element] = []
    parser: Any = ET.XMLPullParser(events=("start",))
    try:
        parser.feed(data)
        events: list[Any] = list(parser.read_events())
        for item in events:
            elem = item[1]
            if isinstance(elem, ET.Element):
                starts.append(elem)
            if len(starts) >= 2:
                break
    except ET.ParseError:
        pass  # a truncated prefix ends mid-document; what was read before is still valid
    if not starts:
        msg = "no XML element found"
        raise ValueError(msg)
    root = starts[0]
    ns, _, tag = root.tag.rpartition("}")
    ns = ns.lstrip("{")
    if ns not in {NRML_NS, NRML_NS_04}:
        msg = f"not an NRML document (namespace {ns!r})"
        raise ValueError(msg)
    child = starts[1] if len(starts) > 1 else None
    child_tag = child.tag.rpartition("}")[2] if child is not None else None
    child_id = (child.get("logicTreeID") or child.get("id")) if child is not None else None
    return NrmlHeader(namespace=ns, root_tag=tag, child_tag=child_tag, child_id=child_id)


def _headers() -> dict[str, str]:
    return {"User-Agent": f"rupture/{__version__} (+https://github.com/dizzy1900/rupture)"}


def _get_json(url: str, timeout_s: float) -> Any:
    resp = requests.get(url, headers=_headers(), timeout=timeout_s)
    if resp.status_code != 200:
        msg = f"GET {url} -> HTTP {resp.status_code}"
        raise RuntimeError(msg)
    data: Any = resp.json()
    return data


def list_tree(
    path: str = MAIN_REGION_DIR, *, ref: str = "master", timeout_s: float = 120.0
) -> list[dict[str, Any]]:
    """Recursive GitLab tree listing (blobs and trees) under ``path``."""
    out: list[dict[str, Any]] = []
    page = 1
    while True:
        url = (
            f"{GITLAB_API}/repository/tree?path={quote(path, safe='')}&ref={ref}"
            f"&recursive=true&per_page=100&page={page}"
        )
        resp = requests.get(url, headers=_headers(), timeout=timeout_s)
        if resp.status_code != 200:
            msg = f"GET {url} -> HTTP {resp.status_code}"
            raise RuntimeError(msg)
        items = resp.json()
        out.extend(items)
        nxt = resp.headers.get("X-Next-Page", "")
        if not nxt:
            break
        page = int(nxt)
    return out


def file_info(path: str, *, ref: str, timeout_s: float = 120.0) -> dict[str, Any]:
    info: dict[str, Any] = _get_json(
        f"{GITLAB_API}/repository/files/{quote(path, safe='')}?ref={ref}", timeout_s
    )
    return info


def fetch_raw(path: str, *, ref: str, timeout_s: float = 300.0) -> bytes:
    url = f"{GITLAB_API}/repository/files/{quote(path, safe='')}/raw?ref={ref}"
    resp = requests.get(url, headers=_headers(), timeout=timeout_s)
    if resp.status_code != 200:
        msg = f"GET {url} -> HTTP {resp.status_code}"
        raise RuntimeError(msg)
    return resp.content


def resolve_commit(ref: str = "master", *, timeout_s: float = 60.0) -> str:
    data = _get_json(f"{GITLAB_API}/repository/branches/{quote(ref, safe='')}", timeout_s)
    return str(data["commit"]["id"])


def fetch_eshm20(
    raw_dir: Path = DEFAULT_RAW_DIR,
    *,
    ref: str = "master",
    paths: list[str] | None = None,
    max_bytes: int = ASK_BEFORE_BYTES,
) -> Path:
    """Download the ESHM20 main-region OpenQuake inputs at a pinned commit; write ``manifest.json``.

    Sizes are checked through the files API *before* any model bytes are fetched; if the total
    would exceed ``max_bytes`` (5 GB, the ask-before rule) the function raises instead of
    downloading. Returns the manifest path.
    """
    commit = resolve_commit(ref)
    blobs = (
        [p for p in paths]
        if paths is not None
        else [t["path"] for t in list_tree(MAIN_REGION_DIR, ref=commit) if t["type"] == "blob"]
    )
    infos = {p: file_info(p, ref=commit) for p in blobs}
    total = sum(int(i["size"]) for i in infos.values())
    if total > max_bytes:
        msg = f"ESHM20 selection is {total} bytes > {max_bytes}: ask before downloading"
        raise RuntimeError(msg)
    licence_text = fetch_raw(LICENCE_FILE, ref=commit).decode("utf-8", errors="replace")
    raw_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for p in blobs:
        content = fetch_raw(p, ref=commit)
        digest = sha256_hex(content)
        if int(infos[p]["size"]) != len(content):
            msg = f"{p}: size {len(content)} != API size {infos[p]['size']}"
            raise RuntimeError(msg)
        dest = raw_dir / p
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        files.append(
            {
                "path": p,
                "source_url": f"{PROJECT_URL}/-/raw/{commit}/{p}",
                "local_path": str(dest.relative_to(raw_dir)),
                "size": len(content),
                "sha256": digest,
                "blob_id": infos[p]["blob_id"],
                "retrieved_at": utc_now().isoformat(),
            }
        )
    manifest = {
        "source": SOURCE_ID,
        "repository": PROJECT_URL,
        "ref": ref,
        "commit": commit,
        "directory": MAIN_REGION_DIR,
        "source_model_logic_tree": SOURCE_MODEL_LOGIC_TREE,
        "gsim_logic_tree": GSIM_LOGIC_TREE,
        "licence": LICENCE_SPDX,
        "licence_file": LICENCE_FILE,
        "licence_text": licence_text,
        "citation": CITATION,
        "adapter_version": ADAPTER_VERSION,
        "total_bytes": total,
        "files": files,
    }
    manifest_path = raw_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest_path


def model_present(raw_dir: Path = DEFAULT_RAW_DIR) -> bool:
    """True when the manifest and both logic-tree files it names are on disk.

    A committed ``manifest.json`` next to no model files is the normal state of a fresh clone, so
    "the manifest exists" must never be read as "the model is here".
    """
    path = Path(raw_dir) / "manifest.json"
    if not path.is_file():
        return False
    try:
        manifest = read_manifest(raw_dir)
    except (OSError, ValueError):  # pragma: no cover - unreadable manifest
        return False
    return all(
        (Path(raw_dir) / str(manifest[key])).is_file()
        for key in ("source_model_logic_tree", "gsim_logic_tree")
    )


def read_manifest(raw_dir: Path = DEFAULT_RAW_DIR) -> dict[str, Any]:
    path = raw_dir / "manifest.json"
    if not path.exists():
        msg = f"{path} not found; run fetch_eshm20() (network) first"
        raise FileNotFoundError(msg)
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def verify_manifest(raw_dir: Path = DEFAULT_RAW_DIR) -> list[str]:
    """Return the list of files whose sha256 no longer matches the manifest (empty = all good)."""
    manifest = read_manifest(raw_dir)
    bad: list[str] = []
    for f in manifest["files"]:
        p = raw_dir / f["local_path"]
        if not p.exists() or sha256_hex(p.read_bytes()) != f["sha256"]:
            bad.append(f["path"])
    return bad
