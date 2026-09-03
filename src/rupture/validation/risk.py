"""``validate-risk``: the loss layer produces a usable, sourced answer, offline.

Runs from a fresh clone with no network and no Docker. What it checks, in order:

1. **A GSIM verification test passes.** Every entry in the native registry is run against
   OpenQuake's committed expected values and must meet its stated tolerance (ADR-0020). Both the
   fixture digests and the coefficient-table digests are checked first, so the gate cannot pass on
   tables that have drifted from their provenance.
2. **``native_gsim`` produces a scenario ground-motion field** for the Gorkha-repeat rupture at
   the corridor's sites, with finite, positive values.
3. **Loss intervals are finite and ordered** for the portfolio total and for every asset.
4. **The avoided-loss contract round-trips** — a request with each implemented intervention kind
   is answered, and the response validates against ``contracts/avoided-loss.v1.json``.
5. **The Nepal portfolio run completes and every figure carries provenance**: the portfolio's own
   ``Provenance``, a ``ModelProvenance`` on every ``MoneyRange``, and the honesty rule that a stub
   response may claim only ``ConfidenceTier.UNQUALIFIED``.

The gate never uses the live serac export even when it is present: it pins the committed fallback
so the result does not depend on what happens to sit in a sibling directory.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

import jsonschema

from rupture.adapters.exposure.serac_export import FALLBACK_REL, SeracExposureSource
from rupture.adapters.groundmotion import NativeGsimEngine, verification
from rupture.adapters.groundmotion import registry as gsim_registry
from rupture.domain import contracts
from rupture.domain.avoided_loss_v1 import (
    AvoidedLossRequestV1,
    Intervention,
    InterventionKind,
    ResponseStatus,
)
from rupture.domain.loss import ExposurePortfolio, TriggerKind
from rupture.domain.money import ModelProvenance
from rupture.risk import avoided_loss, loss, scenarios
from rupture.validation.result import GateResult, GateStatus

GATE = "validate-risk"
AOI = "lhende-khola-trishuli"
ASSETS_FILE = "exposed_assets.geojson"
GATE_REALISATIONS = 200
GATE_SEED = 20260903
MIN_ASSETS = 9


def run(repo_root: Path) -> GateResult:
    findings: list[str] = []
    problems: list[str] = []

    problems.extend(_check_fixture_digests(repo_root, findings))
    problems.extend(_check_gsims(repo_root, findings))

    portfolio = _committed_portfolio(repo_root)
    findings.append(
        f"portfolio: {portfolio.id}, {len(portfolio.assets)} assets, {portfolio.currency}"
    )
    problems.extend(_check_portfolio_provenance(portfolio))

    rupture = scenarios.gorkha_2015_repeat(repo_root)
    findings.append(f"scenario: {rupture.id} M{rupture.magnitude:.2f}")
    config = loss.RunConfig(n_realisations=GATE_REALISATIONS, seed=GATE_SEED)
    engine = NativeGsimEngine()
    sites = loss.sites_for(portfolio)
    field = engine.scenario(
        rupture,
        sites,
        imt=config.imt,
        gsim=config.gsim,
        n_realisations=config.n_realisations,
        truncation_level=config.truncation_level,
        seed=config.seed,
    )
    problems.extend(_check_field(field, findings))

    result = loss.run_scenario(portfolio, rupture, engine=engine, config=config)
    findings.extend(result.lines()[:6])
    problems.extend(_check_loss(result))

    problems.extend(_check_avoided_loss(repo_root, portfolio, config, findings))

    if problems:
        findings.extend(problems[:50])
        if len(problems) > 50:
            findings.append(f"... {len(problems) - 50} more")
        return GateResult(name=GATE, status=GateStatus.FAILED, findings=findings)
    findings.append(
        "checks: GSIM vectors reproduced, GMF finite, loss intervals ordered, "
        "avoided-loss contract round-trips, every figure carries provenance"
    )
    return GateResult(name=GATE, status=GateStatus.PASSED, findings=findings)


# ------------------------------------------------------------------ checks
def _check_fixture_digests(repo_root: Path, findings: list[str]) -> list[str]:
    """Committed reference data must still match the digests its provenance records."""
    problems: list[str] = []
    directories = [
        gsim_registry.fixture_root(repo_root) / entry.directory for entry in gsim_registry.ENTRIES
    ]
    directories.append(
        repo_root / "src" / "rupture" / "adapters" / "groundmotion" / "data",
    )
    directories.append(repo_root / "tests" / "fixtures" / "risk" / "vulnerability" / "hazus51")
    for directory in dict.fromkeys(directories):
        provenance_path = directory / "provenance.json"
        if not provenance_path.is_file():
            problems.append(f"missing provenance.json in {directory}")
            continue
        record = json.loads(provenance_path.read_text(encoding="utf-8"))
        for entry in record.get("files", []):
            payload = (directory / entry["file"]).read_bytes()
            if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                problems.append(f"digest mismatch: {directory.name}/{entry['file']}")
    findings.append(f"provenance digests checked in {len(set(directories))} fixture directories")
    return problems


def _check_gsims(repo_root: Path, findings: list[str]) -> list[str]:
    problems: list[str] = []
    for entry in gsim_registry.ENTRIES:
        tables = gsim_registry.verification_tables(entry, repo_root)
        missing = [str(p) for p in tables.values() if not p.is_file()]
        if missing:
            problems.append(f"{entry.name}: missing verification table(s) {missing}")
            continue
        report = verification.verify(entry.build(), tables)
        worst_mean = report.worst(verification.MEAN)
        worst_std = max(
            report.worst(result_type)
            for result_type in (verification.TOTAL, verification.INTER, verification.INTRA)
        )
        findings.append(
            f"{entry.name}: {report.comparisons} reference values, worst mean "
            f"{worst_mean:.4g} % (tolerance {entry.mean_tolerance_percent} %), worst stddev "
            f"{worst_std:.4g} % (tolerance {entry.stddev_tolerance_percent} %)"
        )
        if worst_mean > entry.mean_tolerance_percent:
            problems.append(f"{entry.name}: mean discrepancy {worst_mean:.4g} % over tolerance")
        if worst_std > entry.stddev_tolerance_percent:
            problems.append(f"{entry.name}: stddev discrepancy {worst_std:.4g} % over tolerance")
    return problems


def _committed_portfolio(repo_root: Path) -> ExposurePortfolio:
    """Always the committed fallback, so the gate does not depend on a sibling checkout."""
    source = SeracExposureSource(repo_root=repo_root)
    path = repo_root / FALLBACK_REL / AOI / ASSETS_FILE
    return source.load(path, portfolio_id="trishuli-corridor")


def _check_portfolio_provenance(portfolio: ExposurePortfolio) -> list[str]:
    problems: list[str] = []
    provenance = portfolio.provenance
    if not provenance.sha256:
        problems.append("the portfolio's provenance has no sha256")
    if not provenance.source_url:
        problems.append("the portfolio's provenance has no source_url")
    if not provenance.notes or "valuation" not in provenance.notes:
        problems.append("the portfolio's provenance does not state its valuation basis")
    if len(portfolio.assets) < MIN_ASSETS:
        problems.append(f"only {len(portfolio.assets)} assets in the committed portfolio")
    if not any(a.value > 0.0 for a in portfolio.assets):
        problems.append("no asset in the portfolio carries a replacement value")
    return problems


def _check_field(field: object, findings: list[str]) -> list[str]:
    problems: list[str] = []
    values = getattr(field, "values", ())
    if not values:
        return ["the native engine produced no ground-motion field"]
    flat = [v for row in values for v in row]
    if not all(math.isfinite(v) and v > 0.0 for v in flat):
        problems.append("the ground-motion field has a non-finite or non-positive value")
    findings.append(
        f"ground-motion field: {len(values)} realisations x {len(values[0])} sites, "
        f"median PGA {min(flat):.3g} to {max(flat):.3g} g across all realisations"
    )
    return problems


def _check_loss(result: loss.PortfolioLoss) -> list[str]:
    problems: list[str] = []
    total = result.total
    for label, money in [
        ("total", total),
        *[(al.asset_id, al.expected_loss) for al in result.by_asset],
    ]:
        for name, value in (("low", money.low), ("high", money.high), ("best", money.best or 0.0)):
            if not math.isfinite(value):
                problems.append(f"{label}: {name} is not finite")
        if money.low > money.high:
            problems.append(f"{label}: interval is inverted ({money.low} > {money.high})")
        if money.best is not None and not money.low <= money.best <= money.high:
            problems.append(f"{label}: best estimate lies outside its interval")
        if money.provenance is ModelProvenance.PUBLISHED and not money.source_refs:
            problems.append(f"{label}: claims published provenance with no source_refs")
        if not money.basis:
            problems.append(f"{label}: no basis recorded")
    if total.best is None or total.best <= 0.0:
        problems.append("the portfolio loss is zero or missing for a M7.8 scenario at the corridor")
    if not result.assumptions:
        problems.append("the loss result records no assumptions, which cannot be right")
    if not result.modelled_asset_ids:
        problems.append("no asset was modelled")
    return problems


def _check_avoided_loss(
    repo_root: Path,
    portfolio: ExposurePortfolio,
    config: loss.RunConfig,
    findings: list[str],
) -> list[str]:
    problems: list[str] = []
    request = AvoidedLossRequestV1(
        request_id="gate-risk-0001",
        requested_at=datetime(2026, 9, 3, tzinfo=UTC),
        portfolio=portfolio,
        trigger_kind=TriggerKind.SCENARIO,
        trigger_id="gorkha-2015-repeat",
        interventions=(
            Intervention(
                id="retrofit", kind=InterventionKind.STRUCTURAL_RETROFIT, description="anchor"
            ),
            Intervention(
                id="shutdown", kind=InterventionKind.AUTOMATED_SHUTDOWN, description="trip"
            ),
            Intervention(
                id="exclude",
                kind=InterventionKind.LAND_USE_EXCLUSION,
                description="do not site here",
                applies_to_asset_ids=(portfolio.assets[0].id,),
            ),
            Intervention(
                id="layer",
                kind=InterventionKind.INSURANCE_LAYER,
                description="excess of loss",
                parameters={"attachment": 1.0e8, "limit": 2.0e8},
            ),
        ),
        consumer="validate-risk",
    )
    response = avoided_loss.respond(request, repo_root=repo_root, config=config)
    if response.status is not ResponseStatus.OK:
        return [
            f"avoided-loss request was not answered: {response.status.value} {response.message}"
        ]
    schema = contracts.schema_for("avoided-loss.v1.json")
    payload = {
        "request": request.model_dump(mode="json"),
        "response": response.model_dump(mode="json"),
    }
    try:
        jsonschema.validate(payload, schema)
    except jsonschema.ValidationError as exc:
        problems.append(f"avoided-loss v1 round-trip failed: {exc.message}")
    reparsed = AvoidedLossRequestV1.model_validate(payload["request"])
    if reparsed.request_id != request.request_id:
        problems.append("the request did not round-trip through its own JSON")

    for outcome in response.interventions:
        avoided_money = outcome.avoided_vs_baseline
        if not math.isfinite(avoided_money.low) or not math.isfinite(avoided_money.high):
            problems.append(f"{outcome.intervention_id}: avoided interval is not finite")
        if avoided_money.low > avoided_money.high:
            problems.append(f"{outcome.intervention_id}: avoided interval is inverted")
        if avoided_money.provenance is ModelProvenance.STUB:
            problems.append(f"{outcome.intervention_id}: avoided figure is a stub")
    if response.provenance is None or not response.provenance.adapter_version:
        problems.append("the response carries no provenance")
    findings.append(
        f"avoided loss: {len(response.interventions)} interventions priced on "
        f"{response.n_realisations} shared realisations; contract v1 round-trip OK"
    )
    findings.extend(
        f"  {o.intervention_id}: avoided {o.avoided_vs_baseline.best:,.0f} "
        f"{o.avoided_vs_baseline.currency}"
        for o in response.interventions
    )
    return problems


if __name__ == "__main__":  # pragma: no cover - `mk/risk.mk` entry point
    import sys

    outcome = run(Path(__file__).resolve().parents[3])
    print(outcome.render())
    sys.exit(0 if outcome.ok else 1)
