from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_ran_assurance.config import _read_yaml, load_config
from ai_ran_assurance.domain.enums import FaultType, RootCauseCategory
from ai_ran_assurance.domain.models import FaultScenario


def test_load_config_and_lookup() -> None:
    config = load_config()
    assert config.network.cell_count == 20
    assert len(config.scenarios) == 8
    assert config.scenario("outage").fault_type is FaultType.CELL_OUTAGE
    with pytest.raises(ValueError, match="unknown scenario"):
        config.scenario("not-real")


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
