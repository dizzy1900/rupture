"""The refit schedule is executed, and a running service picks up what it wrote.

``REFIT_SCHEDULE`` said when to refit and nothing ran it; a request whose scheduled cutoff had no
persisted fit answered 503 forever. These tests drive
:func:`rupture.services.aftershock.refit.run_refits` (the executor behind
``rupture aftershock refit``) and :class:`~rupture.services.aftershock.refit.FitsStore` (the
reader that makes a new fit servable without a restart).

The EM itself is not run here: a real fit of the Gorkha zone takes tens of seconds, so the walk is
driven with a stub fitter that re-labels a **committed real fit** at each cutoff. What is under
test is the schedule, the writing, and the pick-up — not the fitting, which
``tests/unit/aftershock/test_forecaster.py`` and ``make validate-aftershock`` cover.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rupture.domain import Catalog, FitResult, Region
from rupture.services.aftershock.forecaster import AftershockForecaster, scheduled_fit_cutoff
from rupture.services.aftershock.refit import (
    FitsStore,
    cutoff_label,
    plan_refits,
    run_refits,
    scheduled_cutoffs,
)
from rupture.services.aftershock.sequences import (
    Mainshock,
    SequenceSpec,
    fits_dir,
    fixture_coverage_end,
    mainshock_from_catalog,
)
from rupture.services.aftershock.service import LoadedSequence, create_app

KEY = "refit-test-key"
HEADERS = {"X-API-Key": KEY}
SCHEDULE_POINTS_30D = 35  # +0 h, +1/3/6/12 h, then +1 d ... +30 d


@pytest.fixture
def shock(gorkha_catalog: Catalog, gorkha: SequenceSpec) -> Mainshock:
    return mainshock_from_catalog(gorkha_catalog, gorkha.mainshock.event_id)


def _stub_fitter(template: FitResult):
    """Re-label a committed fit at each cutoff, so the walk can be tested in milliseconds."""

    def fit(_catalog: Catalog, _region: Region, cutoff: datetime) -> FitResult:
        return template.model_copy(update={"fit_cutoff": cutoff})

    return fit


def test_the_schedule_starts_at_the_mainshock_and_stops_at_through(shock: Mainshock) -> None:
    """+0 matters: before +1 h the service uses a fit cut at the mainshock (ADR-0028 item 3)."""
    cutoffs = scheduled_cutoffs(shock.origin_time, through=timedelta(days=30))
    assert len(cutoffs) == SCHEDULE_POINTS_30D
    assert cutoffs[0] == shock.origin_time
    assert cutoffs[-1] == shock.origin_time + timedelta(days=30)
    assert scheduled_cutoffs(shock.origin_time, through=timedelta(days=1))[-1] == (
        shock.origin_time + timedelta(days=1)
    )


def test_the_plan_names_what_is_already_fitted_and_what_the_data_cannot_support(
    shock: Mainshock, gorkha_fits: dict[str, FitResult], gorkha: SequenceSpec, repo_root: Path
) -> None:
    coverage_end = fixture_coverage_end(gorkha, repo_root)
    plan = plan_refits(
        shock.origin_time,
        now=coverage_end,
        have=set(gorkha_fits),
        coverage_end=coverage_end,
    )
    by_status = {entry.status for entry in plan}
    assert "already-fitted" in by_status
    assert sum(1 for e in plan if e.status == "already-fitted") == len(gorkha_fits)
    assert all(e.reason for e in plan if e.status != "planned")
    # the committed slice ends well before +30 d after the mainshock
    beyond = [e for e in plan if e.status == "beyond-coverage"]
    assert beyond == [] or all(e.cutoff > coverage_end for e in beyond)


def test_a_cutoff_the_catalogue_cannot_support_is_refused_with_a_reason(shock: Mainshock) -> None:
    coverage_end = shock.origin_time + timedelta(days=2)
    plan = plan_refits(
        shock.origin_time, now=coverage_end, have=(), coverage_end=coverage_end, force=False
    )
    late = [e for e in plan if e.cutoff > coverage_end]
    assert late
    assert {e.status for e in late} == {"beyond-coverage"}
    assert "the catalogue is silent after" in (late[0].reason or "")


def test_the_runner_writes_a_fit_per_due_cutoff_and_records_provenance(
    tmp_path: Path,
    gorkha_catalog: Catalog,
    nepal_region: Region,
    shock: Mainshock,
    gorkha_fits: dict[str, FitResult],
) -> None:
    template = next(iter(gorkha_fits.values()))
    out = tmp_path / "fits"
    out.mkdir()
    outcomes = run_refits(
        catalog=gorkha_catalog,
        parent_region=nepal_region,
        mainshock=shock,
        fits_dir=out,
        now=shock.origin_time + timedelta(hours=12),
        through=timedelta(days=30),
        fitter=_stub_fitter(template),
    )
    written = [o for o in outcomes if o.status == "written"]
    assert [o.elapsed for o in written] == [
        timedelta(0),
        timedelta(hours=1),
        timedelta(hours=3),
        timedelta(hours=6),
        timedelta(hours=12),
    ]
    for outcome in written:
        assert (out / cutoff_label(outcome.cutoff) / "fit_result.json").is_file()
    meta = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert set(meta["fits"]) == {o.cutoff.isoformat() for o in written}
    assert meta["written_by"] == ["rupture aftershock refit"]
    assert meta["region_id"].startswith("aftershock-")


def test_a_second_run_refits_nothing_unless_forced(
    tmp_path: Path,
    gorkha_catalog: Catalog,
    nepal_region: Region,
    shock: Mainshock,
    gorkha_fits: dict[str, FitResult],
) -> None:
    template = next(iter(gorkha_fits.values()))
    out = tmp_path / "fits"
    out.mkdir()
    common = {
        "catalog": gorkha_catalog,
        "parent_region": nepal_region,
        "mainshock": shock,
        "fits_dir": out,
        "now": shock.origin_time + timedelta(hours=3),
        "fitter": _stub_fitter(template),
    }
    first = run_refits(**common)  # type: ignore[arg-type]
    assert sum(1 for o in first if o.status == "written") == 3

    again = run_refits(**common)  # type: ignore[arg-type]
    assert sum(1 for o in again if o.status == "written") == 0
    assert sum(1 for o in again if o.status == "already-fitted") == 3

    forced = run_refits(**common, force=True)  # type: ignore[arg-type]
    assert sum(1 for o in forced if o.status == "written") == 3


def test_a_dry_run_writes_nothing(
    tmp_path: Path,
    gorkha_catalog: Catalog,
    nepal_region: Region,
    shock: Mainshock,
    gorkha_fits: dict[str, FitResult],
) -> None:
    out = tmp_path / "fits"
    out.mkdir()
    outcomes = run_refits(
        catalog=gorkha_catalog,
        parent_region=nepal_region,
        mainshock=shock,
        fits_dir=out,
        now=shock.origin_time + timedelta(days=30),
        fitter=_stub_fitter(next(iter(gorkha_fits.values()))),
        dry_run=True,
    )
    assert {o.status for o in outcomes} == {"planned"}
    assert list(out.iterdir()) == []


def test_the_fits_store_reloads_when_a_fit_appears(
    tmp_path: Path, gorkha: SequenceSpec, repo_root: Path
) -> None:
    committed = fits_dir(gorkha, repo_root)
    live = tmp_path / "fits"
    live.mkdir()
    store = FitsStore(live)
    assert store.fits() == {}

    source = sorted(committed.glob("*/fit_result.json"))[0]
    shutil.copytree(source.parent, live / source.parent.name)
    assert len(store.fits()) == 1
    assert not store.problems


def test_a_fit_written_while_the_service_is_up_becomes_servable(  # noqa: PLR0917
    tmp_path: Path,
    repo_root: Path,
    gorkha: SequenceSpec,
    gorkha_catalog: Catalog,
    nepal_region: Region,
    fast_forecaster: AftershockForecaster,
) -> None:
    """The other half of "refit on a schedule": no restart between the refit and the request."""
    committed = fits_dir(gorkha, repo_root)
    live = tmp_path / "fits"
    live.mkdir()
    early = shutil.copytree(
        committed / cutoff_label(gorkha.mainshock.origin_time + timedelta(days=1)),
        live / cutoff_label(gorkha.mainshock.origin_time + timedelta(days=1)),
    )
    assert early.is_dir()

    sequence = LoadedSequence(
        id="gorkha",
        catalog=gorkha_catalog,
        parent_region=nepal_region,
        fits_store=FitsStore(live),
    )
    client = TestClient(
        create_app(
            api_key=KEY,
            forecaster=fast_forecaster,
            sequences={"gorkha": sequence},
        )
    )
    at_seven_days = gorkha.mainshock.origin_time + timedelta(days=7)
    body = {
        "mainshock_id": gorkha.mainshock.event_id,
        "sequence": "gorkha",
        "issue_time": at_seven_days.isoformat(),
        "horizon": "1d",
        "n_simulations": 1,
    }
    refused = client.post("/aftershock/forecast", json=body, headers=HEADERS)
    assert refused.status_code == 503
    assert "rupture aftershock refit" in refused.json()["detail"]

    # what `rupture aftershock refit` does: write the fit for the scheduled cutoff
    cutoff = scheduled_fit_cutoff(gorkha.mainshock.origin_time, at_seven_days)
    shutil.copytree(committed / cutoff_label(cutoff), live / cutoff_label(cutoff))

    served = client.post("/aftershock/forecast", json=body, headers=HEADERS)
    assert served.status_code == 200, served.text
    assert client.get("/healthz").json()["fits_loaded"]["gorkha"] == [
        (gorkha.mainshock.origin_time + timedelta(days=1)).isoformat(),
        cutoff.isoformat(),
    ]
