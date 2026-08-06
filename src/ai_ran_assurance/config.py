import os
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_ran_assurance.domain.models import FaultScenario


class StrictSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NetworkSettings(StrictSettings):
    seed: int = 42
    cell_count: int = Field(ge=20, le=500)
    interval_minutes: int = Field(gt=0, le=60)
    baseline_steps: int = Field(ge=48, le=10_000)
    capacity_mbps: float = Field(gt=0, le=100_000)
    transmit_power_dbm: float = Field(ge=0, le=80)
    traffic_profile: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_baseline_duration(self) -> "NetworkSettings":
        if self.baseline_steps * self.interval_minutes < 24 * 60:
            raise ValueError("baseline must span at least 24 hours")
        return self


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
    prediction_confidence_min: float = Field(gt=0, le=1)
    diagnosis_confidence_min: float = Field(gt=0, le=1)
    availability_max_drop_pct: float = Field(ge=0)
    max_telemetry_future_skew_seconds: int = Field(ge=0, le=300)
    max_traffic_steering_pct: float = Field(gt=0, le=50)
    max_capacity_increase_pct: float = Field(gt=0, le=100)

    @model_validator(mode="after")
    def validate_policy_consistency(self) -> "ThresholdSettings":
        if self.availability_max_drop_pct > 100 - self.availability_min_pct:
            raise ValueError("availability_max_drop_pct cannot exceed the margin below the minimum")
        return self


class ScenarioSettings(StrictSettings):
    scenarios: list[FaultScenario] = Field(min_length=8)


class ProjectConfig(StrictSettings):
    network: NetworkSettings
    thresholds: ThresholdSettings
    scenarios: list[FaultScenario]

    @model_validator(mode="after")
    def validate_scenarios(self) -> "ProjectConfig":
        names = [scenario.name for scenario in self.scenarios]
        if len(names) != len(set(names)):
            raise ValueError("scenario names must be unique")
        known_cells = {f"CELL-{index + 1:03d}" for index in range(self.network.cell_count)}
        for scenario in self.scenarios:
            unknown = set(scenario.target_cells) - known_cells
            if unknown:
                raise ValueError(
                    f"scenario {scenario.name!r} targets unknown cells: {sorted(unknown)}"
                )
        return self

    def scenario(self, name: str) -> FaultScenario:
        try:
            return next(item for item in self.scenarios if item.name == name)
        except StopIteration as exc:
            choices = ", ".join(item.name for item in self.scenarios)
            raise ValueError(f"unknown scenario {name!r}; choose from: {choices}") from exc


def _parse_yaml(text: str, source: str) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"cannot parse configuration {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"configuration {source} must contain a YAML mapping")
    return raw


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        return _parse_yaml(path.read_text(encoding="utf-8"), str(path))
    except OSError as exc:
        raise ValueError(f"cannot load configuration {path}: {exc}") from exc


def _load_documents(config_dir: str | Path | None) -> tuple[dict[str, Any], ...]:
    selected = config_dir or os.getenv("AI_RAN_CONFIG_DIR")
    if selected is not None:
        directory = Path(selected)
        return tuple(
            _read_yaml(directory / name)
            for name in ("network.yaml", "thresholds.yaml", "scenarios.yaml")
        )
    defaults = resources.files("ai_ran_assurance").joinpath("default_config")
    return tuple(
        _parse_yaml(defaults.joinpath(name).read_text(encoding="utf-8"), f"package:{name}")
        for name in ("network.yaml", "thresholds.yaml", "scenarios.yaml")
    )


def load_config(config_dir: str | Path | None = None) -> ProjectConfig:
    try:
        network_document, threshold_document, scenario_document = _load_documents(config_dir)
        network = NetworkSettings.model_validate(network_document)
        thresholds = ThresholdSettings.model_validate(threshold_document)
        scenario_settings = ScenarioSettings.model_validate(scenario_document)
        return ProjectConfig(
            network=network,
            thresholds=thresholds,
            scenarios=scenario_settings.scenarios,
        )
    except ValidationError as exc:
        raise ValueError(f"invalid project configuration: {exc}") from exc
