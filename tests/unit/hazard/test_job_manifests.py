"""Every infra/jobs/*.yaml validates against infra/jobs/schema.json and matches the CLI verbs.

``yaml`` (pyyaml) is declared in pyproject on main; this worktree may only have it transitively,
so the module is imported with ``importorskip`` and the tests activate wherever it is present.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import jsonschema
import pytest

from rupture.pipelines.hazard import load_classical_job
from tests.unit.hazard.conftest import REPO_ROOT

yaml = pytest.importorskip("yaml")

JOBS = REPO_ROOT / "infra" / "jobs"
MANIFESTS = sorted(JOBS.glob("*.yaml"))
EXPECTED = {"build-catalog", "fit-etas", "issue-forecast", "evaluate-schedule", "oq-classical"}
# The verbs CLAUDE.md assigns; the manifests must invoke exactly these.
VERB_PREFIX = {
    "build-catalog": ["rupture", "catalog", "build", "--region"],
    "fit-etas": ["rupture", "forecast", "fit", "--model", "etas", "--region"],
    "issue-forecast": ["rupture", "forecast", "issue", "--model", "etas", "--region"],
    "evaluate-schedule": ["rupture", "evaluate", "schedule", "--region"],
    "oq-classical": ["rupture", "hazard", "classical", "--job"],
}


def _schema() -> dict[str, object]:
    schema: dict[str, object] = json.loads((JOBS / "schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


def _env_names() -> set[str]:
    names = set()
    for line in (REPO_ROOT / ".env.example").read_text().splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if m:
            names.add(m.group(1))
    return names


def test_the_five_manifests_exist() -> None:
    assert {p.stem for p in MANIFESTS} == EXPECTED


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.stem)
def test_manifest_validates_and_matches_conventions(path: Path) -> None:
    manifest = yaml.safe_load(path.read_text())
    jsonschema.validate(manifest, _schema())
    assert manifest["name"] == path.stem
    prefix = VERB_PREFIX[path.stem]
    assert manifest["command"][: len(prefix)] == prefix, manifest["command"]
    assert set(manifest["env"]) <= _env_names(), "env names must come from .env.example"
    for artifact in (*manifest["inputs"], *manifest["outputs"]):
        assert artifact["remote"].endswith(artifact["path"]), "remote mirrors the repo path"
    assert manifest["aws"]["batch"]["vcpus"] >= manifest["resources"]["cpu"]
    assert (
        manifest["aws"]["batch"]["timeout_seconds"] == manifest["resources"]["timeout_minutes"] * 60
    )
    text = path.read_text()
    assert "AKIA" not in text, "manifests never carry credentials"
    assert "secret" not in text.lower(), "manifests never carry credentials"


def test_oq_classical_needs_the_docker_socket_and_others_do_not() -> None:
    for path in MANIFESTS:
        manifest = yaml.safe_load(path.read_text())
        wants_socket = manifest["resources"].get("docker_socket", False)
        assert wants_socket == (path.stem == "oq-classical"), path.stem
        if wants_socket:
            assert manifest["aws"]["service"] == "batch-ec2", "Fargate has no docker socket"


def test_turkiye_eaf_example_is_a_valid_classical_job_with_a_0p2_degree_grid() -> None:
    example = JOBS / "examples" / "turkiye-eaf-classical.json"
    job = load_classical_job(example)
    assert job.investigation_time_years == 50.0
    assert job.region_grid_spacing_km == 20.0, "about 0.2 degrees at these latitudes"
    assert job.region_wkt is not None
    assert job.region_wkt.startswith("POLYGON((35.5 35.5")
    assert job.source_model_logic_tree.is_absolute()
    assert "data/raw/oq_sources/eshm20" in job.source_model_logic_tree.as_posix()
    assert "NOT RUN" in job.description
