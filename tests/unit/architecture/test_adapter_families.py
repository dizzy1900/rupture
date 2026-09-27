"""The independence contract must name every adapters.* family that exists on disk.

ADR-0002 listed five families. ADR-0071 extends the list to all ten packages under
``src/rupture/adapters/``. A new family that lands without being added to
``pyproject.toml`` would otherwise sit outside the contract, which is how the last five
arrived. This test is the second ratchet: ``lint-imports`` catches a new *edge*; this
catches a new *package*.
"""

from __future__ import annotations

import pkgutil
import tomllib
from pathlib import Path
from typing import Any, Final

import rupture.adapters

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]


def _edge(importer: str, imported: str) -> str:
    return f"{importer} -> {imported}"


# The six edges that already crossed family lines when ADR-0071 was written. A seventh
# cannot be added by editing only the adapter; it has to change this set and pyproject.toml.
GRANDFATHERED_ADAPTER_EDGES: Final[frozenset[str]] = frozenset(
    {
        _edge(
            "rupture.adapters.groundmotion.openquake_scenario",
            "rupture.adapters.hazard.job_builder",
        ),
        _edge(
            "rupture.adapters.groundmotion.openquake_scenario",
            "rupture.adapters.hazard.openquake_docker",
        ),
        _edge(
            "rupture.adapters.groundmotion.openquake_event_based",
            "rupture.adapters.hazard.job_builder",
        ),
        _edge(
            "rupture.adapters.groundmotion.openquake_event_based",
            "rupture.adapters.hazard.openquake_docker",
        ),
        _edge(
            "rupture.adapters.cascade.chamoli",
            "rupture.adapters.groundmotion.distances",
        ),
        _edge(
            "rupture.adapters.cascade.chamoli",
            "rupture.adapters.groundmotion.native",
        ),
    }
)

REQUIRED_REPORTING_FORBIDDEN: Final[frozenset[str]] = frozenset(
    {
        "rupture.adapters",
        "rupture.pipelines",
        "rupture.cli",
        "rupture.validation",
        "rupture.services",
    }
)


def _contracts() -> list[dict[str, Any]]:
    with (REPO_ROOT / "pyproject.toml").open("rb") as handle:
        parsed = tomllib.load(handle)
    contracts = parsed["tool"]["importlinter"]["contracts"]
    assert isinstance(contracts, list)
    return contracts


def _contract_named(name: str) -> dict[str, Any]:
    matches = [c for c in _contracts() if c.get("name") == name]
    assert len(matches) == 1, f"expected one contract named {name!r}, found {len(matches)}"
    return matches[0]


def test_every_adapter_family_on_disk_is_in_the_independence_contract() -> None:
    """A new adapters.* package that is not listed is a silent hole in the contract."""
    listed = {
        module.removeprefix("rupture.adapters.")
        for module in _contract_named("adapters do not import each other across families")[
            "modules"
        ]
    }
    on_disk = {info.name for info in pkgutil.iter_modules(rupture.adapters.__path__) if info.ispkg}
    assert listed == on_disk, (
        f"adapter families on disk {sorted(on_disk)} must match the independence contract "
        f"{sorted(listed)}; add the new family to [tool.importlinter] (ADR-0071)"
    )


def test_cross_family_adapter_ignores_are_exactly_the_grandfathered_edges() -> None:
    """A new ignore is a new exception and has to be named here, not only in pyproject.toml."""
    ignores = _contract_named("adapters do not import each other across families").get(
        "ignore_imports", []
    )
    assert frozenset(ignores) == GRANDFATHERED_ADAPTER_EDGES


def test_reporting_is_forbidden_from_outer_layers_and_is_clean() -> None:
    """ADR-0049's reporting package had no contract; ADR-0071 adds one with nothing to ignore."""
    contract = _contract_named(
        "reporting imports only domain (figures are drawn from committed evidence)"
    )
    assert contract["type"] == "forbidden"
    assert contract["source_modules"] == ["rupture.reporting"]
    forbidden = set(contract["forbidden_modules"])
    assert forbidden >= REQUIRED_REPORTING_FORBIDDEN
    assert "ignore_imports" not in contract
