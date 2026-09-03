"""Every shipped GSIM must reproduce OpenQuake's own committed expected values (ADR-0020).

This is the test that earns a GSIM its place in the registry. It is not a smoke test: it runs the
implementation over all ~17 500 (BSSA14) and ~5 600 (BC Hydro) reference values per result type
and asserts the worst relative disagreement.

What the numbers mean, recorded here because ``docs/RISK.md`` quotes them:

* **BC Hydro (AbrahamsonEtAl2015SInter)** — means agree to better than 1e-6 %, and the three
  standard deviations are exact, because the reference table was generated from the same
  equations and every period it lists is a row of the coefficient table.
* **BSSA14 (BooreEtAl2014)** — at the 36 intensity measures whose coefficients are tabulated,
  means agree to better than 0.01 % and the standard deviations to better than 0.02 %. At
  SA(0.21), SA(0.23) and SA(4.5), which the committed coefficient table does not list, the
  coefficients must be interpolated in log period and the disagreement with Boore's Fortran
  reference reaches 1.8 %. OpenQuake carries the same disagreement and sets its own tolerance at
  2 %; the split below records which is which rather than hiding the larger number behind the
  smaller.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from rupture.adapters.groundmotion import coeffs, registry, verification
from rupture.adapters.groundmotion.imt import Imt
from tests.unit.risk.conftest import GSIM_FIXTURES, REPO_ROOT

BSSA_INTERPOLATED = (Imt("SA", 0.21), Imt("SA", 0.23), Imt("SA", 4.5))
BSSA_TABULATED_MEAN_TOLERANCE = 0.01
BSSA_TABULATED_STDDEV_TOLERANCE = 0.02


@pytest.mark.parametrize("entry", registry.ENTRIES, ids=lambda e: e.name)
def test_gsim_reproduces_openquake_expected_values(entry: registry.GsimEntry) -> None:
    tables = registry.verification_tables(entry, REPO_ROOT)
    for path in tables.values():
        assert path.is_file(), f"missing verification table {path}"
    report = verification.verify(entry.build(), tables)
    assert report.comparisons > 1000, report.lines()
    assert report.worst(verification.MEAN) <= entry.mean_tolerance_percent, "\n".join(
        report.lines()
    )
    for result_type in (verification.TOTAL, verification.INTER, verification.INTRA):
        if result_type in tables:
            assert report.worst(result_type) <= entry.stddev_tolerance_percent, "\n".join(
                report.lines()
            )


def test_bssa14_is_far_tighter_at_tabulated_periods() -> None:
    """Separate the interpolation error from the implementation error, and name both."""
    entry = registry.BY_NAME["BooreEtAl2014"]
    tables = registry.verification_tables(entry, REPO_ROOT)
    table = verification.VerificationTable.read(tables[verification.MEAN])
    tabulated = tuple(imt for imt in table.imts if imt not in BSSA_INTERPOLATED)
    assert set(BSSA_INTERPOLATED).issubset(set(table.imts))

    tight = verification.verify(entry.build(), tables, imts=tabulated)
    assert tight.worst(verification.MEAN) <= BSSA_TABULATED_MEAN_TOLERANCE, "\n".join(tight.lines())
    for result_type in (verification.TOTAL, verification.INTER, verification.INTRA):
        assert tight.worst(result_type) <= BSSA_TABULATED_STDDEV_TOLERANCE, "\n".join(tight.lines())

    loose = verification.verify(
        entry.build(), {verification.MEAN: tables[verification.MEAN]}, imts=BSSA_INTERPOLATED
    )
    assert loose.worst(verification.MEAN) > BSSA_TABULATED_MEAN_TOLERANCE, (
        "if the interpolated periods now agree as tightly as the tabulated ones, the coefficient "
        "table changed and the tolerance table in docs/RISK.md is stale"
    )


@pytest.mark.parametrize("directory", ["bssa14", "bchydro_sinter"])
def test_verification_fixtures_match_their_recorded_digests(directory: str) -> None:
    """A fixture that has drifted from its provenance is not a reference value any more."""
    provenance = json.loads(
        (GSIM_FIXTURES / directory / "provenance.json").read_text(encoding="utf-8")
    )
    assert provenance["licence"] == "AGPL-3.0-or-later"
    assert provenance["source"] == "gem/oq-engine"
    for record in provenance["files"]:
        payload = (GSIM_FIXTURES / directory / record["file"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == record["sha256"], record["file"]


def test_coefficient_tables_match_their_recorded_digests() -> None:
    """The coefficients rupture evaluates are the ones it says it extracted."""
    data = REPO_ROOT / "src" / "rupture" / "adapters" / "groundmotion" / "data"
    provenance = json.loads((data / "provenance.json").read_text(encoding="utf-8"))
    assert provenance["source"] == "gem/oq-engine"
    assert provenance["primary_sources"]
    for record in provenance["files"]:
        text = (data / record["file"]).read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode("utf-8")).hexdigest() == record["sha256"], record["file"]


def test_coeff_table_interpolates_in_log_period() -> None:
    """The interpolation rule is OpenQuake's, and a period outside the table is refused."""
    table = coeffs.CoeffTable.from_text(
        "IMT a\npga 1.0\n0.1 0.0\n1.0 10.0\n",
    )
    assert table[Imt("PGA")]["a"] == 1.0
    # log-linear between 0.1 and 1.0: at 0.31622776... the ratio is exactly 0.5
    midpoint = table[Imt("SA", 0.31622776601683794)]["a"]
    assert midpoint == pytest.approx(5.0)
    with pytest.raises(coeffs.CoeffTableError, match="outside"):
        table[Imt("SA", 5.0)]


def test_an_unsupported_imt_is_a_failure_not_a_skip() -> None:
    entry = registry.BY_NAME["AbrahamsonEtAl2015SInter"]
    tables = registry.verification_tables(entry, REPO_ROOT)
    with pytest.raises(verification.VerificationError, match="does not support"):
        verification.verify(
            entry.build(),
            {verification.MEAN: tables[verification.MEAN]},
            imts=(Imt("SA", 99.0),),
        )
