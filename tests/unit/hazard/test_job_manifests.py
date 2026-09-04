"""Every infra/jobs/*.yaml validates against infra/jobs/schema.json and matches the CLI verbs."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import jsonschema
import pytest
import typer.main
import yaml

from rupture.cli import app as cli_app
from rupture.pipelines.hazard import load_classical_job
from tests.unit.hazard.conftest import REPO_ROOT

JOBS = REPO_ROOT / "infra" / "jobs"
MANIFESTS = sorted(JOBS.glob("*.yaml"))
EXPECTED = {
    # Prompt 1: the catalogue, the ETAS baseline and the hazard engine.
    "build-catalog",
    "fit-etas",
    "issue-forecast",
    "evaluate-schedule",
    "oq-classical",
    # Prompt 2: full training of the learned challengers, and the event set that feeds loss.
    "select-ntpp",
    "train-ntpp",
    "run-ensemble-protocol",
    "stochastic-event-set",
}
# The verbs the manifests must invoke. A `rupture ...` prefix is a mounted CLI verb; a
# `python -m rupture....` prefix is an entry point src/rupture/cli.py has not mounted yet.
VERB_PREFIX = {
    "build-catalog": ["rupture", "catalog", "build", "--region"],
    "fit-etas": ["rupture", "forecast", "fit", "--model", "etas", "--region"],
    "issue-forecast": ["rupture", "forecast", "issue", "--model", "etas", "--region"],
    "evaluate-schedule": ["rupture", "evaluate", "schedule", "--region"],
    "oq-classical": ["rupture", "hazard", "classical", "--job"],
    "select-ntpp": ["python", "-m", "rupture.commands.challenger", "ntpp", "select", "--region"],
    "train-ntpp": ["python", "-m", "rupture.commands.challenger", "ntpp", "fit", "--region"],
    "run-ensemble-protocol": [
        "python",
        "-m",
        "rupture.models.ensemble.protocol_runner",
        "--region",
    ],
    "stochastic-event-set": ["rupture", "forecast", "simulate", "--model", "etas", "--region"],
}
# Paths a core-hour note may cite as its basis. A measured or extrapolated estimate must point at
# one of these; a guess must not pretend to.
CITABLE_BASIS = ("reports/", "tests/fixtures/", "baselines/")


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


def _load(path: Path) -> dict[str, object]:
    manifest: dict[str, object] = yaml.safe_load(path.read_text())
    return manifest


def _entry_point_exists(command: list[str]) -> bool:
    """True when the manifest's argv names something that exists in this tree today."""
    if command[0] == "python":
        return importlib.util.find_spec(command[2]) is not None
    # Duck-typed on ``.commands`` rather than ``isinstance(node, click.Group)``: typer's
    # ``TyperGroup`` is not a subclass of the ``click.Group`` this click exposes.
    node: object = typer.main.get_command(cli_app)
    for token in command[1:]:
        if token.startswith("-"):
            break
        children = getattr(node, "commands", None)
        if not isinstance(children, dict) or token not in children:
            return False
        node = children[token]
    return True


def test_the_manifests_exist() -> None:
    assert {p.stem for p in MANIFESTS} == EXPECTED


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.stem)
def test_manifest_validates_and_matches_conventions(path: Path) -> None:
    manifest = _load(path)
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


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.stem)
def test_every_manifest_states_what_one_run_costs(path: Path) -> None:
    """The compute-discipline rule: a manifest is not launchable until its cost is on the record.

    The schema makes the three fields required; this asserts they mean something. The estimate is
    CPU-core-hours for one invocation, so it can never exceed the ceiling the sizing implies, and
    an estimate that claims to be measured or extrapolated has to name the file it came from.
    """
    resources = _load(path)["resources"]
    estimate = resources["core_hours_estimate"]
    ceiling = resources["cpu"] * resources["timeout_minutes"] / 60
    assert 0 < estimate <= ceiling, f"{estimate} core-hours exceeds the {ceiling} ceiling"
    note = resources["core_hours_note"]
    assert resources["core_hours_basis"] in {"measured", "extrapolated", "guess"}
    if resources["core_hours_basis"] in {"measured", "extrapolated"}:
        assert any(token in note for token in CITABLE_BASIS), (
            "a measured or extrapolated estimate names the run it came from"
        )
    else:
        assert "uess" in note, "a guess says in its note that it is one"


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda p: p.stem)
def test_status_matches_whether_the_entry_point_exists(path: Path) -> None:
    """`command-not-implemented` is a claim about this tree, so it is checked against it.

    A manifest may be committed for a job nobody has run — oq-classical and stochastic-event-set
    both are — but it may not quietly name an entry point that does not exist. When the missing
    verb lands, this test fails until the status is corrected.
    """
    manifest = _load(path)
    exists = _entry_point_exists(manifest["command"])
    assert (manifest["status"] == "command-not-implemented") is not exists, (
        f"{path.stem}: status {manifest['status']!r} but entry point exists={exists}"
    )


def test_oq_classical_needs_the_docker_socket_and_others_do_not() -> None:
    for path in MANIFESTS:
        manifest = _load(path)
        wants_socket = manifest["resources"].get("docker_socket", False)
        assert wants_socket == (path.stem == "oq-classical"), path.stem
        if wants_socket:
            assert manifest["aws"]["service"] == "batch-ec2", "Fargate has no docker socket"


def test_the_learned_challengers_and_the_event_set_are_all_sized() -> None:
    """The brief's compute discipline, spelled out: these four jobs must exist and carry a cost."""
    required = {"select-ntpp", "train-ntpp", "run-ensemble-protocol", "stochastic-event-set"}
    sized = {
        p.stem: _load(p)["resources"]["core_hours_estimate"]
        for p in MANIFESTS
        if p.stem in required
    }
    assert set(sized) == required
    assert all(v > 0 for v in sized.values()), sized


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
