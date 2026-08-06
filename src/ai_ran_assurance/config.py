from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ai_ran_assurance.domain.models import FaultScenario


class StrictSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NetworkSettings(StrictSettings):
    seed: int = 42
    cell_count: int = Field(ge=20)
    interval_minutes: int = Field(gt=0)
    baseline_steps: int = Field(ge=48)
    capacity_mbps: float = Field(gt=0)
    transmit_power_dbm: float
    traffic_profile: str


class ThresholdSettings(StrictSettings):
    rsrp_min_dbm: float
    sinr_min_db: float
    bler_max_pct: float = Field(gt=0, le=100)
    prb_utilization_max_pct: float = Field(gt=0, le=100)
    throughput_min_mbps: float = Field(gt=0)
    rrc_success_min_pct: float = Field(gt=0, le=100)
    handover_success_min_pct: float = Field(gt=0, le=100)
    call_drop_max_pct: float = Field(gt=0, le=100)
    latency_max_ms: float = Field(gt=0)
    availability_min_pct: float = Field(gt=0, le=100)
    zscore_limit: float = Field(gt=0)
    rolling_window: int = Field(ge=3)
    max_parameter_delta: float = Field(gt=0)
    cooldown_minutes: int = Field(ge=0)
    telemetry_max_age_minutes: int = Field(gt=0)
    prediction_confidence_min: float = Field(ge=0, le=1)
    availability_max_drop_pct: float = Field(ge=0)


class ScenarioSettings(StrictSettings):
    scenarios: list[FaultScenario] = Field(min_length=8)


class ProjectConfig(BaseModel):
    network: NetworkSettings
    thresholds: ThresholdSettings
    scenarios: list[FaultScenario]

    def scenario(self, name: str) -> FaultScenario:
        try:
            return next(item for item in self.scenarios if item.name == name)
        except StopIteration as exc:
            choices = ", ".join(item.name for item in self.scenarios)
            raise ValueError(f"unknown scenario {name!r}; choose from: {choices}") from exc


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load configuration {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"configuration {path} must contain a YAML mapping")
    return raw


def load_config(config_dir: str | Path = "config") -> ProjectConfig:
    directory = Path(config_dir)
    try:
        network = NetworkSettings.model_validate(_read_yaml(directory / "network.yaml"))
        thresholds = ThresholdSettings.model_validate(_read_yaml(directory / "thresholds.yaml"))
        scenario_settings = ScenarioSettings.model_validate(
            _read_yaml(directory / "scenarios.yaml")
        )
    except ValidationError as exc:
        raise ValueError(f"invalid project configuration: {exc}") from exc
    return ProjectConfig(
        network=network,
        thresholds=thresholds,
        scenarios=scenario_settings.scenarios,
    )
