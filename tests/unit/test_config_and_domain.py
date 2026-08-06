from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_ran_assurance.config import NetworkSettings, _read_yaml, load_config
from ai_ran_assurance.domain.enums import ActionType, FaultType, RootCauseCategory
from ai_ran_assurance.domain.models import (
    CorrectiveAction,
    FaultScenario,
    KPISample,
    NetworkTopology,
)
from ai_ran_assurance.simulation import KPIGenerator, build_network


def test_load_config_and_lookup() -> None:
    config = load_config()
    assert config.network.cell_count == 20
    assert len(config.scenarios) == 8
    assert config.scenario("outage").fault_type is FaultType.CELL_OUTAGE
    with pytest.raises(ValueError, match="unknown scenario"):
        config.scenario("not-real")


def test_packaged_defaults_do_not_depend_on_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = load_config(Path(__file__).parents[2] / "config")
    monkeypatch.chdir(tmp_path)
    assert load_config() == expected


def test_yaml_reader_rejects_invalid_sources(tmp_path: Path) -> None:
    scalar = tmp_path / "scalar.yaml"
    scalar.write_text("hello\n", encoding="utf-8")
    with pytest.raises(ValueError, match="YAML mapping"):
        _read_yaml(scalar)
    with pytest.raises(ValueError, match="cannot load"):
        _read_yaml(tmp_path / "missing.yaml")


def test_invalid_project_configuration(tmp_path: Path) -> None:
    (tmp_path / "network.yaml").write_text("cell_count: 2\n", encoding="utf-8")
    (tmp_path / "thresholds.yaml").write_text("latency_max_ms: nope\n", encoding="utf-8")
    (tmp_path / "scenarios.yaml").write_text("scenarios: []\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid project configuration"):
        load_config(tmp_path)


def test_network_baseline_must_cover_the_daily_profile() -> None:
    values = load_config().network.model_dump()
    with pytest.raises(ValidationError, match="at least 24 hours"):
        NetworkSettings.model_validate(values | {"baseline_steps": 48})


def test_fault_scenario_validation_and_active_window() -> None:
    with pytest.raises(ValidationError, match="cannot use normal"):
        FaultScenario(
            name="invalid",
            fault_type=FaultType.CELL_OUTAGE,
            target_cells=["CELL-001"],
            start_step=1,
            duration=2,
            severity=1,
            affected_kpis=["availability_pct"],
            ground_truth=RootCauseCategory.NORMAL,
        )
    scenario = load_config().scenario("outage")
    assert scenario.active("CELL-012", scenario.start_step)
    assert not scenario.active("CELL-012", scenario.start_step + scenario.duration)
    assert not scenario.active("CELL-001", scenario.start_step)


def test_fault_scenario_rejects_inconsistent_truth_kpis_and_duplicates() -> None:
    scenario = load_config().scenario("outage")
    values = scenario.model_dump()
    with pytest.raises(ValidationError, match="requires ground truth"):
        FaultScenario.model_validate(values | {"ground_truth": "coverage"})
    with pytest.raises(ValidationError, match="unknown affected KPIs"):
        FaultScenario.model_validate(values | {"affected_kpis": ["vendor_magic_kpi"]})
    with pytest.raises(ValidationError, match="target cells must be unique"):
        FaultScenario.model_validate(values | {"target_cells": ["CELL-012", "CELL-012"]})
    with pytest.raises(ValidationError, match="invalid fault target cells"):
        FaultScenario.model_validate(values | {"target_cells": ["not-a-cell"]})
    with pytest.raises(ValidationError, match="affected KPIs must be"):
        FaultScenario.model_validate(values | {"affected_kpis": ["availability_pct"]})


def test_domain_models_reject_naive_time_nonfinite_values_and_extra_fields() -> None:
    config = load_config()
    sample = KPIGenerator(build_network(config.network), config.network).generate(1)[0]
    values = sample.model_dump()
    with pytest.raises(ValidationError, match="timezone"):
        KPISample.model_validate(values | {"timestamp": datetime(2026, 1, 1)})
    with pytest.raises(ValidationError):
        KPISample.model_validate(values | {"sinr_db": float("nan")})
    with pytest.raises(ValidationError, match="extra_forbidden"):
        KPISample.model_validate(values | {"vendor_extension": 1})


def test_corrective_actions_have_closed_parameter_schemas() -> None:
    base = {
        "action_id": "test-action",
        "cell_id": "CELL-001",
        "diagnosis_confidence": 0.9,
        "rationale": "test candidate",
        "proposed_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    valid = CorrectiveAction.model_validate(
        base
        | {
            "action_type": ActionType.ACTIVATE_CAPACITY,
            "parameters": {"capacity_delta_pct": 15},
        }
    )
    assert valid.parameters == {"capacity_delta_pct": 15}
    with pytest.raises(ValidationError, match="parameters must be exactly"):
        CorrectiveAction.model_validate(
            base
            | {
                "action_type": ActionType.ACTIVATE_CAPACITY,
                "parameters": {"capacity_delta_pct": 15, "command": "apply-now"},
            }
        )
    with pytest.raises(ValidationError, match="differ from the source"):
        CorrectiveAction.model_validate(
            base
            | {
                "action_type": ActionType.STEER_TRAFFIC,
                "parameters": {"target_cell": "CELL-001", "traffic_delta_pct": 10},
            }
        )


def test_topology_rejects_duplicate_and_unknown_relations() -> None:
    config = load_config()
    topology = build_network(config.network)
    values = topology.model_dump()
    duplicate = values["neighbor_relations"][0]
    with pytest.raises(ValidationError, match="relations must be unique"):
        NetworkTopology.model_validate(
            values | {"neighbor_relations": values["neighbor_relations"] + [duplicate]}
        )
    unknown = duplicate | {"target_cell": "CELL-999"}
    with pytest.raises(ValidationError, match="unknown cells"):
        NetworkTopology.model_validate(
            values | {"neighbor_relations": values["neighbor_relations"] + [unknown]}
        )
