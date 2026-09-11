"""The registry is the only door in, and decision 6 is enforced by code, not by prose."""

from __future__ import annotations

import pytest

from rupture.domain.hypothesis import ARM_DESCRIPTION, MANDATORY_REFERENCE, HypothesisArm
from rupture.scoring import refusals
from rupture.scoring.errors import ArmNotImplementedError, RefusedMetricError
from rupture.scoring.registry import implemented_arms, registry_table, scorer_for


def test_only_the_alarm_arm_is_scored_today() -> None:
    assert implemented_arms() == (HypothesisArm.ALARM_SET,)


@pytest.mark.parametrize(
    "arm",
    [a for a in HypothesisArm if a is not HypothesisArm.ALARM_SET],
)
def test_an_unimplemented_arm_refuses_by_name_rather_than_approximating(
    arm: HypothesisArm,
) -> None:
    with pytest.raises(ArmNotImplementedError) as exc:
        scorer_for(arm)
    message = str(exc.value)
    assert arm.value in message
    assert MANDATORY_REFERENCE[arm] in message


def test_the_alarm_arm_carries_its_mandatory_reference() -> None:
    entry = scorer_for(HypothesisArm.ALARM_SET)
    assert "clustering-aware" in entry.mandatory_reference
    assert "matched on alarm rate and spatial footprint" in entry.mandatory_reference


def test_every_arm_is_described_and_has_a_named_reference() -> None:
    for arm in HypothesisArm:
        assert ARM_DESCRIPTION[arm]
        assert MANDATORY_REFERENCE[arm]
    rows = registry_table()
    assert len(rows) == len(HypothesisArm)
    assert all(r["reference"] for r in rows)


@pytest.mark.parametrize("metric", ["auc", "accuracy", "rmse", "mae", "parimutuel", "random_split"])
def test_the_banned_metrics_refuse_with_their_citation(metric: str) -> None:
    with pytest.raises(RefusedMetricError) as exc:
        refusals.refuse(metric)
    assert metric in str(exc.value)
    assert len(str(exc.value)) > 80, "a refusal without its reason teaches nobody anything"


def test_a_cross_referencing_refusal_carries_the_full_reason_not_a_pointer() -> None:
    """A refusal that says only "see the other one" is one somebody will override."""
    assert "DeVries" in refusals.reason_for("accuracy")
    assert "power-law" in refusals.reason_for("mae")
    assert not refusals.reason_for("accuracy").startswith("@")


def test_an_unregistered_metric_is_refused_by_default() -> None:
    with pytest.raises(RefusedMetricError, match="not a registered scorer"):
        refusals.refuse("f1_score")


@pytest.mark.parametrize(
    "fn", [refusals.auc, refusals.accuracy, refusals.rmse, refusals.parimutuel]
)
def test_the_convenience_wrappers_refuse_too(fn: object) -> None:
    with pytest.raises(RefusedMetricError):
        fn()  # type: ignore[operator]


def test_the_auc_refusal_names_the_rebuttal_in_the_same_breath() -> None:
    """ADR-0058: a `rebutted` work is never cited as support without its rebuttal."""
    text = refusals.REFUSED["auc"]
    assert "DeVries" in text
    assert "Mignan" in text
    assert "Broccardo" in text
    assert "rebutted" in text
