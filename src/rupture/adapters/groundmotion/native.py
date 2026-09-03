"""``native_gsim``: scenario ground-motion fields without the OpenQuake container (ADR-0020).

This adapter evaluates a shipped, verified GSIM directly. It is not a re-implementation of the
engine and does not pretend to be one: it does one calculation — a scenario field for a single
rupture at a fixed set of sites — and it records that it, not the engine, produced the numbers.

Sampling follows the scenario calculator's structure: one inter-event residual per realisation,
shared by every site, and one intra-event residual per site per realisation, both drawn from a
normal truncated at ``truncation_level`` standard deviations. Spatial correlation of the
intra-event residual is **not** modelled (OpenQuake's default is likewise no correlation model);
``docs/RISK.md`` records what that costs a portfolio interval.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

from rupture import __version__
from rupture.adapters.groundmotion import distances as geo
from rupture.adapters.groundmotion import imt as imt_module
from rupture.adapters.groundmotion import registry
from rupture.adapters.groundmotion.base import GsimContext
from rupture.domain.common import Provenance, sha256_hex, utc_now
from rupture.domain.groundmotion import GroundMotionEngineId, GroundMotionField, Site
from rupture.domain.hazard import ScenarioRupture

ADAPTER_VERSION = __version__
LICENCE = "Apache-2.0 (rupture); GSIM coefficients per docs/RISK.md"


class NativeGsimError(ValueError):
    """The native engine cannot produce this field."""


class NativeGsimEngine:
    """The ``GroundMotionEngine`` port, evaluated in-process from verified GSIMs."""

    engine_id = GroundMotionEngineId.NATIVE_GSIM.value
    engine_version = ADAPTER_VERSION

    def __init__(self, *, strict_tectonic_region: bool = True) -> None:
        self.strict_tectonic_region = strict_tectonic_region
        """When False, a GSIM may be applied outside its tectonic region; the field says so."""

    def available(self) -> tuple[bool, str]:
        """Always available: it is pure Python and the coefficient tables ship with the package."""
        return True, ""

    def supported_gsims(self) -> tuple[str, ...]:
        return registry.names()

    def scenario(
        self,
        rupture: ScenarioRupture,
        sites: tuple[Site, ...],
        *,
        imt: str = "PGA",
        gsim: str,
        n_realisations: int = 1,
        truncation_level: float = 3.0,
        seed: int | None = None,
    ) -> GroundMotionField:
        if n_realisations < 1:
            msg = "n_realisations must be at least 1"
            raise NativeGsimError(msg)
        if truncation_level < 0.0:
            msg = "truncation_level must be non-negative"
            raise NativeGsimError(msg)
        model = registry.build(gsim)
        measure = imt_module.parse(imt)
        if not model.supports(measure):
            msg = f"{gsim} is not defined for {measure}"
            raise NativeGsimError(msg)

        note = self._tectonic_note(rupture, model.tectonic_region, gsim)
        ctx = self.context(rupture, sites)
        result = model.compute(ctx, measure)
        values = self._sample(
            result.mean_ln,
            result.tau,
            result.phi,
            n_realisations=n_realisations,
            truncation_level=truncation_level,
            seed=seed,
        )
        computed_at = utc_now()
        field_id = _field_id(rupture.id, gsim, str(measure), n_realisations, seed)
        return GroundMotionField(
            id=field_id,
            scenario_id=rupture.id,
            imt=str(measure),
            sites=sites,
            values=tuple(tuple(float(v) for v in row) for row in values),
            engine=GroundMotionEngineId.NATIVE_GSIM,
            engine_version=self.engine_version,
            gsim=gsim,
            rupture_id=rupture.id,
            truncation_level=truncation_level,
            random_seed=seed,
            computed_at=computed_at,
            provenance=Provenance(
                source=self.engine_id,
                source_url=None,
                retrieved_at=computed_at,
                sha256=sha256_hex(rupture.canonical_json() + "|" + field_id),
                licence=LICENCE,
                adapter_version=ADAPTER_VERSION,
                notes=(
                    f"{model.reference}; verified against OpenQuake expected values (ADR-0020). "
                ),
            ),
            notes=note,
        )

    def context(self, rupture: ScenarioRupture, sites: tuple[Site, ...]) -> GsimContext:
        """The GSIM context for one rupture and a set of sites, with distances derived."""
        d = geo.distances(rupture, sites)
        vs30 = np.array([s.vs30 for s in sites], dtype=np.float64)
        z1pt0 = (
            np.array([s.z1pt0 for s in sites], dtype=np.float64)
            if all(s.z1pt0 is not None for s in sites)
            else None
        )
        return GsimContext(
            mag=rupture.magnitude,
            rake=rupture.rake,
            hypo_depth=rupture.hypocentre_depth_km,
            ztor=d.ztor,
            rjb=d.rjb,
            rrup=d.rrup,
            rx=d.rx,
            rhypo=d.rhypo,
            vs30=vs30,
            backarc=np.zeros_like(vs30, dtype=np.bool_),
            z1pt0=z1pt0,
        )

    def _tectonic_note(self, rupture: ScenarioRupture, gsim_trt: str, gsim: str) -> str | None:
        if rupture.tectonic_region.strip().lower() == gsim_trt.strip().lower():
            return None
        message = (
            f"{gsim} is defined for '{gsim_trt}' but the rupture is '{rupture.tectonic_region}'"
        )
        if self.strict_tectonic_region:
            msg = message + "; construct NativeGsimEngine(strict_tectonic_region=False) with a "
            raise NativeGsimError(msg + "documented justification to allow it")
        return message + " (allowed deliberately; see docs/RISK.md)"

    @staticmethod
    def _sample(
        mean_ln: np.ndarray,
        tau: np.ndarray,
        phi: np.ndarray,
        *,
        n_realisations: int,
        truncation_level: float,
        seed: int | None,
    ) -> np.ndarray:
        median = np.exp(mean_ln)[None, :]
        if n_realisations == 1 or truncation_level == 0.0:
            return np.repeat(median, n_realisations, axis=0)
        rng = np.random.default_rng(seed)
        truncated = stats.truncnorm(-truncation_level, truncation_level)
        between = truncated.rvs(size=(n_realisations, 1), random_state=rng)
        within = truncated.rvs(size=(n_realisations, mean_ln.size), random_state=rng)
        sampled: np.ndarray = np.exp(
            mean_ln[None, :] + tau[None, :] * between + phi[None, :] * within
        )
        return sampled


def _field_id(scenario_id: str, gsim: str, imt: str, n: int, seed: int | None) -> str:
    tail = "" if seed is None else f"-s{seed}"
    slug = f"{gsim}-{imt}".replace("(", "").replace(")", "").replace(".", "p").lower()
    return f"{scenario_id}-{slug}-n{n}{tail}"
