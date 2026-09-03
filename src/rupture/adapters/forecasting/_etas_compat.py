"""Import shim for ``etas.simulation`` at the pinned commit (ADR-0009, ADR-0018).

At commit ``097f08b6`` the module ``etas/simulation.py`` does ``from seismostats import
ForecastCatalog`` at import time, but ``seismostats`` is declared only in the package's optional
``hermes`` extra, which rupture does not install. The name is used solely as the return type of
``ETASSimulation.simulate_to_df``, which rupture never calls (it drives
``simulate_catalog_continuation`` directly so it can control the random seed, see ADR-0018).

If ``seismostats`` is importable we do nothing. Otherwise we register a minimal stand-in module
whose ``ForecastCatalog`` refuses to be instantiated, so nothing can silently depend on it. The
clean fix is upstream (guarding the import) or adding ``seismostats`` to ``pyproject.toml``;
either is an architect decision and this shim is the documented interim.
"""

from __future__ import annotations

import importlib
import sys
import types
from typing import Any


class _UnavailableForecastCatalog:
    """Placeholder for ``seismostats.ForecastCatalog``; rupture never constructs one."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        msg = (
            "seismostats.ForecastCatalog is not installed; rupture does not use "
            "ETASSimulation.simulate_to_df (see rupture.adapters.forecasting._etas_compat)"
        )
        raise ModuleNotFoundError(msg)


def etas_simulation() -> Any:
    """Return the ``etas.simulation`` module, installing the shim first if needed."""
    if "seismostats" not in sys.modules:
        try:
            importlib.import_module("seismostats")
        except ModuleNotFoundError:
            shim = types.ModuleType("seismostats")
            shim.ForecastCatalog = _UnavailableForecastCatalog  # type: ignore[attr-defined]
            shim.__doc__ = "rupture stand-in for the optional seismostats dependency of etas"
            sys.modules["seismostats"] = shim
    return importlib.import_module("etas.simulation")
