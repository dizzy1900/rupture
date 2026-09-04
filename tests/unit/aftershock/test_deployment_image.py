"""The image can actually serve the service it claims to package.

There is no Docker on the development machine, so **none of this builds or runs an image** — a
build-and-curl smoke test belongs in CI and is named as missing in ``docs/DEPLOYMENT.md``. What
these tests do check is the part that was silently wrong and would stay wrong until someone tried
a deployment: the image had no port and no server command, and its build context excluded the
committed inputs the risk and aftershock surfaces read, so every request in the container would
have failed on a missing file.

So: the runtime paths the code reads are asserted against the Dockerfile's ``COPY`` lines and the
context's ignore file, and the served module path is asserted by importing it.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
import yaml

from rupture.adapters.exposure.serac_export import FALLBACK_REL
from rupture.adapters.groundmotion.registry import FIXTURE_REL as GSIM_FIXTURE_REL
from rupture.risk.scenarios import FIXTURE_REL as SCENARIO_FIXTURE_REL
from rupture.services.aftershock.sequences import FIXTURE_REL as SEQUENCE_FIXTURE_REL

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "infra" / "docker" / "Dockerfile"
DOCKERIGNORE = REPO_ROOT / "infra" / "docker" / "Dockerfile.dockerignore"
COMPOSE = REPO_ROOT / "infra" / "docker" / "compose.yml"
SERVED = "rupture.services.app:create_app"
RUNTIME_INPUTS = (
    SCENARIO_FIXTURE_REL,
    FALLBACK_REL,
    GSIM_FIXTURE_REL,
    SEQUENCE_FIXTURE_REL,
)


@pytest.fixture(scope="module")
def dockerfile() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


def test_the_served_application_factory_exists(dockerfile: str) -> None:
    """The CMD names a module and a callable; both are imported here rather than assumed."""
    assert SERVED in dockerfile
    module_name, _, attribute = SERVED.partition(":")
    module = importlib.import_module(module_name)
    assert callable(getattr(module, attribute))


def test_the_api_target_publishes_a_port_and_runs_uvicorn(dockerfile: str) -> None:
    api = dockerfile.split("FROM runtime AS api", 1)
    assert len(api) == 2, "the Dockerfile has no `api` target"
    body = api[1]
    assert "EXPOSE 8000" in body
    assert re.search(r'CMD \["uvicorn", "rupture\.services\.app:create_app", "--factory"', body)
    assert "--port" in body
    assert '"8000"' in body
    assert "HEALTHCHECK" in body


def test_the_image_serves_one_worker_because_the_grid_cache_is_in_process(
    dockerfile: str,
) -> None:
    """More than one worker and GET /aftershock/grid/{id} would 404 at random (see grids.py)."""
    assert '"--workers", "1"' in dockerfile


def _copied_prefix(relative: Path, dockerfile: str) -> str | None:
    """The COPY line covering ``relative``: itself or one of its parent directories."""
    candidates = [relative, *relative.parents]
    for candidate in candidates:
        inside = candidate.as_posix()
        if inside in {".", "/"}:
            continue
        if any(
            line.strip().startswith("COPY")
            and f" {inside}/ " in line
            and f" /app/{inside}/" in line
            for line in dockerfile.splitlines()
        ):
            return inside
    return None


@pytest.mark.parametrize("relative", RUNTIME_INPUTS, ids=str)
def test_every_runtime_input_the_code_reads_is_copied_into_the_image(
    relative: Path, dockerfile: str
) -> None:
    """A path the service reads at run time but the image does not carry is a 500 per request."""
    assert _copied_prefix(relative, dockerfile) is not None, (
        f"{relative} is read at run time but neither it nor a parent is COPYed into the image"
    )


@pytest.mark.parametrize("relative", RUNTIME_INPUTS, ids=str)
def test_the_build_context_is_not_excluding_those_inputs(relative: Path, dockerfile: str) -> None:
    """`*` excludes everything; the copied directory needs its parents walked back in."""
    lines = [
        line.strip()
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    copied = _copied_prefix(relative, dockerfile)
    assert copied is not None
    parts = copied.split("/")
    for depth in range(1, len(parts) + 1):
        prefix = "/".join(parts[:depth])
        assert any(line in {f"!{prefix}", f"!{prefix}/"} for line in lines), (
            f"{prefix} is excluded from the build context, so COPY of {copied} would fail"
        )


def test_the_repo_root_the_service_reads_is_set_in_the_image(dockerfile: str) -> None:
    assert "RUPTURE_REPO_ROOT=/app" in dockerfile


def test_compose_can_bring_the_service_up_with_a_key(dockerfile: str) -> None:
    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    api = compose["services"]["api"]
    assert api["build"]["target"] == "api"
    assert api["ports"] == ["127.0.0.1:8000:8000"]
    assert "RUPTURE_API_KEYS" in api["environment"]
    # no default key: an unconfigured service refuses rather than serving open
    assert api["environment"]["RUPTURE_API_KEYS"] == "${RUPTURE_API_KEYS:-}"
