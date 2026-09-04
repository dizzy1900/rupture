"""The GSIMs rupture actually ships, and the verification tables that earn each its place.

A name appears here only when a test reproduces OpenQuake's committed expected values for it
(ADR-0020). Adding an entry without its tables is the failure mode this registry exists to make
visible: :func:`verification_tables` is what both the unit tests and ``validate-risk`` iterate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rupture.adapters.groundmotion import verification
from rupture.adapters.groundmotion.base import Gsim
from rupture.adapters.groundmotion.bchydro import AbrahamsonEtAl2015SInter
from rupture.adapters.groundmotion.bssa14 import (
    BooreEtAl2014,
    BooreEtAl2014HighQ,
    BooreEtAl2014LowQ,
)

FIXTURE_REL = Path("tests") / "fixtures" / "risk" / "gsim"


class UnknownGsimError(KeyError):
    """The requested GSIM is not one rupture has verified and shipped."""


@dataclass(frozen=True, slots=True)
class GsimEntry:
    """One shipped GSIM: how to build it, where its reference tables are, what it must achieve."""

    name: str
    build: Callable[[], Gsim]
    directory: str
    tables: dict[str, str]
    mean_tolerance_percent: float
    stddev_tolerance_percent: float
    notes: str = ""


def _bssa14() -> Gsim:
    return BooreEtAl2014()


def _bssa14_no_sof() -> Gsim:
    return BooreEtAl2014(sof=False)


def _bssa14_high_q() -> Gsim:
    return BooreEtAl2014HighQ()


def _bssa14_low_q() -> Gsim:
    return BooreEtAl2014LowQ()


def _bchydro_sinter() -> Gsim:
    return AbrahamsonEtAl2015SInter()


ENTRIES: tuple[GsimEntry, ...] = (
    GsimEntry(
        name="BooreEtAl2014",
        build=_bssa14,
        directory="bssa14",
        tables={
            verification.MEAN: "BSSA_2014_MEAN.csv",
            verification.TOTAL: "BSSA_2014_TOTAL_STD.csv",
            verification.INTER: "BSSA_2014_INTER_STD.csv",
            verification.INTRA: "BSSA_2014_INTRA_STD.csv",
        },
        # The reference table lists three periods (0.21 s, 0.23 s, 4.5 s) that the committed
        # coefficient table does not, so their coefficients are interpolated in log period.
        # OpenQuake carries the same discrepancy and sets its own tolerance at 2 %; at the
        # tabulated periods rupture agrees to better than 0.01 %. docs/RISK.md has the split.
        mean_tolerance_percent=2.0,
        stddev_tolerance_percent=0.1,
        notes="global Q, no basin term, style of faulting from rake",
    ),
    GsimEntry(
        name="BooreEtAl2014(sof=False)",
        build=_bssa14_no_sof,
        directory="bssa14",
        tables={
            verification.MEAN: "BSSA_2014_NOSOF_MEAN.csv",
            verification.TOTAL: "BSSA_2014_NOSOF_TOTAL_STD.csv",
            verification.INTER: "BSSA_2014_NOSOF_INTER_STD.csv",
            verification.INTRA: "BSSA_2014_NOSOF_INTRA_STD.csv",
        },
        mean_tolerance_percent=2.0,
        stddev_tolerance_percent=0.1,
        notes="unspecified mechanism (e0)",
    ),
    GsimEntry(
        name="BooreEtAl2014HighQ",
        build=_bssa14_high_q,
        directory="bssa14",
        tables={
            verification.MEAN: "BSSA_2014_HIGHQ_MEAN.csv",
            verification.TOTAL: "BSSA_2014_HIGHQ_TOTAL_STD.csv",
            verification.INTER: "BSSA_2014_HIGHQ_INTER_STD.csv",
            verification.INTRA: "BSSA_2014_HIGHQ_INTRA_STD.csv",
        },
        mean_tolerance_percent=2.0,
        stddev_tolerance_percent=0.1,
        notes="high-Q anelastic attenuation (China, Turkey); a branch of the GSIM logic tree",
    ),
    GsimEntry(
        name="BooreEtAl2014LowQ",
        build=_bssa14_low_q,
        directory="bssa14",
        tables={
            verification.MEAN: "BSSA_2014_LOWQ_MEAN.csv",
            verification.TOTAL: "BSSA_2014_LOWQ_TOTAL_STD.csv",
            verification.INTER: "BSSA_2014_LOWQ_INTER_STD.csv",
            verification.INTRA: "BSSA_2014_LOWQ_INTRA_STD.csv",
        },
        mean_tolerance_percent=2.0,
        stddev_tolerance_percent=0.1,
        notes="low-Q anelastic attenuation (Italy, Japan); a branch of the GSIM logic tree",
    ),
    GsimEntry(
        name="AbrahamsonEtAl2015SInter",
        build=_bchydro_sinter,
        directory="bchydro_sinter",
        tables={
            verification.MEAN: "BCHYDRO_SINTER_CENTRAL_MEAN.csv",
            verification.TOTAL: "BCHYDRO_SINTER_CENTRAL_STDDEV_TOTAL.csv",
            verification.INTER: "BCHYDRO_SINTER_CENTRAL_STDDEV_INTER.csv",
            verification.INTRA: "BCHYDRO_SINTER_CENTRAL_STDDEV_INTRA.csv",
        },
        mean_tolerance_percent=0.01,
        stddev_tolerance_percent=0.01,
        notes="subduction interface, central DeltaC1, ergodic sigma",
    ),
)

BY_NAME: dict[str, GsimEntry] = {entry.name: entry for entry in ENTRIES}


def build(name: str) -> Gsim:
    """The GSIM registered under ``name``."""
    try:
        entry = BY_NAME[name]
    except KeyError as exc:
        known = ", ".join(sorted(BY_NAME))
        msg = f"unknown GSIM {name!r}; rupture ships {known}"
        raise UnknownGsimError(msg) from exc
    return entry.build()


def names() -> tuple[str, ...]:
    return tuple(sorted(BY_NAME))


def fixture_root(repo_root: Path) -> Path:
    return repo_root / FIXTURE_REL


def verification_tables(entry: GsimEntry, repo_root: Path) -> dict[str, Path]:
    """Absolute paths of ``entry``'s expected-value tables under the repository root."""
    directory = fixture_root(repo_root) / entry.directory
    return {result_type: directory / name for result_type, name in entry.tables.items()}
