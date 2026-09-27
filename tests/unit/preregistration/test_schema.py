"""Preregistration YAML/schema: parsed in memory, never as a fake experiment on disk."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from rupture.domain.hypothesis import HypothesisArm
from rupture.domain.preregistration import Preregistration, StatisticalPower
from rupture.preregistration import parse_preregistration_yaml

SAMPLE_YAML = """\
experiment_id: template-not-an-experiment
hypothesis: An ETAS-matched random alarm set has area skill consistent with one half.
arm: alarm_set
region_id: california
magnitude_min: 6.0
magnitude_max: 9.0
magnitude_scale: Mw (ANSS preferred)
lead_time: 7d
horizon: 30d
alarm_rate: 0.05
scoring_rule: molchan_area_skill
reference_baseline: ETAS-derived alarms and a matched random alarm set
as_of: "2026-01-01T00:00:00Z"
data_vintage: ComCat California fixture; C_D is the DVC pointer.
statistical_power:
  alpha: 0.05
  target_power: 0.8
  effect: probability gain G=2 against the clustering-aware reference
failure_criterion: Area skill consistent with 0.5, or minimum detectable G greater than 2.
test_data_paths:
  - data/fixtures/catalogs/california/provenance.json
"""


def test_a_complete_yaml_document_parses() -> None:
    record = parse_preregistration_yaml(SAMPLE_YAML)
    assert record.experiment_id == "template-not-an-experiment"
    assert record.arm is HypothesisArm.ALARM_SET
    assert record.lead_time == timedelta(days=7)
    assert record.horizon == timedelta(days=30)
    assert record.alarm_rate == 0.05
    assert record.as_of == datetime(2026, 1, 1, tzinfo=UTC)
    assert record.preregistration_commit is None
    assert record.statistical_power.target_power == 0.8
    assert record.test_data_paths == ("data/fixtures/catalogs/california/provenance.json",)


def test_missing_failure_criterion_is_rejected() -> None:
    stripped = "\n".join(
        line for line in SAMPLE_YAML.splitlines() if not line.startswith("failure_criterion:")
    )
    with pytest.raises(ValueError, match="failure_criterion"):
        parse_preregistration_yaml(stripped)


def test_alarm_rate_is_required_for_alarm_set() -> None:
    stripped = "\n".join(
        line for line in SAMPLE_YAML.splitlines() if not line.startswith("alarm_rate:")
    )
    with pytest.raises(ValueError, match="alarm_rate"):
        parse_preregistration_yaml(stripped)


def test_alarm_rate_is_optional_for_a_rate_forecast() -> None:
    record = parse_preregistration_yaml(SAMPLE_YAML)
    swapped = record.model_copy(update={"arm": HypothesisArm.RATE_FORECAST, "alarm_rate": None})
    assert swapped.alarm_rate is None
    assert swapped.arm is HypothesisArm.RATE_FORECAST


def test_extra_fields_are_forbidden() -> None:
    with pytest.raises(ValueError, match="Extra"):
        parse_preregistration_yaml(SAMPLE_YAML + "secret: 1\n")


def test_test_data_paths_must_be_relative() -> None:
    power = StatisticalPower(alpha=0.05, target_power=0.8, effect="G=2")
    with pytest.raises(ValidationError, match="relative"):
        Preregistration(
            experiment_id="x",
            hypothesis="h",
            arm=HypothesisArm.RATE_FORECAST,
            region_id="california",
            magnitude_min=5.0,
            magnitude_max=8.0,
            magnitude_scale="Mw",
            lead_time=timedelta(days=7),
            horizon=timedelta(days=30),
            scoring_rule="paired-t",
            reference_baseline="ETAS",
            as_of=datetime(2026, 1, 1, tzinfo=UTC),
            data_vintage="fixture",
            statistical_power=power,
            failure_criterion="no gain",
            test_data_paths=("../outside.txt",),
        )
